"""Smart City Navigation System: Flask application.

Run with:  python app.py
"""
import logging
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

import assistant
import database as db
from geo import GeoClient, GeoServiceError
from graph_algorithms import CityGraph, edge_key, run_algorithm

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("smartcity")


class RoadState:
    """Thread-safe set of closed roads (kept in memory, resets on restart)."""

    def __init__(self):
        self._closed = set()
        self._lock = threading.Lock()

    def snapshot(self):
        with self._lock:
            return frozenset(self._closed)

    def set_closed(self, a, b, closed):
        k = edge_key(a, b)
        with self._lock:
            if closed:
                self._closed.add(k)
            else:
                self._closed.discard(k)

    def toggle(self, a, b):
        k = edge_key(a, b)
        with self._lock:
            if k in self._closed:
                self._closed.remove(k)
                return False
            self._closed.add(k)
            return True

    def clear(self):
        with self._lock:
            self._closed.clear()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.environ.get("DATABASE_PATH", str(BASE_DIR / "instance" / "smartcity.db")),
        GRAPH_FILE=str(BASE_DIR / "data" / "city_graph.json"),
        NOMINATIM_URL=os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org"),
        OSRM_URL=os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org"),
        USER_AGENT=os.environ.get("GEO_USER_AGENT", "SmartCityNavigation-CollegeProject/2.0"),
        HTTP_TIMEOUT=float(os.environ.get("HTTP_TIMEOUT", "10")),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    db.init_db(app.config["DATABASE"])
    app.extensions["graph"] = CityGraph.from_json(app.config["GRAPH_FILE"])
    app.extensions["roads"] = RoadState()
    app.extensions["geo"] = GeoClient(app.config["NOMINATIM_URL"], app.config["OSRM_URL"],
                                      app.config["USER_AGENT"], app.config["HTTP_TIMEOUT"])

    graph = app.extensions["graph"]
    roads = app.extensions["roads"]

    # ---- helpers --------------------------------------------------------
    def get_db():
        if "db" not in g:
            g.db = db.connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    def payload():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else {}

    def err(message, status=400):
        return jsonify({"error": message}), status

    def graph_payload():
        closed = roads.snapshot()
        edges = [{"from": e["from"], "to": e["to"], "distance": e["distance"],
                  "closed": edge_key(e["from"], e["to"]) in closed} for e in graph.edge_list]
        return {
            "nodes": [{"id": n, "x": graph.positions[n][0], "y": graph.positions[n][1]}
                      for n in graph.nodes],
            "edges": edges,
            "closed": sorted([list(k) for k in closed]),
            "stats": {"vertices": len(graph.nodes), "edges": len(edges),
                      "open_edges": graph.open_edge_count(closed), "closed_edges": len(closed),
                      "components": len(graph.components(closed))},
        }

    def timed_run(algorithm, start, end, closed):
        t0 = time.perf_counter()
        res = run_algorithm(graph, algorithm, start, end, closed)
        res["runtime_ms"] = round((time.perf_counter() - t0) * 1000, 4)
        return res

    def log_run(res):
        try:
            db.add_algorithm_run(get_db(), res["algorithm"], res["start"], res.get("end"),
                                 res.get("distance"), res["visited_count"],
                                 res.get("reachable", True), res["runtime_ms"])
        except sqlite3.Error:
            log.exception("Could not record algorithm run")

    def clean_place(obj, label):
        if not isinstance(obj, dict):
            raise ValueError(f"Please choose a valid {label}.")
        name = str(obj.get("name", "")).strip()
        try:
            lat, lon = float(obj.get("lat")), float(obj.get("lon"))
        except (TypeError, ValueError):
            raise ValueError(f"The {label} has invalid coordinates.")
        if not name:
            raise ValueError(f"The {label} needs a name.")
        if not (math.isfinite(lat) and math.isfinite(lon)) or abs(lat) > 90 or abs(lon) > 180:
            raise ValueError(f"The {label} has coordinates outside the valid range.")
        return {"name": name[:200], "lat": lat, "lon": lon}

    # ---- pages ----------------------------------------------------------
    @app.route("/")
    def home():
        return render_template("index.html")

    # ---- educational graph ---------------------------------------------
    @app.get("/api/graph")
    def api_graph():
        return jsonify(graph_payload())

    @app.post("/api/algorithm")
    def api_algorithm():
        d = payload()
        algo = str(d.get("algorithm", "dijkstra")).lower()
        start, end = d.get("start", "University"), d.get("end", "Airport")
        try:
            res = timed_run(algo, start, end, roads.snapshot())
        except ValueError as e:
            return err(str(e))
        log_run(res)
        if algo == "dijkstra":
            closed = roads.snapshot()
            res["assistant"] = (assistant.explain_unreachable(graph, closed, start, end)
                                if not res["reachable"]
                                else assistant.graph_status(graph, closed, start, end))
        return jsonify(res)

    @app.post("/api/road")
    def api_road():
        d = payload()
        a, b = d.get("from"), d.get("to")
        if not isinstance(a, str) or not isinstance(b, str) or not graph.has_edge(a, b):
            return err("That road does not exist.")
        algo = str(d.get("algorithm", "dijkstra")).lower()
        start, end = d.get("start", "University"), d.get("end", "Airport")
        before_closed = roads.snapshot()
        try:
            before = run_algorithm(graph, algo, start, end, before_closed)
        except ValueError as e:
            return err(str(e))
        wanted = d.get("closed")
        if isinstance(wanted, bool):
            roads.set_closed(a, b, wanted)
        else:
            roads.toggle(a, b)
        after_closed = roads.snapshot()
        action = "closed" if edge_key(a, b) in after_closed else "reopened"
        after = timed_run(algo, start, end, after_closed)
        log_run(after)
        explanation = assistant.explain_reroute(graph, after_closed, algo, before, after, (a, b), action)
        return jsonify({
            "status": action, "from": a, "to": b, "graph": graph_payload(), "result": after,
            "before": {"path": before.get("path"), "distance": before.get("distance"),
                       "reachable": before.get("reachable"), "visited_count": before["visited_count"]},
            "assistant": explanation,
        })

    @app.get("/api/assistant/status")
    def api_assistant_status():
        start, end = request.args.get("start", ""), request.args.get("end", "")
        if not graph.has_node(start) or not graph.has_node(end):
            return err("Please select valid locations.")
        return jsonify(assistant.graph_status(graph, roads.snapshot(), start, end))

    @app.post("/api/roads/reset")
    def api_roads_reset():
        roads.clear()
        return jsonify({"graph": graph_payload()})

    # ---- real-map services ---------------------------------------------
    @app.get("/api/geocode")
    def api_geocode():
        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return err("Type at least 2 characters to search for a place.")
        if len(q) > 200:
            return err("That search is too long.")
        try:
            return jsonify({"results": app.extensions["geo"].geocode(q)})
        except GeoServiceError as e:
            return err(e.message, e.status)

    @app.post("/api/route")
    def api_route():
        d = payload()
        try:
            origin = clean_place(d.get("origin"), "starting point")
            dest = clean_place(d.get("destination"), "destination")
        except ValueError as e:
            return err(str(e))
        if abs(origin["lat"] - dest["lat"]) < 1e-5 and abs(origin["lon"] - dest["lon"]) < 1e-5:
            return err("The starting point and destination are the same place.")
        try:
            routes = app.extensions["geo"].route(origin, dest)
        except GeoServiceError as e:
            return err(e.message, e.status)
        summary = assistant.summarize_routes(routes, origin["name"], dest["name"])
        best = routes[summary["recommended"]]
        for i, r in enumerate(routes):
            r["is_fastest"] = i == summary["fastest"]
            r["is_shortest"] = i == summary["shortest"]
        history_id = None
        try:
            history_id = db.add_history(get_db(), origin, dest, best["distance"],
                                        best["duration"], len(routes))
        except sqlite3.Error:
            log.exception("Could not save route history")
        return jsonify({"routes": routes, "assistant": summary, "history_id": history_id,
                        "note": "Durations are free-flow estimates; no live traffic is included."})

    # ---- history --------------------------------------------------------
    @app.get("/api/history")
    def api_history():
        conn = get_db()
        return jsonify({"items": db.list_history(conn),
                        "recent_locations": db.recent_locations(conn)})

    @app.delete("/api/history/<int:hid>")
    def api_history_delete(hid):
        if not db.delete_history(get_db(), hid):
            return err("That history entry no longer exists.", 404)
        return jsonify({"deleted": hid})

    @app.delete("/api/history")
    def api_history_clear():
        return jsonify({"deleted": db.clear_history(get_db())})

    # ---- favourites -----------------------------------------------------
    @app.get("/api/favourites")
    def api_favourites():
        return jsonify({"items": db.list_favourites(get_db())})

    @app.post("/api/favourites")
    def api_favourites_add():
        try:
            place = clean_place(payload(), "location")
        except ValueError as e:
            return err(str(e))
        try:
            fid = db.add_favourite(get_db(), place["name"], place["lat"], place["lon"])
        except db.DuplicateFavourite:
            return err(f"“{place['name']}” is already in your favourites.", 409)
        return jsonify({"id": fid, **place}), 201

    @app.delete("/api/favourites/<int:fid>")
    def api_favourites_delete(fid):
        if not db.delete_favourite(get_db(), fid):
            return err("That favourite no longer exists.", 404)
        return jsonify({"deleted": fid})

    # ---- analytics ------------------------------------------------------
    @app.get("/api/analytics")
    def api_analytics():
        return jsonify(db.analytics(get_db()))

    # ---- error handling ---------------------------------------------------
    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return err("Not found.", 404)
        return "Page not found", 404

    @app.errorhandler(405)
    def bad_method(_e):
        return err("Method not allowed.", 405)

    @app.errorhandler(500)
    def server_error(_e):
        if request.path.startswith("/api/"):
            return err("Something went wrong on the server. Please try again.", 500)
        return "Server error", 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG", "0") == "1")
