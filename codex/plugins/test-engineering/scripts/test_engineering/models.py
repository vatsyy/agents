from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FunctionInfo:
    name: str
    qualified_name: str
    path: Path
    line: int
    end_line: int
    is_method: bool = False
    async_function: bool = False
    decorators: list[str] = field(default_factory=list)
    language: str = "python"


@dataclass
class TestCaseInfo:
    name: str
    path: Path
    line: int
    end_line: int
    assertions: int
    branches: int
    fixtures: list[str] = field(default_factory=list)
    parametrized: bool = False
    framework: str = "unknown"
    kind: str = "test"
    assertion_kinds: list[str] = field(default_factory=list)
    assertion_samples: list[str] = field(default_factory=list)
    mock_count: int = 0
    confidence: str = "unknown"
    evidence_type: str = "deterministic"
    risk_notes: list[str] = field(default_factory=list)


@dataclass
class TestFileInfo:
    path: Path
    framework: str
    line_count: int
    test_count: int
    assertion_count: int
    cases: list[TestCaseInfo]
    helpers: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)


@dataclass
class CoverageIndex:
    by_path: dict[Path, dict[int, int]]
    by_name: dict[str, dict[int, int]]


@dataclass(frozen=True)
class TraversalError:
    path: str
    message: str


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class RepoConfig:
    ignore_path_contains: tuple[str, ...] = ()
    generated_path_contains: tuple[str, ...] = ()


@dataclass
class ProjectInventory:
    files: list[Path] = field(default_factory=list)
    discovered_file_count: int = 0
    supported_candidate_count: int = 0
    unsupported_code_files: list[Path] = field(default_factory=list)
    oversized_files: list[Path] = field(default_factory=list)
    unreadable_files: list[Path] = field(default_factory=list)
    symlink_files: list[Path] = field(default_factory=list)
    traversal_errors: list[TraversalError] = field(default_factory=list)
    excluded_directory_count: int = 0
    truncated: bool = False


@dataclass
class CoverageLoadResult:
    index: CoverageIndex
    state: str
    path: Path | None = None
    class_count: int = 0
    line_count: int = 0
    diagnostic: Diagnostic | None = None


@dataclass
class GradeEvidence:
    refs: list[Path]
    name_refs: list[Path]
    assertions: int
    cases: list[TestCaseInfo]
    coverage_status: str
    covered_lines: int | None
    executable_lines: int | None


@dataclass
class TestParseResult:
    cases: list[TestCaseInfo] = field(default_factory=list)
    helpers: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)
    framework: str = "unknown"


@dataclass(frozen=True)
class SourceReference:
    file: str
    line: int


@dataclass(frozen=True)
class TestCaseReference:
    test: str
    file: str
    line: int
    assertions: int


@dataclass(frozen=True)
class FunctionGrade:
    function: str
    simple_name: str
    file: str
    line: int
    end_line: int
    language: str
    grade: str
    score: int
    evidence_labels: tuple[str, ...]
    evidence_type: str
    confidence: str
    primary_evidence: str
    evidence_confidence: str
    source_ref: SourceReference
    test_refs: tuple[str, ...]
    direct_call_test_refs: tuple[str, ...]
    test_case_refs: tuple[TestCaseReference, ...]
    assertion_evidence: int
    assertion_scope: str
    mapping_method: str
    manual_review_required: bool
    coverage_status: str
    covered_lines: int | None
    executable_lines: int | None
    recommendation: str


@dataclass(frozen=True)
class FunctionFinding:
    grade: FunctionGrade
    static_mapping_status: str | None = None
    entrypoint_group: str | None = None


@dataclass(frozen=True)
class EntrypointExample:
    function: str
    file: str
    line: int
    risk_reasons: tuple[str, ...]


@dataclass(frozen=True)
class EntrypointGroup:
    group: str
    count: int
    examples: tuple[EntrypointExample, ...]
    files: tuple[str, ...]
    evidence_type: str
    confidence: str
    recommendation: str


@dataclass(frozen=True)
class AssertionLightFinding:
    test: str
    file: str
    line: int
    evidence_type: str
    confidence: str
    evidence_lines: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class TestCreationFinding:
    function: str
    file: str
    line: int
    test_name: str
    assertion_goal: str
    evidence_type: str
    confidence: str
    risk_level: str
    risk_reasons: tuple[str, ...]
    source_ref: SourceReference


@dataclass(frozen=True)
class TestReference:
    test: str
    line: int
    file: str | None = None
    confidence: str = "unknown"


@dataclass(frozen=True)
class RedundancyFinding:
    normalised_intent: str
    tests: tuple[TestReference, ...]
    evidence_type: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class LowSignalFinding:
    file: str
    reason: str
    tests: tuple[TestReference, ...]
    evidence_type: str
    confidence: str


