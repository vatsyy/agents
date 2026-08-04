from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Diagnostic, RepoConfig


CONFIG_NAMES = (".test-engineering.json", "test-engineering.json")


def load_repo_config(root: Path) -> RepoConfig:
    config, _ = load_repo_config_with_diagnostics(root)
    return config


def load_repo_config_with_diagnostics(root: Path) -> tuple[RepoConfig, list[Diagnostic]]:
    path = first_existing_config(root)
    if path is None:
        return empty_repo_config(), []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return empty_repo_config(), [diagnostic("config-invalid", path, f"Configuration was ignored: {exc}")]
    if not isinstance(payload, dict):
        return empty_repo_config(), [diagnostic("config-invalid", path, "Configuration root must be a JSON object.")]
    diagnostics = validate_repo_config(path, payload)
    return normalise_repo_config(payload), diagnostics


def diagnostic(code: str, path: Path, message: str) -> Diagnostic:
    return Diagnostic(severity="warning", code=code, path=str(path), message=message)


def validate_repo_config(path: Path, payload: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for key in ("ignore_path_contains", "generated_path_contains"):
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            diagnostics.append(diagnostic("config-invalid-field", path, f"{key} must be a list of non-empty strings."))
    return diagnostics


def first_existing_config(root: Path) -> Path | None:
    for name in CONFIG_NAMES:
        path = root / name
        if path.exists():
            return path
    return None


def read_json_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def empty_repo_config() -> RepoConfig:
    return RepoConfig()


def normalise_repo_config(payload: dict[str, Any]) -> RepoConfig:
    return RepoConfig(
        ignore_path_contains=tuple(string_list(payload.get("ignore_path_contains"))),
        generated_path_contains=tuple(string_list(payload.get("generated_path_contains"))),
    )


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def filter_configured_files(files: list[Path], root: Path, config: RepoConfig) -> list[Path]:
    patterns = configured_path_patterns(config)
    return [path for path in files if not path_matches_patterns(path, root, patterns)]


def configured_path_patterns(config: RepoConfig) -> list[str]:
    return [*config.ignore_path_contains, *config.generated_path_contains]


def path_matches_patterns(path: Path, root: Path, patterns: list[str]) -> bool:
    relative = relative_text(path, root)
    return any(pattern in relative for pattern in patterns)


def relative_text(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)
