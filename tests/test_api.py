"""API tests: routes, validation, history, favourites, analytics, network failures."""
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

import app as app_module

FAKE_NOMINATIM = [{"name": "Chandigarh University", "display_name": "Chandigarh University, Gharuan, Punjab, India",
                   "lat": "30.7690", "lon": "76.5750"}]
FAKE_OSRM = {"code": "Ok", "routes": [
    {"distance": 20000.0, "duration": 1500.0, "geometry": {"type": "LineString", "coordinates": [[76.5, 30.7], [76.7, 30.6]]}},
    {"distance": 18000.0, "duration": 1700.0, "geometry": {"type": "LineString", "coordinates": [[76.5, 30.7], [76.8, 30.6]]}}]}


class FakeResponse:
    def __init__(self, data):
        self._data = json.dumps(data).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class BaseCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = app_module.create_app({"TESTING": True, "DATABASE": self.path})
        # the 1 request/second Nominatim throttle is not needed in tests
        self.app.extensions["geo"]._throttle = lambda: None
        self.c = self.app.test_client()

    def tearDown(self):
        os.unlink(self.path)

    A = {"name": "Chandigarh University", "lat": 30.769, "lon": 76.575}
    B = {"name": "Chandigarh Airport", "lat": 30.673, "lon": 76.788}

    def route(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(FAKE_OSRM)):
            return self.c.post("/api/route", json={"origin": self.A, "destination": self.B})


class StartupTests(BaseCase):
    def test_home_page_and_graph(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        g = self.c.get("/api/graph").json
        self.assertEqual(g["stats"]["vertices"], 9)
        self.assertEqual(g["stats"]["closed_edges"], 0)

    def test_unknown_api_path_is_json(self):
        r = self.c.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.json)


class AlgorithmApiTests(BaseCase):
    def test_all_algorithms(self):
        r = self.c.post("/api/algorithm", json={"algorithm": "dijkstra", "start": "University", "end": "Airport"}).json
        self.assertEqual((r["path"], r["distance"]), (["University", "Mohali", "Airport"], 7))
        self.assertIn("runtime_ms", r)
        self.assertEqual(self.c.post("/api/algorithm", json={"algorithm": "bfs", "start": "University"}).json["levels"][0], ["University"])
        self.assertEqual(len(self.c.post("/api/algorithm", json={"algorithm": "dfs", "start": "University"}).json["order"]), 9)

    def test_validation(self):
        for body in ({"algorithm": "dijkstra", "start": "X", "end": "Airport"},
                     {"algorithm": "dijkstra", "start": "University", "end": "X"},
                     {"algorithm": "nope", "start": "University"}):
            self.assertEqual(self.c.post("/api/algorithm", json=body).status_code, 400)
        self.assertEqual(self.c.post("/api/algorithm", data="not json", content_type="text/plain").status_code, 200)  # defaults apply

    def test_close_reroute_reopen(self):
        body = {"from": "Mohali", "to": "Airport", "algorithm": "dijkstra", "start": "University", "end": "Airport"}
        r = self.c.post("/api/road", json={**body, "closed": True}).json
        self.assertEqual(r["status"], "closed")
        self.assertEqual(r["result"]["distance"], 12)
        self.assertEqual(r["before"]["distance"], 7)
        self.assertEqual(r["graph"]["stats"]["closed_edges"], 1)
        self.assertIn("recalculated", r["assistant"]["messages"][0])
        r = self.c.post("/api/road", json={**body, "closed": False}).json
        self.assertEqual(r["status"], "reopened")
        self.assertEqual(r["result"]["distance"], 7)

    def test_toggle_without_flag_and_reset(self):
        body = {"from": "Mohali", "to": "Airport"}
        self.assertEqual(self.c.post("/api/road", json=body).json["status"], "closed")
        self.assertEqual(self.c.post("/api/road", json=body).json["status"], "reopened")
        self.c.post("/api/road", json=body)
        self.assertEqual(self.c.post("/api/roads/reset").json["graph"]["stats"]["closed_edges"], 0)

    def test_unreachable_after_closure_is_explained(self):
        body = {"from": "Hospital", "to": "Sector 17", "closed": True, "algorithm": "dijkstra",
                "start": "University", "end": "Hospital"}
        r = self.c.post("/api/road", json=body).json
        self.assertFalse(r["result"]["reachable"])
        self.assertEqual(r["graph"]["stats"]["components"], 2)
        text = " ".join(r["assistant"]["messages"])
        self.assertIn("cut off: Hospital", text)
        self.assertIn("reopening Hospital - Sector 17", text)
        direct = self.c.post("/api/algorithm", json={"algorithm": "dijkstra", "start": "University", "end": "Hospital"}).json
        self.assertFalse(direct["reachable"])
        self.assertTrue(direct["assistant"]["suggestions"])

    def test_assistant_status_and_alternatives(self):
        r = self.c.get("/api/assistant/status?start=University&end=Airport").json
        self.assertIn("University -> Mohali -> Airport", r["messages"][0])
        self.assertEqual(r["alternatives"][0]["path"], ["University", "Kharar", "Airport"])
        self.assertEqual(r["alternatives"][0]["extra"], 5)
        self.c.post("/api/road", json={"from": "Hospital", "to": "Sector 17", "closed": True})
        r = self.c.get("/api/assistant/status?start=University&end=Hospital").json
        self.assertEqual(r["title"], "Graph status")
        self.assertIn("No route exists", r["messages"][0])
        self.assertEqual(self.c.get("/api/assistant/status?start=X&end=Airport").status_code, 400)

    def test_invalid_road(self):
        self.assertEqual(self.c.post("/api/road", json={"from": "University", "to": "Airport"}).status_code, 400)
        self.assertEqual(self.c.post("/api/road", json={}).status_code, 400)


