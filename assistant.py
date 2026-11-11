"""Rule-based travel assistant.

This is plain Python logic (if/else rules over real computed numbers).
It does NOT call any external AI model or API.
"""
from graph_algorithms import dijkstra, edge_key


def _km(m):
    return f"{m / 1000:.1f} km"


def _min(s):
    m = round(s / 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} min"


# ---------------------------------------------------------------------------
# Real-map routes (distances in metres, durations in seconds from OSRM)
# ---------------------------------------------------------------------------
def summarize_routes(routes, origin_name="the start", dest_name="the destination"):
    """Compare map routes. ``routes`` = [{'distance': m, 'duration': s}, ...]."""
    if not routes:
        return {"title": "No route", "messages": ["No route is available to summarise."],
                "fastest": None, "shortest": None, "recommended": None}
    fastest = min(range(len(routes)), key=lambda i: (routes[i]["duration"], routes[i]["distance"]))
    shortest = min(range(len(routes)), key=lambda i: (routes[i]["distance"], routes[i]["duration"]))
    r = routes[fastest]
    msgs = [f"Recommended: Route {fastest + 1}, about {_km(r['distance'])} and an estimated "
            f"{_min(r['duration'])} from {origin_name} to {dest_name}."]
    if len(routes) == 1:
        msgs.append("The routing service returned only one route, so there is no alternative to compare.")
    elif fastest == shortest:
        others = [i for i in range(len(routes)) if i != fastest]
        o = routes[others[0]]
        msgs.append(f"Route {fastest + 1} is both the shortest and the fastest. The next option, "
                    f"Route {others[0] + 1}, is {_km(o['distance'] - r['distance'])} longer and "
                    f"about {_min(max(o['duration'] - r['duration'], 0))} slower.")
    else:
        s = routes[shortest]
        msgs.append(f"Route {shortest + 1} is the shortest ({_km(s['distance'])}), saving "
                    f"{_km(r['distance'] - s['distance'])} compared with Route {fastest + 1}, "
                    f"but it is estimated to take about {_min(s['duration'] - r['duration'])} longer.")
        msgs.append("Pick the fastest route to save time, or the shortest route to save fuel/distance.")
    msgs.append("Durations are free-flow estimates from the public OSRM service. They do not include "
                "live traffic, signals, roadworks or closures.")
    return {"title": "Route comparison", "messages": msgs, "fastest": fastest, "shortest": shortest,
            "recommended": fastest}


# ---------------------------------------------------------------------------
# Educational graph: closures and unreachable explanations
# ---------------------------------------------------------------------------
def explain_unreachable(graph, closed, start, end):
    """Why is there no path, and which closed road(s) would restore one?"""
    comp = graph.reachable_from(start, closed)
    cut_off = sorted(set(graph.nodes) - set(comp))
    msgs = [f"No route exists from {start} to {end} because the open roads no longer connect them."]
    if closed:
        names = ", ".join(f"{a} - {b}" for a, b in sorted(closed))
        msgs.append(f"Closed roads: {names}.")
    msgs.append(f"From {start} you can still reach {len(comp) - 1} other location(s); "
                f"cut off: {', '.join(cut_off) if cut_off else 'none'}.")
    suggestions = []
    for a, b in sorted(closed):
        trial = dijkstra(graph, start, end, closed - {edge_key(a, b)})
        if trial["reachable"]:
            suggestions.append({"from": a, "to": b, "distance": trial["distance"], "path": trial["path"]})
    if suggestions:
        s = min(suggestions, key=lambda x: x["distance"])
        msgs.append(f"Suggestion: reopening {s['from']} - {s['to']} would restore a route of "
                    f"{s['distance']} km ({' -> '.join(s['path'])}).")
    else:
        msgs.append("Suggestion: reopen any closed road that links the two parts of the network, "
                    "or choose a different destination.")
    return {"title": "Route unavailable", "messages": msgs, "suggestions": suggestions}


