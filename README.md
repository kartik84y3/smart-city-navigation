# Smart City Navigation System (ADS Project)

A Flask web app with two clearly separate parts:

1. **Map Navigation (real world):** search places, calculate real driving routes with alternatives, compare distance and *estimated* time, save history and favourites. Uses OpenStreetMap, Leaflet, Nominatim (place search) and the public OSRM demo server (routing).
2. **Algorithm Lab (educational ADS simulation):** our own Python implementation of **Dijkstra, BFS and DFS** running on a 9-location sample graph with made-up distances, with step-by-step playback, road closures and re-routing.

> The two parts use different data and different routing engines. The Lab does **not** use the real map, and the real map does **not** use our Dijkstra code (OSRM has its own engine). The interface says this too.

Also included: dark/light theme, rule-based travel assistant, SQLite history and favourites (kept after restart), analytics dashboard.

---

## 1. Windows installation (VS Code / PowerShell)

Requires Python 3.10+ from python.org (tick "Add Python to PATH").

```powershell
cd path\to\SmartCityNavigation_Hybrid_Project
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** in your browser. Keep the terminal open while using the site. Stop with `Ctrl+C`.

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use Command Prompt (`cmd`) instead.

Optional settings (environment variables, all have defaults):

| Variable | Purpose | Default |
|---|---|---|
| `PORT` | web port | 5000 |
| `FLASK_DEBUG` | `1` enables auto-reload/debugger | 0 |
| `DATABASE_PATH` | SQLite file | `instance/smartcity.db` |
| `GEO_USER_AGENT` | identifies the app to Nominatim (their policy asks for this; put your own name/email) | `SmartCityNavigation-CollegeProject/2.0` |
| `OSRM_BASE_URL` / `NOMINATIM_URL` | alternative servers | public demo servers |

PowerShell example: `$env:PORT=5050; python app.py`

**Internet is needed** for map tiles, Leaflet (loaded from unpkg), place search and routing. The Algorithm Lab, history and analytics pages work without internet, but the Leaflet map will not draw.

## 2. Run the tests

```powershell
python -m unittest discover -s tests -t . -v
```

Optional browser test (extra install, not needed to run the app):

```powershell
pip install playwright
playwright install chromium
python tests\e2e_browser.py
```

## 3. Implemented features

**Map Navigation**
- Searchable start/destination with live suggestions (debounced, keyboard accessible), favourites and recent places shown when the box is empty
- A/B markers, route line, **alternative routes** (when OSRM returns them), click a card or line to select
- Distance + estimated duration, Fastest/Shortest badges, comparison table
- Clear route, Reset, Swap; validation, "place not found", "no route", network/rate-limit messages, loading spinners

**Algorithm Lab**
- Dijkstra (binary heap) with settled order, relaxations, path, cost, unreachable handling
- BFS (levels, queue) and DFS (iterative stack, backtracking) with traversal order and unreachable list
- SVG graph with node labels and edge weights, path highlight, play/step/back/finish, step log
- Road closures: click a road or use the list; the algorithm re-runs; before/after comparison; reason explained; disconnected graph handled ("Hospital" is a dead end, close its only road to see it)
- Complexity, space, V/E counts, runtime, beginner-friendly explanation

**Assistant (rule-based)** - recommends fastest/shortest route, compares options, explains reroutes, explains why a route is unavailable and which closed road would fix it, suggests alternatives. It is plain Python rules; **no external AI is used**.

**History, favourites, analytics** - SQLite, timestamps (UTC, shown in local time), reuse, delete, clear; analytics computed from stored data with empty states.

## 4. Project structure

```
app.py                 Flask app factory + all API routes
graph_algorithms.py    CityGraph, dijkstra(), bfs(), dfs()  (pure Python, no Flask)
assistant.py           rule-based explanations
database.py            SQLite schema + parameterised queries
geo.py                 Nominatim/OSRM client (User-Agent, 1 req/s throttle, cache, friendly errors)
data/city_graph.json   sample graph (nodes, positions, distances)
templates/index.html   single-page dashboard
static/css/style.css   theme + layout
static/js/             main, map, lab, history, analytics, ui, state, api, util (ES modules)
tests/                 unit, API and optional browser tests
```

Why server-side geocoding/routing? The server can send a proper User-Agent, respect Nominatim's 1 request/second limit, cache results and turn failures into clear messages.

Main API: `GET /api/graph`, `POST /api/algorithm`, `POST /api/road`, `POST /api/roads/reset`, `GET /api/assistant/status`, `GET /api/geocode?q=`, `POST /api/route`, `GET|DELETE /api/history`, `GET|POST /api/favourites`, `DELETE /api/favourites/<id>`, `GET /api/analytics`.

What changed from your original project: the Flask + Dijkstra/BFS/DFS + Leaflet/OSRM idea and the original 6-location sample graph (all original roads and distances are unchanged; Hospital, Bus Stand and Stadium were added) are kept. Everything else was rebuilt: modular backend, SQLite, new UI, tests. The old `script.js`/`style.css`/`README.txt` were replaced.

## 5. Test results (actually run during development)

| Suite | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | **41 tests passed** |
| `python tests/e2e_browser.py` (headless Chromium) | **64 of 64 checks passed** |

Unit tests cover: Dijkstra on textbook and project graphs; Dijkstra compared with an independent Bellman-Ford on 200 random graphs with random closed roads; BFS levels; DFS order equal to the recursive definition and a 3000-node chain; disconnected graphs; closures/reopening; API validation; history, favourites (duplicates, deletion, SQL-injection text stored literally); persistence across app restart; analytics empty and populated; network failure, rate-limit and no-route handling.

**Not verified (be honest in your viva/demo):**
- The development environment had **no internet**. Nominatim and OSRM were replaced by fakes in the tests, so **live place search and real routes were not tested**. Their request/response handling follows the public API formats but must be tried on your machine.
- The real **Leaflet library and map tiles were not loaded**; the browser test used a small stand-in (`tests/e2e_support/leaflet_stub.js`) that records calls. Please check that the map draws, markers and route lines appear, and pan/zoom works.
- The app was **not run on Windows**; commands above are standard but untested here.
- Google Fonts (Inter) could not load in the sandbox; the page falls back to system fonts.
- The light theme and tablet/mobile layouts were checked only through screenshots and an overflow check, not on real devices.

## 6. Limitations

- OSRM durations are free-flow estimates, **no live traffic**, no roadworks/closures. Public demo servers are shared and may be slow or rate-limited. Do not use this for real navigation.
- Road closures in the Lab live in server memory and reset when the app restarts (history/favourites persist).
- The Lab graph is small and fixed (edit `data/city_graph.json` to change it; distances must be positive).
- One shared closure state per server: if two people use the same running server they see each other's closures. SQLite history is also shared (no user accounts).
- Alternative routes depend on OSRM; sometimes it returns only one route.

## 7. Demonstration guide (about 8 minutes)

1. **Map Navigation:** search "Chandigarh University" and "Chandigarh Airport", pick suggestions, press the star on one, **Find route**. Show alternatives, the comparison table and the assistant's message; click "About estimates" and say clearly there is no live traffic.
2. **Algorithm Lab:** read the banner (simulation vs real map). Run **Dijkstra** University to Airport: show cost 7 km, path, settled order, the step log, complexity. Use Step/Back.
3. **Closure:** close *Mohali - Airport*. Show the 12 km reroute, the before/after box and the assistant's reason. Reopen it by clicking the road on the graph.
4. **Disconnected:** choose destination Hospital, close *Hospital - Sector 17*: "No route", cut-off nodes and the suggested road to reopen. Run **BFS** and **DFS** and show unreachable nodes.
5. **History & Favourites:** reuse a route; delete an entry. Restart the server and show data is still there.
6. **Analytics:** show charts calculated from saved data. Toggle the light/dark theme.

## 8. Viva questions and answers

1. **How does Dijkstra work?** Keep tentative distances (start = 0, others infinity) in a min-priority queue. Repeatedly remove the closest unsettled node, mark it settled, and relax its edges (`d[u]+w < d[v]` then update). Stop when the destination is settled.
2. **Complexity?** O((V+E) log V) with a binary heap; O(V²) with an array; space O(V).
3. **Why must weights be non-negative?** Once a node is settled we assume no later path can be shorter; a negative edge could break that. Use Bellman-Ford for negative edges. Our graph validator rejects non-positive weights.
4. **Why a heap and what are "stale entries"?** `heapq` has no decrease-key, so we push a new entry and skip older ones when popped (`d > dist[u]`).
5. **BFS vs DFS?** BFS = queue, level by level, finds fewest *edges*; DFS = stack, goes deep then backtracks. Both O(V+E).
6. **Does BFS give the shortest path here?** Only for unweighted graphs. Our roads have weights, so we use Dijkstra.
7. **Why is DFS iterative?** An explicit stack avoids Python's recursion limit (tested on a 3000-node chain) and gives the same order as recursion.
8. **How is the graph stored?** Adjacency list (dict of dicts): O(V+E) space, fast neighbour iteration; an adjacency matrix would need O(V²).
9. **How is a road closure modelled?** A set of undirected edge keys `(a,b)` sorted; `neighbors()` skips closed keys, so every algorithm sees the changed graph.
10. **What if the graph becomes disconnected?** Dijkstra ends with the destination still at infinity, so we report "no route", compute connected components with BFS, name the cut-off nodes and test which closed road would reconnect.
11. **How do you know Dijkstra is correct?** Tests compare it with a separate Bellman-Ford implementation on 200 random graphs with random closures, and check path validity and cost.
12. **Is the map route computed by your Dijkstra?** No. OSRM (a routing engine using road-network speed-up techniques) calculates it. Our Lab is a separate educational graph.
13. **Why are travel times only estimates?** OSRM uses speed limits/road types without live traffic.
14. **How are SQL injection and XSS avoided?** Parameterised queries (`?`); user text is escaped before being placed in the page (`esc()`); tests store `'); DROP TABLE...` literally.
15. **Is the assistant AI?** No. It is rule-based Python over computed numbers, and the interface says so.
