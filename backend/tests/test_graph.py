"""Tests for the relationship graph and its algorithms (spec 7-10).

The traversal and path routines are hand-written, so they are cross-checked
against NetworkX's own implementations on the real 5,000-event graph -- an
independent oracle rather than expectations copied from the implementation.
"""

from __future__ import annotations

import random

import networkx as nx
import pytest

from app.graph.astar import astar, hop_distances_to
from app.graph.bfs import bfs
from app.graph.builder import build_graph, edge_weight, graph_stats, min_edge_weight
from app.graph.dfs import dfs
from app.graph.dijkstra import dijkstra, k_shortest_paths, path_cost
from app.models.common import Direction, Heuristic, WeightStrategy

# Costs are rounded to 6 dp in the response, so compare at that resolution.
TOL = 1e-6


@pytest.fixture(scope="module")
def source_nodes(graph):
    """Devices with outbound edges (five servers in this dataset are sinks)."""
    return sorted(node for node in graph.nodes if graph.out_degree(node) > 0)


class TestBuilder:
    def test_shape(self, graph):
        assert graph.number_of_nodes() == 125
        assert graph.graph["event_count"] == 5000

    def test_aggregates_repeated_communication(self, graph, events):
        pairs = {}
        for event in events:
            pairs[(event["src_device"], event["dst_device"])] = (
                pairs.get((event["src_device"], event["dst_device"]), 0) + 1
            )
        assert graph.number_of_edges() == len(pairs)
        for (src, dst), count in list(pairs.items())[:50]:
            assert graph.edges[src, dst]["event_count"] == count

    def test_edge_totals_match_source_events(self, graph, events):
        src, dst = next(iter(graph.edges()))
        expected = sum(
            event["total_bytes"]
            for event in events
            if event["src_device"] == src and event["dst_device"] == dst
        )
        assert graph.edges[src, dst]["total_bytes"] == expected

    def test_node_counters_balance(self, graph, events):
        assert sum(d["events_out"] for _, d in graph.nodes(data=True)) == len(events)
        assert sum(d["events_in"] for _, d in graph.nodes(data=True)) == len(events)

    def test_time_filter_narrows_graph(self, events):
        cutoff = sorted(e["timestamp"] for e in events)[len(events) // 2]
        filtered = build_graph(events, filter={"start_time": cutoff})
        assert filtered.graph["event_count"] < 5000
        assert all(d["last_seen"] >= cutoff for _, _, d in filtered.edges(data=True))

    def test_protocol_filter(self, events):
        udp = build_graph(events, filter={"protocol": 17})
        assert udp.graph["event_count"] == sum(1 for e in events if e["protocol"] == 17)

    def test_stats(self, graph):
        stats = graph_stats(graph)
        assert stats["node_count"] == graph.number_of_nodes()
        assert stats["is_weakly_connected"] is True
        assert len(stats["top_talkers"]) == 5


class TestWeights:
    @pytest.mark.parametrize("strategy", list(WeightStrategy))
    def test_all_weights_strictly_positive(self, graph, strategy):
        """Dijkstra's correctness depends on this."""
        assert all(edge_weight(d, strategy) > 0 for _, _, d in graph.edges(data=True))

    def test_stronger_relationships_cost_less(self):
        frequent = {"event_count": 100, "total_bytes": 10**9, "total_duration": 1000.0}
        rare = {"event_count": 1, "total_bytes": 1000, "total_duration": 1.0}
        for strategy in (WeightStrategy.FREQUENCY, WeightStrategy.BYTES, WeightStrategy.STRENGTH):
            assert edge_weight(frequent, strategy) < edge_weight(rare, strategy)

    def test_hops_is_unit_cost(self):
        assert edge_weight({"event_count": 50}, WeightStrategy.HOPS) == 1.0


class TestBFS:
    def test_matches_networkx_hop_distances(self, graph, source_nodes):
        source = source_nodes[0]
        result = bfs(graph, source, max_depth=3, max_nodes=10**6)
        expected = nx.single_source_shortest_path_length(graph, source, cutoff=3)
        assert {n["device"]: n["depth"] for n in result["nodes"]} == dict(expected)

    def test_levels_group_by_depth(self, graph, source_nodes):
        result = bfs(graph, source_nodes[0], max_depth=2, max_nodes=10**6)
        for depth, members in result["levels"].items():
            assert all(
                node["depth"] == depth for node in result["nodes"] if node["device"] in members
            )

    def test_depth_limit_respected(self, graph, source_nodes):
        result = bfs(graph, source_nodes[0], max_depth=1, max_nodes=10**6)
        assert max(node["depth"] for node in result["nodes"]) <= 1

    def test_node_cap_marks_truncation(self, graph, source_nodes):
        result = bfs(graph, source_nodes[0], max_depth=5, max_nodes=10)
        assert result["node_count"] <= 10
        assert result["truncated"] is True

    def test_tree_edges_form_a_tree(self, graph, source_nodes):
        result = bfs(graph, source_nodes[0], max_depth=3, max_nodes=10**6)
        # Every node except the root is discovered exactly once.
        assert len(result["tree_edges"]) == result["node_count"] - 1

    def test_path_to_target_is_shortest(self, graph, source_nodes):
        source = source_nodes[0]
        target = next(iter(graph.successors(next(iter(graph.successors(source))))))
        result = bfs(graph, source, target=target, max_depth=4, max_nodes=10**6)
        assert result["paths_to_target"]
        path = result["paths_to_target"][0]
        assert path[0] == source and path[-1] == target
        assert len(path) - 1 == nx.shortest_path_length(graph, source, target)

    def test_inbound_direction_follows_predecessors(self, graph):
        sink = next(node for node in graph.nodes if graph.out_degree(node) == 0)
        outbound = bfs(graph, sink, max_depth=1, direction=Direction.OUTBOUND)
        inbound = bfs(graph, sink, max_depth=1, direction=Direction.INBOUND, max_nodes=10**6)
        assert outbound["node_count"] == 1          # a sink has no successors
        assert inbound["node_count"] > 1

    def test_unknown_device_raises(self, graph):
        with pytest.raises(KeyError):
            bfs(graph, "NoSuchDevice")


class TestDFS:
    def test_visits_exactly_the_reachable_set(self, graph, source_nodes):
        source = source_nodes[0]
        result = dfs(graph, source, max_depth=20, max_nodes=10**6)
        assert set(result["order"]) == nx.descendants(graph, source) | {source}

    def test_depth_limit_respected(self, graph, source_nodes):
        result = dfs(graph, source_nodes[0], max_depth=2, max_nodes=10**6)
        assert max(node["depth"] for node in result["nodes"]) <= 2

    def test_discovery_order_starts_at_source(self, graph, source_nodes):
        result = dfs(graph, source_nodes[0], max_depth=3)
        assert result["order"][0] == source_nodes[0]

    def test_paths_to_target_are_simple_and_valid(self, graph, source_nodes):
        source = source_nodes[0]
        target = next(iter(graph.successors(source)))
        result = dfs(graph, source, target=target, max_depth=3, max_nodes=10**6)
        assert result["paths_to_target"]
        for path in result["paths_to_target"]:
            assert path[0] == source and path[-1] == target
            assert len(set(path)) == len(path)                      # loop-free
            assert all(graph.has_edge(u, v) for u, v in zip(path, path[1:]))

    def test_unknown_device_raises(self, graph):
        with pytest.raises(KeyError):
            dfs(graph, "NoSuchDevice")


class TestDijkstra:
    @pytest.mark.parametrize("strategy", list(WeightStrategy))
    def test_matches_networkx(self, graph, strategy):
        rng = random.Random(1234)
        nodes = sorted(graph.nodes)
        for _ in range(20):
            source, target = rng.sample(nodes, 2)
            mine = dijkstra(graph, source, target, weight=strategy)
            try:
                expected = nx.dijkstra_path_length(
                    graph, source, target, weight=lambda u, v, d: edge_weight(d, strategy)
                )
            except nx.NetworkXNoPath:
                assert not mine["found"]
                continue
            assert mine["found"]
            assert mine["cost"] == pytest.approx(expected, abs=TOL)

    def test_path_is_walkable_and_cost_consistent(self, graph, source_nodes):
        rng = random.Random(99)
        nodes = sorted(graph.nodes)
        for _ in range(10):
            source, target = rng.sample(nodes, 2)
            result = dijkstra(graph, source, target)
            if not result["found"]:
                continue
            path = result["path"]
            assert all(graph.has_edge(u, v) for u, v in zip(path, path[1:]))
            assert path_cost(graph, path, WeightStrategy.STRENGTH) == pytest.approx(
                result["cost"], abs=TOL
            )
            assert result["hops"] == len(path) - 1

    def test_hops_strategy_gives_shortest_hop_count(self, graph, source_nodes):
        source = source_nodes[0]
        target = source_nodes[-1]
        result = dijkstra(graph, source, target, weight=WeightStrategy.HOPS)
        if result["found"]:
            assert result["hops"] == nx.shortest_path_length(graph, source, target)

    def test_unreachable_reported_not_raised(self, graph):
        sink = next(node for node in graph.nodes if graph.out_degree(node) == 0)
        other = next(node for node in graph.nodes if node != sink)
        result = dijkstra(graph, sink, other)
        assert result["found"] is False and result["path"] == []

    def test_unknown_device_raises(self, graph, source_nodes):
        with pytest.raises(KeyError):
            dijkstra(graph, source_nodes[0], "NoSuchDevice")


class TestYen:
    def test_paths_are_distinct_and_ordered_by_cost(self, graph, source_nodes):
        source = source_nodes[0]
        target = next(iter(graph.successors(source)))
        paths = k_shortest_paths(graph, source, target, k=4)
        assert paths
        costs = [p["cost"] for p in paths]
        assert costs == sorted(costs)
        assert len({tuple(p["path"]) for p in paths}) == len(paths)

    def test_first_path_equals_dijkstra(self, graph, source_nodes):
        source = source_nodes[0]
        target = next(iter(graph.successors(source)))
        best = dijkstra(graph, source, target)
        assert k_shortest_paths(graph, source, target, k=3)[0]["cost"] == pytest.approx(
            best["cost"], abs=TOL
        )


class TestAStar:
    @pytest.mark.parametrize("strategy", list(WeightStrategy))
    def test_returns_optimal_cost(self, graph, strategy):
        """An admissible heuristic must not change the answer, only the work."""
        rng = random.Random(2024)
        nodes = sorted(graph.nodes)
        for _ in range(15):
            source, target = rng.sample(nodes, 2)
            optimal = dijkstra(graph, source, target, weight=strategy)
            guided = astar(graph, source, target, weight=strategy)
            assert guided["found"] == optimal["found"]
            if optimal["found"]:
                assert guided["cost"] == pytest.approx(optimal["cost"], abs=TOL)

    def test_explores_fewer_nodes_than_dijkstra(self, graph):
        rng = random.Random(7)
        nodes = sorted(graph.nodes)
        guided_total = plain_total = 0
        for _ in range(25):
            source, target = rng.sample(nodes, 2)
            plain = dijkstra(graph, source, target)
            if not plain["found"]:
                continue
            plain_total += plain["nodes_explored"]
            guided_total += astar(graph, source, target)["nodes_explored"]
        assert guided_total < plain_total

    def test_zero_heuristic_equals_dijkstra(self, graph, source_nodes):
        source, target = source_nodes[0], source_nodes[-1]
        guided = astar(graph, source, target, heuristic=Heuristic.ZERO)
        plain = dijkstra(graph, source, target)
        assert guided["cost"] == pytest.approx(plain["cost"], abs=TOL)

    def test_heuristic_never_overestimates(self, graph, source_nodes):
        """Admissibility, checked directly against true costs."""
        target = source_nodes[-1]
        floor = min_edge_weight(graph, WeightStrategy.STRENGTH)
        hops = hop_distances_to(graph, target)
        rng = random.Random(31)
        for node in rng.sample(sorted(graph.nodes), 25):
            actual = dijkstra(graph, node, target)
            if not actual["found"]:
                continue
            assert floor * hops.get(node, 0) <= actual["cost"] + TOL

    def test_path_is_walkable(self, graph, source_nodes):
        result = astar(graph, source_nodes[0], source_nodes[-1])
        if result["found"]:
            assert all(graph.has_edge(u, v) for u, v in zip(result["path"], result["path"][1:]))

    def test_unknown_device_raises(self, graph, source_nodes):
        with pytest.raises(KeyError):
            astar(graph, "NoSuchDevice", source_nodes[0])