def explain_reroute(graph, closed_after, algorithm, before, after, edge, action):
    """Explain what a road closure/reopening did to the current result."""
    a, b = edge
    road = f"{a} - {b}"
    verb = "closed" if action == "closed" else "reopened"
    msgs = []
    if algorithm == "dijkstra":
        start, end = after["start"], after["end"]
        was_ok, now_ok = before["reachable"], after["reachable"]
        if now_ok and was_ok:
            on_old = edge_key(a, b) in {edge_key(x, y) for x, y in zip(before["path"], before["path"][1:])}
            if before["path"] == after["path"]:
                if action == "closed":
                    msgs.append(f"{road} was {verb}, but it was not part of the {start} to {end} route, "
                                f"so the route is unchanged ({after['distance']} km).")
                else:
                    msgs.append(f"{road} was {verb}, but it does not offer a shorter way, "
                                f"so the route stays the same ({after['distance']} km).")
            else:
                diff = after["distance"] - before["distance"]
                if action == "closed":
                    why = (f"the old route used {road}" if on_old else "the old route became invalid")
                    msgs.append(f"{road} was {verb} and {why}, so Dijkstra recalculated: new route "
                                f"{' -> '.join(after['path'])} costs {after['distance']} km "
                                f"({'+' if diff >= 0 else ''}{diff:g} km compared with {before['distance']} km).")
                else:
                    msgs.append(f"{road} was {verb}, which opened a better path: "
                                f"{' -> '.join(after['path'])} now costs {after['distance']} km "
                                f"({diff:g} km compared with {before['distance']} km).")
        elif now_ok and not was_ok:
            msgs.append(f"{road} was {verb}, which reconnected {start} and {end}: route "
                        f"{' -> '.join(after['path'])} costs {after['distance']} km.")
        elif was_ok and not now_ok:
            msgs.append(f"{road} was {verb} and it was the only link left. {start} can no longer reach {end}.")
            msgs += explain_unreachable(graph, closed_after, start, end)["messages"][1:]
        else:
            msgs.append(f"{road} was {verb}, but {start} still cannot reach {end}.")
            msgs += explain_unreachable(graph, closed_after, start, end)["messages"][1:]
        title = "Route update"
    else:
        label = after["label"]
        msgs.append(f"{road} was {verb}. {label} from {after['start']} now reaches "
                    f"{after['visited_count']} location(s) (before: {before['visited_count']}).")
        if after["unreachable"]:
            msgs.append(f"Unreachable from {after['start']}: {', '.join(after['unreachable'])}.")
        if before["order"] != after["order"]:
            msgs.append("The traversal order changed because the graph's open roads changed.")
        title = "Traversal update"
    return {"title": title, "messages": msgs}


def suggest_alternatives(graph, closed, start, end, limit=3):
    """Next-best routes: close each road of the best path in turn and re-run Dijkstra."""
    base = dijkstra(graph, start, end, closed)
    if not base["reachable"] or len(base["path"]) < 2:
        return []
    found = {}
    for a, b in zip(base["path"], base["path"][1:]):
        r = dijkstra(graph, start, end, closed | {edge_key(a, b)})
        if r["reachable"] and r["path"] != base["path"]:
            found[tuple(r["path"])] = r["distance"]
    alts = [{"path": list(p), "distance": d, "extra": d - base["distance"]} for p, d in found.items()]
    return sorted(alts, key=lambda x: (x["distance"], x["path"]))[:limit]


def graph_status(graph, closed, start, end):
    """Plain-language status of the current educational graph."""
    res = dijkstra(graph, start, end, closed)
    comps = graph.components(closed)
    msgs = []
    if res["reachable"]:
        msgs.append(f"Shortest open route from {start} to {end}: {' -> '.join(res['path'])} "
                    f"({res['distance']} km).")
        if closed:
            base = dijkstra(graph, start, end, frozenset())
            if base["distance"] != res["distance"]:
                msgs.append(f"With every road open it would be {base['distance']} km, so the closures "
                            f"add {res['distance'] - base['distance']:g} km.")
    else:
        return explain_unreachable(graph, closed, start, end) | {"title": "Graph status"}
    alts = suggest_alternatives(graph, closed, start, end)
    if len(res["path"]) < 2:
        msgs.append("Start and destination are the same location, so there is nothing to travel.")
    elif alts:
        msgs.append("Alternatives: " + "; ".join(
            f"{' -> '.join(a['path'])} ({a['distance']} km, +{a['extra']:g} km)" for a in alts) + ".")
    else:
        msgs.append("No alternative route exists: every other path is blocked or needs the same roads.")
    msgs.append(f"{len(closed)} road(s) closed; the network has {len(comps)} connected part(s).")
    return {"title": "Graph status", "messages": msgs, "suggestions": [], "alternatives": alts}
