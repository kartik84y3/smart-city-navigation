"""Unit tests for Dijkstra, BFS, DFS and closures (pure algorithm code)."""
import itertools
import math
import random
import unittest
from pathlib import Path

from graph_algorithms import CityGraph, bfs, dfs, dijkstra, edge_key, run_algorithm

DATA = Path(__file__).resolve().parent.parent / "data" / "city_graph.json"


def make(edges, extra_nodes=()):
    names = sorted({n for a, b, _ in edges for n in (a, b)} | set(extra_nodes))
    return CityGraph([{"id": n} for n in names],
                     [{"from": a, "to": b, "distance": w} for a, b, w in edges])


def bellman_ford(graph, start, closed=frozenset()):
    """Independent reference implementation used to cross-check Dijkstra."""
    dist = {n: math.inf for n in graph.nodes}
    dist[start] = 0
    for _ in range(len(graph.nodes)):
        changed = False
        for e in graph.edge_list:
            if edge_key(e["from"], e["to"]) in closed:
                continue
            a, b, w = e["from"], e["to"], e["distance"]
            if dist[a] + w < dist[b]:
                dist[b], changed = dist[a] + w, True
            if dist[b] + w < dist[a]:
                dist[a], changed = dist[b] + w, True
        if not changed:
            break
    return dist


class DijkstraTests(unittest.TestCase):
    def test_textbook_graph(self):
        g = make([("A", "B", 4), ("A", "C", 2), ("B", "C", 1), ("B", "D", 5), ("C", "D", 8),
                  ("C", "E", 10), ("D", "E", 2), ("D", "F", 6), ("E", "F", 3)])
        r = dijkstra(g, "A", "F")
        self.assertEqual(r["distance"], 13)
        self.assertEqual(r["path"], ["A", "C", "B", "D", "E", "F"])

    def test_same_start_and_end(self):
        g = make([("A", "B", 1)])
        r = dijkstra(g, "A", "A")
        self.assertEqual((r["path"], r["distance"]), (["A"], 0))

    def test_unreachable_in_disconnected_graph(self):
        g = make([("A", "B", 1), ("C", "D", 1)])
        r = dijkstra(g, "A", "D")
        self.assertFalse(r["reachable"])
        self.assertEqual(r["path"], [])
        self.assertIsNone(r["distance"])

    def test_project_graph_known_routes(self):
        g = CityGraph.from_json(DATA)
        r = dijkstra(g, "University", "Airport")
        self.assertEqual((r["path"], r["distance"]), (["University", "Mohali", "Airport"], 7))
        r = dijkstra(g, "University", "Railway Station")
        self.assertEqual(r["distance"], 9)

    def test_matches_bellman_ford_on_random_graphs(self):
        rng = random.Random(42)
        for _ in range(200):
            n = rng.randint(2, 9)
            nodes = [f"N{i}" for i in range(n)]
            edges = [(a, b, rng.randint(1, 15)) for a, b in itertools.combinations(nodes, 2)
                     if rng.random() < 0.4]
            g = make(edges, extra_nodes=nodes)
            closed = frozenset(edge_key(a, b) for a, b, _ in edges if rng.random() < 0.25)
            s = rng.choice(nodes)
            ref = bellman_ford(g, s, closed)
            for t in nodes:
                r = dijkstra(g, s, t, closed)
                if math.isinf(ref[t]):
                    self.assertFalse(r["reachable"])
                else:
                    self.assertEqual(r["distance"], ref[t])
                    # the returned path must be valid, open and add up to the cost
                    self.assertEqual(r["path"][0], s)
                    self.assertEqual(r["path"][-1], t)
                    total = 0
                    for x, y in zip(r["path"], r["path"][1:]):
                        self.assertTrue(g.has_edge(x, y))
                        self.assertNotIn(edge_key(x, y), closed)
                        total += g.weight(x, y)
                    self.assertEqual(total, r["distance"])

    def test_steps_and_counts_are_recorded(self):
        g = CityGraph.from_json(DATA)
        r = dijkstra(g, "University", "Airport")
        self.assertEqual(r["visited_count"], len(r["order"]))
        self.assertEqual(len(r["steps"]), r["visited_count"])
        self.assertEqual(r["steps"][0]["node"], "University")
        self.assertEqual(r["order"][-1], "Airport")


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.g = CityGraph.from_json(DATA)

    def test_closure_changes_route(self):
        closed = frozenset({edge_key("Mohali", "Airport")})
        r = dijkstra(self.g, "University", "Airport", closed)
        self.assertEqual(r["distance"], 12)
        self.assertEqual(r["path"], ["University", "Kharar", "Airport"])

    def test_reopen_restores_route(self):
        r = dijkstra(self.g, "University", "Airport", frozenset())
        self.assertEqual(r["distance"], 7)

    def test_closing_leaf_road_disconnects(self):
        closed = frozenset({edge_key("Hospital", "Sector 17")})
        r = dijkstra(self.g, "University", "Hospital", closed)
        self.assertFalse(r["reachable"])
        comps = self.g.components(closed)
        self.assertEqual(len(comps), 2)
        self.assertIn(["Hospital"], comps)

    def test_closed_roads_are_not_traversed(self):
        closed = frozenset({edge_key("University", "Kharar"), edge_key("University", "Mohali")})
        self.assertEqual(bfs(self.g, "University", closed)["order"], ["University"])
        self.assertEqual(dfs(self.g, "University", closed)["order"], ["University"])


