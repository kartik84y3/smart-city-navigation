"""Graph data structure and the ADS algorithms (Dijkstra, BFS, DFS).

Everything here is pure Python with no Flask or database imports, so the
algorithms can be unit-tested and explained on their own.

Terminology
-----------
* A *closed* road is an undirected edge that is temporarily ignored.
  Closed roads are passed in as a set of ``edge_key(a, b)`` tuples.
* Neighbours are always visited in alphabetical order so results are
  deterministic and easy to reproduce in a viva.
"""
import heapq
import json
import math
from collections import deque
from pathlib import Path

INF = math.inf

COMPLEXITY = {
    "dijkstra": {
        "time": "O((V + E) log V)",
        "space": "O(V)",
        "note": "Uses a binary min-heap (Python heapq). Without a heap it is O(V^2).",
    },
    "bfs": {"time": "O(V + E)", "space": "O(V)", "note": "Uses a FIFO queue."},
    "dfs": {"time": "O(V + E)", "space": "O(V)", "note": "Uses a stack (explicit, not recursion)."},
}

EXPLANATIONS = {
    "dijkstra": (
        "Dijkstra's algorithm always settles the closest unsettled location next. "
        "When a location is settled its distance can never improve, because every "
        "road has a positive length. It then checks ('relaxes') the roads leaving "
        "that location to see if they give a shorter way to a neighbour."
    ),
    "bfs": (
        "Breadth-First Search explores the graph level by level. It first visits the "
        "start, then everything one road away, then everything two roads away, and so "
        "on, using a queue. It counts roads (hops), not kilometres, so it does not "
        "find the shortest weighted path."
    ),
    "dfs": (
        "Depth-First Search follows one road as deep as it can go, and only when it "
        "reaches a dead end does it backtrack to try the next unexplored road. It uses "
        "a stack. It reaches every connected location, but the path it takes is not "
        "necessarily the shortest."
    ),
}

ALGORITHM_NAMES = {"dijkstra": "Dijkstra", "bfs": "BFS", "dfs": "DFS"}


def edge_key(a, b):
    """Canonical key for an undirected road."""
    return tuple(sorted((a, b)))


class CityGraph:
    """Weighted, undirected graph stored as an adjacency dictionary."""

    def __init__(self, nodes, edges):
        self.positions = {}
        self.adj = {}
        for n in nodes:
            nid = n["id"]
            if nid in self.adj:
                raise ValueError(f"Duplicate node: {nid}")
            self.adj[nid] = {}
            self.positions[nid] = (n.get("x", 0), n.get("y", 0))
        self.edge_list = []
        for e in edges:
            a, b, w = e["from"], e["to"], e["distance"]
            if a not in self.adj or b not in self.adj:
                raise ValueError(f"Edge uses unknown node: {a} - {b}")
            if a == b:
                raise ValueError(f"Self-loop not allowed: {a}")
            if not isinstance(w, (int, float)) or w <= 0:
                raise ValueError(f"Edge weight must be positive: {a} - {b}")
            if b in self.adj[a]:
                raise ValueError(f"Duplicate edge: {a} - {b}")
            self.adj[a][b] = w
            self.adj[b][a] = w
            self.edge_list.append({"from": a, "to": b, "distance": w})

    @classmethod
    def from_json(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["nodes"], data["edges"])

    # ---- queries -------------------------------------------------------
    @property
    def nodes(self):
        return list(self.adj)

    def has_node(self, n):
        return n in self.adj

    def has_edge(self, a, b):
        return a in self.adj and b in self.adj[a]

    def weight(self, a, b):
        return self.adj[a][b]

    def neighbors(self, node, closed=frozenset()):
        """Open neighbours of ``node`` as (name, weight), alphabetical."""
        return [(v, w) for v, w in sorted(self.adj[node].items())
                if edge_key(node, v) not in closed]

    def open_edge_count(self, closed=frozenset()):
        return sum(1 for e in self.edge_list if edge_key(e["from"], e["to"]) not in closed)

    def components(self, closed=frozenset()):
        """Connected components over open roads (list of sorted node lists)."""
        seen, comps = set(), []
        for s in self.adj:
            if s in seen:
                continue
            comp, q = [], deque([s])
            seen.add(s)
            while q:
                u = q.popleft()
                comp.append(u)
                for v, _ in self.neighbors(u, closed):
                    if v not in seen:
                        seen.add(v)
                        q.append(v)
            comps.append(sorted(comp))
        return comps

    def reachable_from(self, start, closed=frozenset()):
        for comp in self.components(closed):
            if start in comp:
                return comp
        return []


# ---------------------------------------------------------------------------
# Dijkstra
# ---------------------------------------------------------------------------
def dijkstra(graph, start, end, closed=frozenset()):
    """Shortest path from ``start`` to ``end`` on the open roads.

    Stops as soon as ``end`` is settled (popped from the heap).
    Returns a dict with path, distance, visited order and step-by-step log.
    """
    dist = {n: INF for n in graph.adj}
    prev = {}
    dist[start] = 0
    heap = [(0, start)]
    settled = set()
    order, steps = [], []
    relaxations = 0

    while heap:
        d, u = heapq.heappop(heap)
        if u in settled or d > dist[u]:
            continue  # stale heap entry
        settled.add(u)
        order.append(u)
        step = {"node": u, "distance": d, "relaxed": [], "queue": []}
        if u != end:
            for v, w in graph.neighbors(u, closed):
                if v in settled:
                    continue
                nd = d + w
                improved = nd < dist[v]
                relaxations += 1
                step["relaxed"].append({"to": v, "weight": w, "candidate": nd,
                                        "previous": None if dist[v] == INF else dist[v],
                                        "improved": improved})
                if improved:
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))
        step["queue"] = sorted(
            ({"node": n, "distance": dd} for dd, n in heap if n not in settled and dd == dist[n]),
            key=lambda x: (x["distance"], x["node"]))
        step["description"] = _dijkstra_step_text(step, end)
        steps.append(step)
        if u == end:
            break

    reachable = dist[end] != INF
    path = []
    if reachable:
        cur = end
        path = [cur]
        while cur in prev:
            cur = prev[cur]
            path.append(cur)
        path.reverse()
    return {
        "algorithm": "dijkstra", "start": start, "end": end,
        "reachable": reachable,
        "path": path,
        "distance": dist[end] if reachable else None,
        "order": order,
        "visited_count": len(order),
        "relaxations": relaxations,
        "steps": steps,
        "message": "Shortest path found." if reachable else "No route available.",
    }


