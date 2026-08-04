from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import prepare_analysis_files
from .analysis_contract import serialise_analysis_outcome
from .assessment import assess_run
from .config import configured_path_patterns, load_repo_config_with_diagnostics, path_matches_patterns
from .coverage import coverage_status_for as coverage_status_for
from .coverage import load_coverage_result
from .files import filter_files, inventory_project, is_source_file, is_test_file, read_text, rel, resolve_repo_root
from .grading import build_test_reference_index as build_test_reference_index
from .grading import find_test_references as find_test_references
from .models import AnalysisOutcome, AnalysisRun, Diagnostic, ProjectInventory, RepoConfig
from .models import CoverageIndex as CoverageIndex
from .models import FunctionInfo as FunctionInfo
from .source_parser import collect_functions
from .test_files import collect_tests


def analyse_repo(repo: Path, coverage_xml: Path | None = None) -> dict[str, Any]:
    """Analyse one repository through the plugin's canonical evidence seam."""
    root = resolve_repo_root(repo)
    inventory = inventory_project(root)
    repo_config, config_diagnostics = load_repo_config_with_diagnostics(root)
    files, excluded_files = apply_repo_config(inventory.files, root, repo_config)
    source_files = filter_files(files, lambda path: is_source_file(path, root))
    test_files = filter_files(files, lambda path: is_test_file(path, root))
    texts, read_diagnostics, read_failed_paths = load_analysis_texts(files, root)
    prepared_files, adapter_failures, adapter_runtime = prepare_analysis_files(
        source_files,
        test_files,
        texts,
        read_failed_paths,
        root,
    )
    analysed_source = [path for path in source_files if path in prepared_files]
    analysed_tests = [path for path in test_files if path in prepared_files]
    source_functions = collect_functions(analysed_source, prepared_files)
    tests = collect_tests(analysed_tests, prepared_files)
    coverage = load_coverage_result(coverage_xml, root)
    diagnostics = contract_diagnostics(root, inventory, config_diagnostics, read_diagnostics, coverage.diagnostic)
    diagnostics.extend(adapter_failures)
    attempted_paths = {*source_files, *test_files}
    read_failures = [
        item
        for item in read_diagnostics
        if item.code == "source-unreadable" and root / (item.path or "") in attempted_paths
    ]
    analysis_failures = [*read_failures, *adapter_failures]
    run = AnalysisRun(
        root=root,
        inventory=inventory,
        repo_config=repo_config,
        excluded_files=excluded_files,
        attempted_source_files=source_files,
        attempted_test_files=test_files,
        source_files=analysed_source,
        test_files=analysed_tests,
        texts=texts,
        prepared_files=prepared_files,
        adapter_runtime=adapter_runtime,
        analysis_failures=analysis_failures,
        diagnostics=diagnostics,
        coverage=coverage,
        coverage_xml=coverage_xml,
        source_functions=source_functions,
        tests=tests,
    )
    return serialise_analysis_outcome(AnalysisOutcome(run=run, assessment=assess_run(run)))


def apply_repo_config(files: list[Path], root: Path, config: RepoConfig) -> tuple[list[Path], list[Path]]:
    patterns = configured_path_patterns(config)
    excluded = [path for path in files if path_matches_patterns(path, root, patterns)]
    return [path for path in files if path not in set(excluded)], excluded


def load_analysis_texts(
    paths: list[Path],
    root: Path,
) -> tuple[dict[Path, str], list[Diagnostic], set[Path]]:
    texts: dict[Path, str] = {}
    diagnostics: list[Diagnostic] = []
    failed_paths: set[Path] = set()
    for path in sorted(paths):
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            texts[path] = read_text(path)
            diagnostics.append(warning("source-decode-replaced", path, root, "Invalid UTF-8 bytes were ignored before parsing."))
        except OSError as exc:
            failed_paths.add(path)
            diagnostics.append(warning("source-unreadable", path, root, f"File could not be read: {exc}"))
    return texts, diagnostics, failed_paths


def contract_diagnostics(
    root: Path,
    inventory: ProjectInventory,
    config_diagnostics: list[Diagnostic],
    read_diagnostics: list[Diagnostic],
    coverage_diagnostic: Diagnostic | None,
) -> list[Diagnostic]:
    diagnostics = [normalise_diagnostic(item, root) for item in config_diagnostics]
    diagnostics.extend(read_diagnostics)
    if inventory.truncated:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="inventory-truncated",
                message="Repository traversal reached the configured file limit.",
            )
        )
    if inventory.unsupported_code_files:
        examples = ", ".join(rel(path, root) for path in inventory.unsupported_code_files[:5])
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="unsupported-language-files",
                message=f"Unsupported code files were not analysed ({len(inventory.unsupported_code_files)}): {examples}",
            )
        )
    for path in inventory.oversized_files:
        diagnostics.append(warning("source-too-large", path, root, "Supported file exceeded the per-file byte limit."))
    for path in inventory.unreadable_files:
        diagnostics.append(warning("source-unreadable", path, root, "Supported file metadata could not be read."))
    for path in inventory.symlink_files:
        diagnostics.append(warning("source-symlink-skipped", path, root, "Symlink target was not followed during bounded repository analysis."))
    for error in inventory.traversal_errors:
        path = Path(error.path) if error.path else root
        diagnostics.append(warning("inventory-traversal-failed", path, root, error.message))
    if coverage_diagnostic:
        diagnostics.append(normalise_diagnostic(coverage_diagnostic, root))
    return diagnostics


def normalise_diagnostic(item: Diagnostic, root: Path) -> Diagnostic:
    path = rel(Path(item.path), root) if item.path else None
    return Diagnostic(severity=item.severity, code=item.code, path=path, message=item.message)


def warning(code: str, path: Path, root: Path, message: str) -> Diagnostic:
    return Diagnostic(severity="warning", code=code, path=rel(path, root), message=message)