class MapApiTests(BaseCase):
    def test_geocode_ok_and_validation(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(FAKE_NOMINATIM)):
            r = self.c.get("/api/geocode?q=Chandigarh University").json
        self.assertEqual(r["results"][0]["label"], "Chandigarh University, Gharuan")
        self.assertEqual(self.c.get("/api/geocode?q=a").status_code, 400)
        self.assertEqual(self.c.get("/api/geocode").status_code, 400)

    def test_geocode_cache_avoids_second_request(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(FAKE_NOMINATIM)) as m:
            self.c.get("/api/geocode?q=Chandigarh University")
            self.c.get("/api/geocode?q=chandigarh   university")
        self.assertEqual(m.call_count, 1)

    def test_geocode_no_results(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse([])):
            self.assertEqual(self.c.get("/api/geocode?q=zzzzzz").json["results"], [])

    def test_network_failures_are_friendly(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            r = self.c.get("/api/geocode?q=Chandigarh")
            self.assertEqual(r.status_code, 503)
            self.assertIn("internet", r.json["error"])
            r = self.c.post("/api/route", json={"origin": self.A, "destination": self.B})
            self.assertEqual(r.status_code, 503)
        err = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            self.assertEqual(self.c.get("/api/geocode?q=Another place").status_code, 429)

    def test_route_success_saves_history(self):
        r = self.route()
        self.assertEqual(r.status_code, 200)
        d = r.json
        self.assertEqual(len(d["routes"]), 2)
        self.assertTrue(d["routes"][0]["is_fastest"] and d["routes"][1]["is_shortest"])
        self.assertEqual(d["assistant"]["recommended"], 0)
        h = self.c.get("/api/history").json
        self.assertEqual(len(h["items"]), 1)
        self.assertEqual(h["items"][0]["distance_m"], 20000.0)
        self.assertEqual(h["items"][0]["alternatives"], 2)
        self.assertTrue(h["items"][0]["created_at"].endswith("+00:00"))

    def test_no_route(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse({"code": "NoRoute", "routes": []})):
            r = self.c.post("/api/route", json={"origin": self.A, "destination": self.B})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.c.get("/api/history").json["items"], [])  # failures are not saved

    def test_route_validation(self):
        bad = [{}, {"origin": self.A}, {"origin": self.A, "destination": {"name": "x", "lat": "abc", "lon": 1}},
               {"origin": self.A, "destination": {"name": "x", "lat": 95, "lon": 1}},
               {"origin": self.A, "destination": {"name": " ", "lat": 1, "lon": 1}},
               {"origin": self.A, "destination": self.A}]
        for body in bad:
            self.assertEqual(self.c.post("/api/route", json=body).status_code, 400, body)