def _dijkstra_step_text(step, end):
    u, d = step["node"], step["distance"]
    if u == end:
        return f"Settle {u} at distance {d}. This is the destination, so the search stops."
    if not step["relaxed"]:
        return f"Settle {u} at distance {d}. No unsettled neighbours to update."
    upd = [r for r in step["relaxed"] if r["improved"]]
    if upd:
        txt = ", ".join(f"{r['to']} = {r['candidate']}" for r in upd)
        return f"Settle {u} at distance {d}. Better distances found: {txt}."
    return f"Settle {u} at distance {d}. No neighbour got a shorter distance."


# ---------------------------------------------------------------------------
# BFS
# ---------------------------------------------------------------------------
def bfs(graph, start, closed=frozenset()):
    """Level-by-level traversal from ``start`` using a FIFO queue."""
    level = {start: 0}
    parent = {}
    queue = deque([start])
    order, steps, tree_edges = [], [], []
    while queue:
        u = queue.popleft()
        order.append(u)
        discovered = []
        for v, _ in graph.neighbors(u, closed):
            if v not in level:
                level[v] = level[u] + 1
                parent[v] = u
                tree_edges.append([u, v])
                queue.append(v)
                discovered.append(v)
        txt = f"Dequeue {u} (level {level[u]})."
        txt += (" Enqueue " + ", ".join(discovered) + ".") if discovered else " No new locations to enqueue."
        steps.append({"node": u, "level": level[u], "discovered": discovered,
                      "queue": list(queue), "description": txt})
    levels = {}
    for n in order:
        levels.setdefault(level[n], []).append(n)
    return {
        "algorithm": "bfs", "start": start, "order": order,
        "levels": [levels[k] for k in sorted(levels)],
        "tree_edges": tree_edges,
        "visited_count": len(order),
        "unreachable": sorted(set(graph.adj) - set(order)),
        "steps": steps,
        "message": "BFS traversal completed.",
    }


# ---------------------------------------------------------------------------
# DFS (iterative, so it never hits Python's recursion limit)
# ---------------------------------------------------------------------------
def dfs(graph, start, closed=frozenset()):
    """Depth-first traversal from ``start`` using an explicit stack.

    Visits neighbours in alphabetical order, giving exactly the same order
    as the usual recursive version.
    """
    visited = {start}
    order = [start]
    tree_edges = []
    depth = {start: 0}
    stack = [(start, iter(graph.neighbors(start, closed)))]
    steps = [{"node": start, "event": "visit", "from": None, "depth": 0,
              "stack": [start], "description": f"Visit {start} (start, depth 0)."}]
    while stack:
        u, it = stack[-1]
        advanced = False
        for v, _ in it:
            if v not in visited:
                visited.add(v)
                order.append(v)
                depth[v] = depth[u] + 1
                tree_edges.append([u, v])
                stack.append((v, iter(graph.neighbors(v, closed))))
                steps.append({"node": v, "event": "visit", "from": u, "depth": depth[v],
                              "stack": [s[0] for s in stack],
                              "description": f"Go deeper: visit {v} from {u} (depth {depth[v]})."})
                advanced = True
                break
        if not advanced:
            stack.pop()
            parent = stack[-1][0] if stack else None
            steps.append({"node": u, "event": "backtrack", "from": parent, "depth": depth[u],
                          "stack": [s[0] for s in stack],
                          "description": (f"Dead end at {u}: backtrack to {parent}." if parent
                                          else f"{u} has no unexplored roads. Traversal finished.")})
    return {
        "algorithm": "dfs", "start": start, "order": order,
        "tree_edges": tree_edges,
        "visited_count": len(order),
        "unreachable": sorted(set(graph.adj) - set(order)),
        "steps": steps,
        "message": "DFS traversal completed.",
    }


def run_algorithm(graph, algorithm, start, end=None, closed=frozenset()):
    """Dispatch helper used by the API. Raises ValueError on bad input."""
    algorithm = (algorithm or "").lower()
    if not graph.has_node(start):
        raise ValueError("Please select a valid start location.")
    if algorithm == "dijkstra":
        if not graph.has_node(end):
            raise ValueError("Please select a valid destination.")
        res = dijkstra(graph, start, end, closed)
    elif algorithm == "bfs":
        res = bfs(graph, start, closed)
    elif algorithm == "dfs":
        res = dfs(graph, start, closed)
    else:
        raise ValueError("Unknown algorithm.")
    res["label"] = ALGORITHM_NAMES[algorithm]
    res["complexity"] = COMPLEXITY[algorithm]
    res["explanation"] = EXPLANATIONS[algorithm]
    res["vertices"] = len(graph.adj)
    res["open_edges"] = graph.open_edge_count(closed)
    return res