class TraversalTests(unittest.TestCase):
    def test_bfs_levels(self):
        g = make([("A", "B", 1), ("A", "C", 1), ("B", "D", 1), ("C", "D", 1), ("D", "E", 1)])
        r = bfs(g, "A")
        self.assertEqual(r["order"], ["A", "B", "C", "D", "E"])
        self.assertEqual(r["levels"], [["A"], ["B", "C"], ["D"], ["E"]])

    def test_dfs_order_matches_recursive_definition(self):
        g = make([("A", "B", 1), ("A", "C", 1), ("B", "D", 1), ("C", "D", 1), ("D", "E", 1)])

        def recursive(u, seen, out):
            seen.add(u)
            out.append(u)
            for v, _ in g.neighbors(u):
                if v not in seen:
                    recursive(v, seen, out)
            return out

        self.assertEqual(dfs(g, "A")["order"], recursive("A", set(), []))
        self.assertEqual(dfs(g, "A")["order"], ["A", "B", "D", "C", "E"])

    def test_dfs_records_backtracking(self):
        g = make([("A", "B", 1), ("A", "C", 1)])
        events = [s["event"] for s in dfs(g, "A")["steps"]]
        self.assertIn("backtrack", events)

    def test_disconnected_graph_reports_unreachable(self):
        g = make([("A", "B", 1), ("C", "D", 1)])
        for fn in (bfs, dfs):
            r = fn(g, "A")
            self.assertEqual(r["order"], ["A", "B"])
            self.assertEqual(r["unreachable"], ["C", "D"])

    def test_traversals_visit_same_set(self):
        g = CityGraph.from_json(DATA)
        self.assertEqual(set(bfs(g, "Kharar")["order"]), set(dfs(g, "Kharar")["order"]))
        self.assertEqual(len(bfs(g, "Kharar")["order"]), 9)

    def test_long_chain_does_not_hit_recursion_limit(self):
        n = 3000
        g = make([(f"N{i:05d}", f"N{i + 1:05d}", 1) for i in range(n)])
        self.assertEqual(len(dfs(g, "N00000")["order"]), n + 1)


class RunAlgorithmTests(unittest.TestCase):
    def test_validation(self):
        g = CityGraph.from_json(DATA)
        with self.assertRaises(ValueError):
            run_algorithm(g, "dijkstra", "Nowhere", "Airport")
        with self.assertRaises(ValueError):
            run_algorithm(g, "dijkstra", "University", "Nowhere")
        with self.assertRaises(ValueError):
            run_algorithm(g, "astar", "University", "Airport")

    def test_metadata(self):
        g = CityGraph.from_json(DATA)
        r = run_algorithm(g, "dijkstra", "University", "Airport")
        self.assertEqual(r["complexity"]["time"], "O((V + E) log V)")
        self.assertEqual(r["vertices"], 9)

    def test_graph_validation(self):
        with self.assertRaises(ValueError):
            CityGraph([{"id": "A"}, {"id": "B"}], [{"from": "A", "to": "B", "distance": -1}])
        with self.assertRaises(ValueError):
            CityGraph([{"id": "A"}], [{"from": "A", "to": "Z", "distance": 1}])


if __name__ == "__main__":
    unittest.main()