class HistoryFavouritesTests(BaseCase):
    def test_history_delete_clear_and_recent(self):
        self.route(); self.route()
        h = self.c.get("/api/history").json
        self.assertEqual(len(h["items"]), 2)
        self.assertEqual(len(h["recent_locations"]), 2)  # deduplicated places
        self.assertEqual(self.c.delete(f"/api/history/{h['items'][0]['id']}").status_code, 200)
        self.assertEqual(self.c.delete(f"/api/history/{h['items'][0]['id']}").status_code, 404)
        self.assertEqual(self.c.delete("/api/history").json["deleted"], 1)
        self.assertEqual(self.c.get("/api/history").json["items"], [])

    def test_history_persists_across_app_restart(self):
        self.route()
        again = app_module.create_app({"TESTING": True, "DATABASE": self.path}).test_client()
        self.assertEqual(len(again.get("/api/history").json["items"]), 1)

    def test_favourites_add_duplicate_remove(self):
        self.assertEqual(self.c.get("/api/favourites").json["items"], [])
        r = self.c.post("/api/favourites", json=self.A)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/favourites", json={**self.A, "name": "chandigarh UNIVERSITY"}).status_code, 409)
        self.assertEqual(self.c.post("/api/favourites", json={"name": "", "lat": 1, "lon": 1}).status_code, 400)
        items = self.c.get("/api/favourites").json["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(self.c.delete(f"/api/favourites/{items[0]['id']}").status_code, 200)
        self.assertEqual(self.c.delete(f"/api/favourites/{items[0]['id']}").status_code, 404)
        self.assertEqual(self.c.get("/api/favourites").json["items"], [])

    def test_sql_injection_text_is_stored_literally(self):
        evil = "x'); DROP TABLE favourites;--"
        self.assertEqual(self.c.post("/api/favourites", json={"name": evil, "lat": 1, "lon": 2}).status_code, 201)
        self.assertEqual(self.c.get("/api/favourites").json["items"][0]["name"], evil)


class AnalyticsTests(BaseCase):
    def test_empty_state(self):
        a = self.c.get("/api/analytics").json
        self.assertEqual(a["total_routes"], 0)
        self.assertIsNone(a["avg_distance_km"])
        self.assertEqual(a["top_locations"], [])
        self.assertEqual(a["algorithm_stats"], [])
        self.assertEqual(a["favourites_count"], 0)

    def test_populated(self):
        self.route(); self.route()
        self.c.post("/api/favourites", json=self.A)
        self.c.post("/api/algorithm", json={"algorithm": "dijkstra", "start": "University", "end": "Airport"})
        self.c.post("/api/algorithm", json={"algorithm": "dijkstra", "start": "University", "end": "Airport"})
        self.c.post("/api/algorithm", json={"algorithm": "bfs", "start": "University"})
        a = self.c.get("/api/analytics").json
        self.assertEqual(a["total_routes"], 2)
        self.assertEqual(a["avg_distance_km"], 20.0)
        self.assertEqual(a["avg_duration_min"], 25.0)
        self.assertEqual(a["top_locations"][0]["count"], 2)
        self.assertEqual(a["favourites_count"], 1)
        stats = {s["algorithm"]: s for s in a["algorithm_stats"]}
        self.assertEqual(stats["dijkstra"]["runs"], 2)
        self.assertEqual(stats["dijkstra"]["avg_cost"], 7.0)
        self.assertEqual(stats["bfs"]["runs"], 1)
        self.assertEqual(a["algorithm_runs_total"], 3)
        self.assertEqual(len(a["distance_series"]), 2)


if __name__ == "__main__":
    unittest.main()
