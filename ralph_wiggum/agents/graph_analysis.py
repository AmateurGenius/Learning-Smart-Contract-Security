"""Graph analysis agent that consumes Slither JSON output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ralph_wiggum.escalation import EscalationRouter
from ralph_wiggum.state import StateStore


@dataclass
class GraphAnalysis:
    """Analyze a call graph and flag risky patterns."""

    state_store: StateStore
    escalation_router: EscalationRouter = field(default_factory=EscalationRouter)
    risk_threshold: int = 1

    def analyze(self, slither_json: dict[str, Any]) -> dict[str, Any]:
        """Analyze Slither JSON data and persist graph risk findings."""
        backend, graph, networkx = self._build_call_graph(slither_json)
        privileged_entry_points = self._privileged_entry_points(slither_json)
        cycles = self._detect_cycles(backend, graph, networkx)
        sensitive_calls = self._sensitive_external_calls(
            slither_json,
            backend,
            graph,
            privileged_entry_points,
            networkx,
        )

        score = 0
        if cycles:
            score += 1
        if privileged_entry_points:
            score += 1
        if sensitive_calls:
            score += 1

        findings = {
            "graph_backend": backend,
            "score": score,
            "cycles": cycles,
            "privileged_entry_points": sorted(privileged_entry_points),
            "sensitive_external_calls": sorted(sensitive_calls),
        }

        state = self.state_store.load()
        state["graph_analysis"] = findings

        if score >= self.risk_threshold:
            state["escalation_level"] = 2
            self.escalation_router.level = 2

        self.state_store.save(state)
        return findings

    def _build_call_graph(self, slither_json: dict[str, Any]) -> tuple[str, Any, Any | None]:
        """Build a call graph from available Slither JSON hints."""
        networkx = self._try_import_networkx()
        if networkx:
            graph = networkx.DiGraph()
        else:
            graph = {}

        call_graph = slither_json.get("call_graph")
        if isinstance(call_graph, dict):
            for node in call_graph.get("nodes", []):
                self._add_node(graph, node)
            for edge in call_graph.get("edges", []):
                self._add_edge(graph, edge.get("from"), edge.get("to"))

        for edge in slither_json.get("function_calls", []):
            self._add_edge(graph, edge.get("caller"), edge.get("callee"))

        for function in slither_json.get("functions", []):
            name = function.get("name")
            for callee in function.get("calls", []):
                self._add_edge(graph, name, callee)

        return ("networkx" if networkx else "fallback"), graph, networkx

    def _privileged_entry_points(self, slither_json: dict[str, Any]) -> set[str]:
        """Identify privileged entry points by visibility and modifiers."""
        privileged = set()
        for function in slither_json.get("functions", []):
            visibility = (function.get("visibility") or "").lower()
            modifiers = [modifier.lower() for modifier in function.get("modifiers", [])]
            name = function.get("name")
            if visibility in {"public", "external"} and any(
                keyword in modifier
                for modifier in modifiers
                for keyword in ("onlyowner", "owner", "admin", "onlyrole")
            ):
                if name:
                    privileged.add(name)
        return privileged

    def _sensitive_external_calls(
        self,
        slither_json: dict[str, Any],
        backend: str,
        graph: Any,
        privileged_entry_points: set[str],
        networkx: Any | None,
    ) -> set[str]:
        """Detect external calls reachable from privileged entry points."""
        external_callers = {
            function.get("name")
            for function in slither_json.get("functions", [])
            if function.get("external_calls")
        }
        risky = set()
        for entry in privileged_entry_points:
            for target in external_callers:
                if self._has_path(backend, graph, entry, target, networkx):
                    risky.add(target)
        return risky

    def _try_import_networkx(self) -> Any | None:
        """Try to import networkx, returning the module or None."""
        try:
            import networkx  # type: ignore[import-not-found]
        except ModuleNotFoundError:
            return None
        return networkx

    def _add_node(self, graph: Any, node: Any) -> None:
        """Add a node to the graph for either backend."""
        if hasattr(graph, "add_node"):
            graph.add_node(node)
            return
        graph.setdefault(node, set())

    def _add_edge(self, graph: Any, source: Any, target: Any) -> None:
        """Add an edge to the graph for either backend."""
        if source is None or target is None:
            return
        if hasattr(graph, "add_edge"):
            graph.add_edge(source, target)
            return
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())

    def _detect_cycles(self, backend: str, graph: Any, networkx: Any | None) -> list[list[Any]]:
        """Detect cycles using the selected backend."""
        if backend == "networkx" and networkx:
            return list(networkx.simple_cycles(graph))
        return self._fallback_cycles(graph)

    def _fallback_cycles(self, graph: dict[Any, set[Any]]) -> list[list[Any]]:
        """Detect cycles in a directed graph using DFS colors."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in graph}
        cycles: list[list[Any]] = []

        def visit(node: Any, stack: list[Any]) -> None:
            color[node] = GRAY
            stack.append(node)
            for neighbor in graph.get(node, set()):
                if color[neighbor] == WHITE:
                    visit(neighbor, stack)
                elif color[neighbor] == GRAY:
                    cycle_start = stack.index(neighbor)
                    cycles.append(stack[cycle_start:] + [neighbor])
            stack.pop()
            color[node] = BLACK

        for node in graph:
            if color[node] == WHITE:
                visit(node, [])
        return cycles

    def _has_path(
        self,
        backend: str,
        graph: Any,
        source: Any,
        target: Any,
        networkx: Any | None,
    ) -> bool:
        """Check if a path exists between two nodes."""
        if source is None or target is None:
            return False
        if backend == "networkx" and networkx:
            return (
                graph.has_node(source)
                and graph.has_node(target)
                and networkx.has_path(graph, source, target)
            )
        return self._fallback_has_path(graph, source, target)

    def _fallback_has_path(self, graph: dict[Any, set[Any]], source: Any, target: Any) -> bool:
        """Check path existence using BFS."""
        if source not in graph or target not in graph:
            return False
        queue = [source]
        visited = {source}
        while queue:
            node = queue.pop(0)
            if node == target:
                return True
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return False
