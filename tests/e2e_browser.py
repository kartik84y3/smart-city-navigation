"""Optional end-to-end browser test (needs: pip install playwright && playwright install chromium).

What it does
  * starts the real Flask app on a temporary database,
  * replaces ONLY the two internet services (Nominatim/OSRM) with deterministic fakes,
  * replaces the Leaflet CDN script with tests/e2e_support/leaflet_stub.js,
  * drives the real pages in headless Chromium and checks buttons, forms, lists and errors.

What it cannot check: real map tiles, real place search results, real OSRM routes.
Run:  python tests/e2e_browser.py
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import app as app_module  # noqa: E402
from geo import GeoServiceError  # noqa: E402

SHOTS = Path(os.environ.get("E2E_SHOTS", tempfile.gettempdir())) / "scn_shots"
SHOTS.mkdir(exist_ok=True)


def fake_geocode(q, limit=5):
    if "offline" in q.lower():
        raise GeoServiceError("Could not reach the place search service. Check your internet connection and try again.", 503)
    if "nowhere" in q.lower():
        return []
    lat = 30.5 + (sum(map(ord, q)) % 100) / 100
    lon = 76.5 + (sum(map(ord, q[::-1])) % 100) / 100
    return [{"label": q.title(), "display_name": q.title() + ", Punjab, India", "lat": lat, "lon": lon},
            {"label": q.title() + " Road", "display_name": q.title() + " Road, India", "lat": lat + .02, "lon": lon + .02}]


def fake_route(o, d):
    line = {"type": "LineString", "coordinates": [[o["lon"], o["lat"]], [d["lon"], d["lat"]]]}
    return [{"index": 0, "distance": 21400.0, "duration": 1560.0, "geometry": line},
            {"index": 1, "distance": 19800.0, "duration": 1800.0, "geometry": line}]


def main():
    fd, dbpath = tempfile.mkstemp(suffix=".db"); os.close(fd)
    app = app_module.create_app({"TESTING": True, "DATABASE": dbpath})
    geo = app.extensions["geo"]
    geo.geocode, geo.route = fake_geocode, fake_route
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    stub = (ROOT / "tests" / "e2e_support" / "leaflet_stub.js").read_text()
    errors, checks = [], []

    def shot(page, name):
        page.wait_for_timeout(450)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(SHOTS / name))

    def check(name, cond=True):
        checks.append((name, bool(cond)))
        print(("PASS " if cond else "FAIL ") + name)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
        # offline sandbox: stub Leaflet, drop fonts/tiles
        ctx.route("**/leaflet.js", lambda r: r.fulfill(body=stub, content_type="application/javascript"))
        ctx.route("**/leaflet.css", lambda r: r.fulfill(body="", content_type="text/css"))
        ctx.route("**/*fonts.googleapis.com/**", lambda r: r.abort())
        ctx.route("**/*.tile.openstreetmap.org/**", lambda r: r.abort())

        # ---- startup, theme ----
        page.goto(base)
        expect(page.locator("#pageTitle")).to_have_text("Map Navigation")
        check("startup: dashboard loads", page.locator(".nav-item").count() == 4)
        check("startup: dark theme by default", page.evaluate("document.documentElement.dataset.theme") == "dark")
        shot(page, "map_dark_empty.png")
        page.click("#themeBtn")
        check("theme: toggles to light", page.evaluate("document.documentElement.dataset.theme") == "light")
        page.reload()
        check("theme: choice is remembered after reload", page.evaluate("document.documentElement.dataset.theme") == "light")
        page.click("#themeBtn")

        # ---- empty analytics / history first ----
        page.click('[data-view="analytics"]')
        expect(page.locator("#chartDistances .empty")).to_be_visible()
        check("analytics: empty state (distances)", True)
        check("analytics: empty state (locations, algorithms, recent)",
              page.locator("#chartLocations .empty").is_visible() and page.locator("#chartAlgos .empty").is_visible()
              and page.locator("#recentRoutes .empty").is_visible())
        check("analytics: averages show a dash with no data", "—" in page.locator("#statGrid").inner_text())
        page.click('[data-view="history"]')
        check("history: empty states", page.locator("#historyList .empty").is_visible() and page.locator("#favList .empty").is_visible())
        check("history: Clear all disabled when empty", page.locator("#clearHistoryBtn").is_disabled())

        # ---- map: validation ----
        page.click('[data-view="map"]')
        page.click("#routeBtn")
        expect(page.locator("#routeError")).to_contain_text("starting point")
        check("map: empty form shows validation message", True)
        page.fill("#originInput", "Chandigarh University")
        page.click("#routeBtn")
        expect(page.locator("#routeError")).to_contain_text("destination")
        check("map: missing destination message", True)

        # ---- map: search suggestions & markers ----
        page.fill("#originInput", "")
        page.type("#originInput", "Chandigarh University", delay=5)
        expect(page.locator("#originList li[data-i]").first).to_be_visible(timeout=5000)
        check("map: suggestions appear", page.locator("#originList li[data-i]").count() == 2)
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
        check("map: keyboard selects suggestion", page.input_value("#originInput") == "Chandigarh University")
        check("map: start marker added", page.evaluate("[...window.__L.map.layers].some(l=>l.type==='marker')"))
        page.click("#originFav")
        expect(page.locator("#originFav")).to_have_attribute("aria-pressed", "true")
        check("favourites: star saves a favourite", True)

        # not-found + offline messages
        page.fill("#destInput", "nowhere land")
        page.click("#routeBtn")
        expect(page.locator("#routeError")).to_contain_text("Could not find")
        check("map: unknown place gives a helpful message", True)
        page.fill("#destInput", "offline place")
        page.click("#routeBtn")
        expect(page.locator("#routeError")).to_contain_text("internet connection")
        check("map: network failure message", True)
        check("map: button is usable again after failures", page.locator("#routeBtn").is_enabled())

        # ---- map: route with alternatives ----
        page.fill("#destInput", "Chandigarh Airport")
        page.click("#routeBtn")
        expect(page.locator(".route-card")).to_have_count(2, timeout=5000)
        info = page.locator("#routeInfo").inner_text()
        check("route: distance and estimated duration shown", "21.4 km" in info and "26 min" in info)
        check("route: alternatives and comparison table", "19.8 km" in info and "vs fastest" in info)
        check("route: fastest & shortest badges", "Fastest" in info and "Shortest" in info)
        check("route: lines drawn on map", page.evaluate("[...window.__L.map.layers].filter(l=>l.type==='route').length") == 2)
        shot(page, "map_route_dark.png")
        page.locator(".route-card").nth(1).click()
        check("route: selecting alternative updates summary", "19.8 km" in page.locator("#routeInfo .stats").inner_text())
        check("assistant: comparison message", "shortest" in page.locator("#mapAssistant").inner_text().lower())
        page.click("#mapAssistant .chip:has-text('About estimates')")
        check("assistant: limitations message", "live traffic" in page.locator("#mapAssistant").inner_text().lower())
        page.click("#clearRouteBtn")
        check("route: clear removes route", page.locator(".route-card").count() == 0
              and page.evaluate("[...window.__L.map.layers].filter(l=>l.type==='route').length") == 0)
        page.click("#swapBtn")
        check("map: swap exchanges start and destination", page.input_value("#originInput") == "Chandigarh Airport")
        page.click("#resetMapBtn")
        check("map: reset clears inputs and markers", page.input_value("#originInput") == "" and page.input_value("#destInput") == ""
              and not page.evaluate("[...window.__L.map.layers].some(l=>l.type==='marker')"))

        # ---- lab ----
        page.click('[data-view="lab"]')
        expect(page.locator("#roadList .road")).to_have_count(14)
        check("lab: graph and road list rendered", page.locator("#graph .node").count() == 9 and page.locator("#graph .edge").count() == 14)
        page.select_option("#startSel", "University"); page.select_option("#endSel", "Airport")
        page.select_option("#pSpeed", "300")
        page.click("#runBtn")
        expect(page.locator("#labResult .stat.ok b").first).to_have_text("7 km", timeout=5000)
        page.wait_for_function("document.querySelectorAll('#graph .node.path').length===3", timeout=8000)
        check("dijkstra: selected path shown (University > Mohali > Airport)", page.locator("#pathChips .n").all_inner_texts() == ["University", "Mohali", "Airport"])
        check("dijkstra: path nodes highlighted after playback", page.locator("#graph .edge.path").count() == 2)
        check("dijkstra: complexity displayed", "O((V + E) log V)" in page.locator("#labResult").inner_text())
        shot(page, "lab_dijkstra_dark.png")
        page.click("#pReset")
        check("player: reset returns to step 0", page.locator("#graph .node.visited").count() == 0)
        page.click("#pStep")
        check("player: step reveals first node", page.locator("#graph .node.current").count() == 1)
        page.click("#pEnd")
        check("player: finish shows all steps", page.locator("#graph .edge.path").count() == 2)

        # closure + reroute
        page.locator('#roadList button[data-from="Mohali"][data-to="Airport"]').click()
        expect(page.locator("#labResult .stat.ok b").first).to_have_text("12 km", timeout=5000)
        check("closure: route recalculated (12 km)", True)
        check("closure: before/after comparison shown", "Before" in page.locator("#labResult .compare").inner_text())
        check("closure: assistant explains reason", "recalculated" in page.locator("#labAssistant").inner_text())
        check("closure: closed edge drawn", page.locator("#graph .edge.closed").count() == 1)
        shot(page, "lab_closure_dark.png")
        # click edge on svg to reopen
        page.locator('#graph .edge[data-from="Mohali"][data-to="Airport"] .hit').click(force=True)
        expect(page.locator("#labResult .stat.ok b").first).to_have_text("7 km", timeout=5000)
        check("closure: reopening via graph click restores 7 km", page.locator("#graph .edge.closed").count() == 0)

        # disconnected
        page.select_option("#endSel", "Hospital")
        page.locator('#roadList button[data-from="Hospital"][data-to="Sector 17"]').click()
        expect(page.locator("#labResult .stat.bad b").first).to_have_text("No route", timeout=5000)
        check("disconnected: 'No route' shown", True)
        check("disconnected: assistant explains and suggests", "reopening Hospital - Sector 17" in page.locator("#labAssistant").inner_text())
        page.click("#labAssistant .chip:has-text('Explain graph')")
        expect(page.locator("#labAssistant .msg h3").first).to_have_text("Graph status", timeout=5000)
        check("assistant chip works", "No route exists" in page.locator("#labAssistant .msg").first.inner_text())
        page.click('#algoSeg button[data-algo="bfs"]')
        check("bfs: destination field hidden", page.locator("#endWrap").is_hidden())
        page.select_option("#startSel", "University")
        page.click("#runBtn")
        page.wait_for_function("document.querySelectorAll('#orderChips .n').length>0", timeout=5000)
        check("bfs: unreachable node reported", "Hospital" in page.locator("#labResult .explain").last.inner_text() or "Hospital" in page.locator("#labResult").inner_text())
        page.click("#pEnd")
        check("bfs: 8 nodes reached while disconnected", page.locator("#graph .node.visited, #graph .node.current").count() >= 8)
        page.click("#reopenAll")
        expect(page.locator("#roadList .road.closed")).to_have_count(0, timeout=5000)
        check("lab: reopen all restores roads", page.locator("#reopenAll").is_disabled())
        page.click('#algoSeg button[data-algo="dfs"]')
        page.click("#runBtn")
        page.wait_for_function("document.querySelector('#labResult h2')?.textContent.includes('DFS')", timeout=5000)
        page.click("#pEnd")
        order = page.locator("#orderChips .n").all_inner_texts()
        check("dfs: traversal order of 9 nodes", len(order) == 9 and order[0] == "University")
        check("dfs: backtracking logged", "backtrack" in page.locator("#stepLog").inner_text().lower())
        shot(page, "lab_dfs_dark.png")

        # ---- history, favourites ----
        page.click('[data-view="history"]')
        expect(page.locator("#historyList .item")).to_have_count(1)
        txt = page.locator("#historyList").inner_text()
        check("history: route saved with distance and time", "→" in txt and "21.4 km" in txt and "26 min" in txt)
        page.locator('#historyList button[data-act="reuse"]').click()
        expect(page.locator(".route-card")).to_have_count(2, timeout=5000)
        check("history: reuse recalculates the route on the map", page.input_value("#destInput") == "Chandigarh Airport")
        page.click('[data-view="history"]')
        expect(page.locator("#historyList .item")).to_have_count(2)
        check("history: reuse adds a new entry", True)
        check("history: recent places listed", page.locator("#recentList .item").count() == 2)
        page.locator('#favList button[data-act="use-b"]').click()
        check("favourites: use as destination", page.input_value("#destInput") == "Chandigarh University")
        page.click('[data-view="history"]')
        page.locator('#historyList button[data-act="del-history"]').first.click()
        expect(page.locator("#historyList .item")).to_have_count(1)
        check("history: delete one entry", True)
        page.locator('#favList button[data-act="del-fav"]').click()
        expect(page.locator("#favList .empty")).to_be_visible()
        check("favourites: remove", True)
        page.click("#clearHistoryBtn")
        page.click("#confirmOk")
        expect(page.locator("#historyList .empty")).to_be_visible()
        check("history: clear all (with confirmation)", True)

        # ---- analytics populated ----
        page.click('[data-view="map"]')
        page.fill("#originInput", "Phase 8 Mohali"); page.fill("#destInput", "Sector 17 Chandigarh")
        page.click("#routeBtn")
        expect(page.locator(".route-card")).to_have_count(2, timeout=5000)
        page.click('[data-view="analytics"]')
        expect(page.locator("#statGrid")).to_contain_text("21.4 km", timeout=5000)
        check("analytics: average distance from real data", "21.4 km" in page.locator("#statGrid").inner_text())
        check("analytics: charts populated", page.locator("#chartDistances .bar").count() == 1
              and page.locator("#chartLocations .hbar").count() >= 2 and page.locator("#chartAlgos .hbar").count() >= 2)
        page.screenshot(path=str(SHOTS / "analytics_dark.png"), full_page=True)

        # ---- responsive ----
        for name, w, h in (("tablet", 820, 1180), ("mobile", 390, 844)):
            page.set_viewport_size({"width": w, "height": h})
            page.click('[data-view="map"]') if w > 900 else (page.click("#menuBtn"), page.click('.nav-item[data-view="map"]'))
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            check(f"responsive {name}: no horizontal overflow (map)", not overflow)
            shot(page, f"map_{name}.png")
            page.click("#menuBtn"); page.click('.nav-item[data-view="lab"]')
            check(f"responsive {name}: no horizontal overflow (lab)", not page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"))
            shot(page, f"lab_{name}.png")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.click("#themeBtn")
        page.click('[data-view="lab"]')
        shot(page, "lab_light.png")
        page.click('[data-view="map"]')
        shot(page, "map_light.png")

        check("no JavaScript errors in the console", not errors)
        browser.close()
    server.shutdown()
    os.unlink(dbpath)
    for e in errors:
        print("JS ERROR:", e)
    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} browser checks passed. Screenshots: {SHOTS}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
