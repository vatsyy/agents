from __future__ import annotations

from collections.abc import Iterator, Sequence

from .models import FunctionMetric


def enrich_internal_call_graph(
    metrics: list[FunctionMetric], calls_by_name: dict[str, set[str]]
) -> None:
    names = {metric.name for metric in metrics}
    graph = build_internal_call_graph(names, calls_by_name)
    fan_in = count_fan_in(names, graph)
    cycle_nodes = nodes_in_cycles(graph)
    for metric in metrics:
        apply_graph_metrics(metric, graph, fan_in, cycle_nodes)


def build_internal_call_graph(
    names: set[str], calls_by_name: dict[str, set[str]]
) -> dict[str, set[str]]:
    simple_to_full = map_simple_names(names)
    return {
        name: matched_internal_calls(
            name, calls_by_name.get(name, set()), names, simple_to_full
        )
        for name in names
    }


def map_simple_names(names: set[str]) -> dict[str, set[str]]:
    simple_to_full: dict[str, set[str]] = {}
    for name in names:
        simple_to_full.setdefault(name.split(".")[-1], set()).add(name)
    return simple_to_full


def matched_internal_calls(
    name: str,
    calls: set[str],
    names: set[str],
    simple_to_full: dict[str, set[str]],
) -> set[str]:
    matches = set().union(
        *(simple_to_full.get(call.split(".")[-1], set()) for call in calls)
    )
    matches.update(call for call in calls if call in names)
    matches.discard(name)
    return matches


def count_fan_in(names: set[str], graph: dict[str, set[str]]) -> dict[str, int]:
    fan_in = {name: 0 for name in names}
    for callees in graph.values():
        increment_fan_in(fan_in, callees)
    return fan_in


def increment_fan_in(fan_in: dict[str, int], callees: set[str]) -> None:
    for callee in callees:
        fan_in[callee] += 1


def apply_graph_metrics(
    metric: FunctionMetric,
    graph: dict[str, set[str]],
    fan_in: dict[str, int],
    cycle_nodes: set[str],
) -> None:
    metric.internal_fan_out = len(graph.get(metric.name, set()))
    metric.internal_fan_in = fan_in[metric.name]
    metric.indirect_recursion = metric.name in cycle_nodes
    metric.review_flags = join_flags(graph_review_flags(metric))


def graph_review_flags(metric: FunctionMetric) -> list[str]:
    flags = split_flags(metric.review_flags)
    flags.extend(flag for flag, applies in graph_flag_rules(metric) if applies)
    return flags


def graph_flag_rules(metric: FunctionMetric) -> tuple[tuple[str, bool], ...]:
    return (
        ("indirect recursion", metric.indirect_recursion),
        ("high fan-in", metric.internal_fan_in >= 5),
        ("high internal fan-out", metric.internal_fan_out >= 5),
    )


def nodes_in_cycles(graph: dict[str, set[str]]) -> set[str]:
    """Return nodes in non-trivial strongly connected components.

    A singleton component is intentionally not an indirect cycle.  Direct
    self-calls are recorded separately by the AST metric lane, and the
    internal graph also removes self-edges before reaching this function.
    The two iterative passes visit each node and edge a bounded number of
    times, avoiding the exponential simple-path enumeration this replaces.
    Component discovery order is irrelevant because SCC membership is
    order-independent and the public result is a set.
    """
    adjacency = graph_with_all_nodes(graph)
    reverse = reverse_graph(adjacency)
    finish_order = finishing_order(adjacency)
    return non_trivial_components(reverse, reversed(finish_order))


def graph_with_all_nodes(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    nodes = set(graph)
    for callees in graph.values():
        nodes.update(callees)
    return {node: graph.get(node, set()) for node in nodes}


def reverse_graph(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    reverse = {node: set() for node in graph}
    for caller, callees in graph.items():
        for callee in callees:
            reverse[callee].add(caller)
    return reverse


def finishing_order(graph: dict[str, set[str]]) -> list[str]:
    visited: set[str] = set()
    order: list[str] = []
    for start, neighbours in graph.items():
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(neighbours))]
        while stack:
            node, neighbours = stack[-1]
            try:
                next_node = next(neighbours)
            except StopIteration:
                order.append(node)
                stack.pop()
                continue
            if next_node in visited:
                continue
            visited.add(next_node)
            stack.append((next_node, iter(graph[next_node])))
    return order


def non_trivial_components(
    reverse: dict[str, set[str]], starts: Iterator[str]
) -> set[str]:
    visited: set[str] = set()
    cycle_nodes: set[str] = set()
    for start in starts:
        if start in visited:
            continue
        component = collect_component(reverse, start, visited)
        if len(component) > 1:
            cycle_nodes.update(component)
    return cycle_nodes


def collect_component(
    graph: dict[str, set[str]], start: str, visited: set[str]
) -> set[str]:
    component: set[str] = set()
    stack = [start]
    visited.add(start)
    while stack:
        node = stack.pop()
        component.add(node)
        for next_node in graph[node]:
            if next_node in visited:
                continue
            visited.add(next_node)
            stack.append(next_node)
    return component


def split_flags(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def join_flags(flags: Sequence[str]) -> str:
    deduped = list(dict.fromkeys(flags))
    return ", ".join(deduped)
