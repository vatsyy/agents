from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FunctionMetric:
    name: str
    kind: str
    start: int
    end: int | None
    loc: int | None
    sloc: int | None
    params: int | None
    statements: int | None
    returns: int | None
    branches: int | None
    loops: int | None
    exceptions: int | None
    bool_ops: int | None
    comprehensions: int | None
    calls: int | None
    fan_out: int | None
    called_symbols: str
    internal_fan_in: int | None
    internal_fan_out: int | None
    max_nesting: int | None
    max_loop_depth: int | None
    cyclomatic: int
    cognitive: int | None
    halstead_vocab: int | None
    halstead_length: int | None
    halstead_volume: float | None
    halstead_difficulty: float | None
    halstead_effort: float | None
    maintainability_index: float | None
    direct_recursion: bool | None
    indirect_recursion: bool | None
    awaits: int | None
    task_calls: int | None
    lock_calls: int | None
    raises: int | None
    assignments: int | None
    global_writes: int | None
    mutations: int | None
    allocation_ops: int | None
    max_literal_size: int | None
    db_calls: int | None
    network_calls: int | None
    file_calls: int | None
    subprocess_calls: int | None
    io_calls_in_loops: int | None
    n_plus_one_risk: bool | None
    time_complexity_hint: str
    space_complexity_hint: str
    repo_references: int | None
    git_commits: int | None
    git_churn_lines: int | None
    coverage_percent: float | None
    review_flags: str
    risk: str
    evidence: str = ""
    claim_type: str = "deterministic metrics with heuristic review flags"
    confidence: str = "high for counts, medium for review flags"
    calibration: str = "Static metrics are facts from syntax; performance claims need manual validation."
