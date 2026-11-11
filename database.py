"""SQLite persistence: route history, favourites and algorithm run log.

All queries are parameterised (``?`` placeholders); user input is never
concatenated into SQL.
"""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS route_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_name TEXT NOT NULL,
    origin_lat REAL NOT NULL,
    origin_lon REAL NOT NULL,
    dest_name TEXT NOT NULL,
    dest_lat REAL NOT NULL,
    dest_lon REAL NOT NULL,
    distance_m REAL,
    duration_s REAL,
    alternatives INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favourites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fav_name ON favourites (name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS algorithm_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    algorithm TEXT NOT NULL,
    start_node TEXT NOT NULL,
    end_node TEXT,
    cost REAL,
    visited_count INTEGER NOT NULL,
    reachable INTEGER NOT NULL,
    runtime_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


class DuplicateFavourite(Exception):
    pass


# ---- history -----------------------------------------------------------
def add_history(conn, origin, dest, distance_m, duration_s, alternatives):
    cur = conn.execute(
        "INSERT INTO route_history (origin_name, origin_lat, origin_lon, dest_name, dest_lat,"
        " dest_lon, distance_m, duration_s, alternatives, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (origin["name"], origin["lat"], origin["lon"], dest["name"], dest["lat"], dest["lon"],
         distance_m, duration_s, alternatives, now_iso()))
    conn.commit()
    return cur.lastrowid


def list_history(conn, limit=100):
    rows = conn.execute("SELECT * FROM route_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_history(conn, hid):
    cur = conn.execute("DELETE FROM route_history WHERE id = ?", (hid,))
    conn.commit()
    return cur.rowcount > 0


def clear_history(conn):
    cur = conn.execute("DELETE FROM route_history")
    conn.commit()
    return cur.rowcount


def recent_locations(conn, limit=8):
    """Distinct recently used places (start or destination), newest first."""
    rows = conn.execute(
        "SELECT name, lat, lon, MAX(id) AS last_id FROM ("
        " SELECT id, origin_name AS name, origin_lat AS lat, origin_lon AS lon FROM route_history"
        " UNION ALL"
        " SELECT id, dest_name, dest_lat, dest_lon FROM route_history)"
        " GROUP BY LOWER(name) ORDER BY last_id DESC LIMIT ?", (limit,)).fetchall()
    return [{"name": r["name"], "lat": r["lat"], "lon": r["lon"]} for r in rows]


# ---- favourites --------------------------------------------------------
def add_favourite(conn, name, lat, lon):
    try:
        cur = conn.execute("INSERT INTO favourites (name, lat, lon, created_at) VALUES (?,?,?,?)",
                           (name, lat, lon, now_iso()))
        conn.commit()
    except sqlite3.IntegrityError:
        raise DuplicateFavourite(name)
    return cur.lastrowid


def list_favourites(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM favourites ORDER BY id DESC").fetchall()]


def delete_favourite(conn, fid):
    cur = conn.execute("DELETE FROM favourites WHERE id = ?", (fid,))
    conn.commit()
    return cur.rowcount > 0


# ---- algorithm runs ----------------------------------------------------
def add_algorithm_run(conn, algorithm, start, end, cost, visited, reachable, runtime_ms):
    conn.execute(
        "INSERT INTO algorithm_runs (algorithm, start_node, end_node, cost, visited_count,"
        " reachable, runtime_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (algorithm, start, end, cost, visited, 1 if reachable else 0, runtime_ms, now_iso()))
    conn.commit()


# ---- analytics ---------------------------------------------------------
def analytics(conn):
    one = lambda sql, args=(): conn.execute(sql, args).fetchone()
    total = one("SELECT COUNT(*) c FROM route_history")["c"]
    agg = one("SELECT COUNT(distance_m) nd, AVG(distance_m) ad, COUNT(duration_s) nt,"
              " AVG(duration_s) at FROM route_history WHERE distance_m > 0")
    top = conn.execute(
        "SELECT MIN(name) AS name, COUNT(*) AS count FROM ("
        " SELECT origin_name AS name FROM route_history UNION ALL SELECT dest_name FROM route_history)"
        " GROUP BY LOWER(name) ORDER BY count DESC, name LIMIT 8").fetchall()
    recent = list_history(conn, 5)
    series = conn.execute(
        "SELECT id, origin_name, dest_name, distance_m FROM route_history"
        " WHERE distance_m > 0 ORDER BY id DESC LIMIT 10").fetchall()
    algos = conn.execute(
        "SELECT algorithm, COUNT(*) AS runs, AVG(runtime_ms) AS avg_runtime_ms,"
        " AVG(visited_count) AS avg_visited, AVG(cost) AS avg_cost,"
        " SUM(CASE WHEN reachable = 0 THEN 1 ELSE 0 END) AS unreachable"
        " FROM algorithm_runs GROUP BY algorithm ORDER BY runs DESC").fetchall()
    return {
        "total_routes": total,
        "avg_distance_km": round(agg["ad"] / 1000, 2) if agg["nd"] else None,
        "avg_duration_min": round(agg["at"] / 60, 1) if agg["nt"] and agg["nd"] else None,
        "routes_with_distance": agg["nd"],
        "top_locations": [dict(r) for r in top],
        "recent_routes": recent,
        "distance_series": [dict(r) for r in reversed(series)],
        "favourites": list_favourites(conn)[:5],
        "favourites_count": one("SELECT COUNT(*) c FROM favourites")["c"],
        "algorithm_runs_total": one("SELECT COUNT(*) c FROM algorithm_runs")["c"],
        "algorithm_stats": [
            {"algorithm": r["algorithm"], "runs": r["runs"],
             "avg_runtime_ms": round(r["avg_runtime_ms"], 3),
             "avg_visited": round(r["avg_visited"], 1),
             "avg_cost": round(r["avg_cost"], 2) if r["avg_cost"] is not None else None,
             "unreachable": r["unreachable"]} for r in algos],
    }