@dataclass(frozen=True)
class PlaceholderFinding:
    file: str
    line: int
    evidence_type: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class MonolithFinding:
    test: str
    file: str
    line: int
    reasons: tuple[str, ...]
    evidence_type: str
    confidence: str
    evidence_lines: tuple[int, ...]
    recommendation: str


@dataclass(frozen=True)
class TaxonomyAssessment:
    covered: tuple[FunctionFinding, ...]
    missing: tuple[FunctionFinding, ...]
    probably_untested: tuple[FunctionFinding, ...]
    not_directly_mapped: tuple[FunctionFinding, ...]
    missing_by_entrypoint: tuple[EntrypointGroup, ...]
    improvable: tuple[FunctionFinding, ...]
    assertion_light: tuple[AssertionLightFinding, ...]
    needs_to_create: tuple[TestCreationFinding, ...]
    redundant: tuple[RedundancyFinding, ...]
    low_signal: tuple[LowSignalFinding, ...]
    placeholder: tuple[PlaceholderFinding, ...]
    monolith_candidates: tuple[MonolithFinding, ...]


@dataclass(frozen=True)
class FixtureShape:
    fixtures: int
    helpers: int
    parametrized_tests: int
    over_mocked_tests: int


@dataclass(frozen=True)
class HighSignalFile:
    file: str
    framework: str
    tests: int
    assertions: int
    fixtures: int
    helpers: int


@dataclass(frozen=True)
class OrientationAssessment:
    summary: tuple[str, ...]
    runner_clues: tuple[str, ...]
    fixture_shape: FixtureShape
    high_signal_files: tuple[HighSignalFile, ...]


@dataclass(frozen=True)
class CoverageGapAssessment:
    probably_untested: int
    not_directly_mapped: int
    missing_by_entrypoint: tuple[EntrypointGroup, ...]


@dataclass(frozen=True)
class MockHeavyFinding:
    test: str
    file: str
    line: int
    mock_count: int
    confidence: str
    evidence_type: str
    reason: str


@dataclass(frozen=True)
class HeuristicExamples:
    over_mocked: tuple[MockHeavyFinding, ...]
    low_signal: tuple[LowSignalFinding, ...]
    placeholder: tuple[PlaceholderFinding, ...]


@dataclass(frozen=True)
class RiskFunctionFinding:
    grade: FunctionGrade
    risk_level: str
    risk_reasons: tuple[str, ...]


@dataclass(frozen=True)
class TrustQuestion:
    question: str
    answer: str
    evidence_type: str
    confidence: str


@dataclass(frozen=True)
class TrustAssessment:
    summary: str
    mocked_unit_trust: str
    behavioural_coverage: str
    refactor_readiness: str
    confidence: str
    evidence_type: str
    coverage_gap: CoverageGapAssessment
    static_confidence_caveat: str
    grade_counts: dict[str, int]
    confidence_counts: dict[str, int]
    risk_counts: dict[str, int]
    heuristic_examples: HeuristicExamples
    highest_risk_functions: tuple[RiskFunctionFinding, ...]
    questions: tuple[TrustQuestion, ...]


@dataclass(frozen=True)
class ActionRecommendation:
    kind: str
    target: str
    file: str
    line: int
    recommendation: str
    evidence_type: str
    confidence: str
    candidate_count: int | None = None
    examples: tuple[EntrypointExample, ...] = ()


@dataclass(frozen=True)
class PreparedFile:
    path: Path
    text: str
    adapter_name: str
    artifact: ast.AST | str


@dataclass(frozen=True)
class AdapterRuntime:
    analysed_source_files: int
    analysed_test_files: int
    attempted_source_files: int
    attempted_test_files: int
    failed_files: int
    state: str


@dataclass
class AnalysisRun:
    root: Path
    inventory: ProjectInventory
    repo_config: RepoConfig
    excluded_files: list[Path]
    attempted_source_files: list[Path]
    attempted_test_files: list[Path]
    source_files: list[Path]
    test_files: list[Path]
    texts: dict[Path, str]
    prepared_files: dict[Path, PreparedFile]
    adapter_runtime: dict[str, AdapterRuntime]
    analysis_failures: list[Diagnostic]
    diagnostics: list[Diagnostic]
    coverage: CoverageLoadResult
    coverage_xml: Path | None
    source_functions: list[FunctionInfo]
    tests: list[TestFileInfo]


@dataclass(frozen=True)
class ProjectionScope:
    status: str
    evidence_scope: str
    repository_verdict_available: bool
    projections: dict[str, str]


@dataclass
class AnalysisAssessment:
    scope: ProjectionScope
    framework_hints: list[str]
    function_grades: tuple[FunctionGrade, ...]
    taxonomy: TaxonomyAssessment
    orientation: OrientationAssessment
    trust: TrustAssessment
    action_plan: tuple[ActionRecommendation, ...]


@dataclass
class AnalysisOutcome:
    run: AnalysisRun
    assessment: AnalysisAssessment
