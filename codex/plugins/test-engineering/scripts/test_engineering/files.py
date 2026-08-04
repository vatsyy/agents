from __future__ import annotations

import os
from pathlib import Path

from .constants import (
    CONFIG_NAMES,
    IGNORED_PARTS,
    JS_TEST_SUFFIXES,
    MAX_TEXT_BYTES,
    MAX_PROJECT_FILES,
    PYTHON_SUFFIX,
    SOURCE_SUFFIXES,
    TEST_DIR_NAMES,
    UNSUPPORTED_CODE_SUFFIXES,
)
from .models import ProjectInventory, TraversalError


def resolve_repo_root(repo: Path) -> Path:
    root = repo.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {root}")
    return root


def iter_project_files(root: Path) -> list[Path]:
    return inventory_project(root).files


def inventory_project(root: Path, max_files: int = MAX_PROJECT_FILES) -> ProjectInventory:
    inventory = ProjectInventory()
    for directory, directory_names, file_names in os.walk(root, onerror=lambda error: record_traversal_error(inventory, error)):
        directory_names[:] = prune_directories(Path(directory), directory_names, inventory)
        for name in sorted(file_names):
            if inventory.discovered_file_count >= max_files:
                inventory.truncated = True
                return inventory
            inventory.discovered_file_count += 1
            inspect_inventory_file(inventory, Path(directory) / name)
    inventory.files.sort()
    inventory.unsupported_code_files.sort()
    inventory.oversized_files.sort()
    inventory.unreadable_files.sort()
    inventory.symlink_files.sort()
    inventory.traversal_errors.sort(key=lambda item: item.path)
    return inventory


def record_traversal_error(inventory: ProjectInventory, error: OSError) -> None:
    inventory.traversal_errors.append(TraversalError(path=str(error.filename or ""), message=str(error)))


def prune_directories(directory: Path, names: list[str], inventory: ProjectInventory) -> list[str]:
    kept: list[str] = []
    for name in sorted(names):
        if name in IGNORED_PARTS or (directory / name).is_symlink():
            inventory.excluded_directory_count += 1
        else:
            kept.append(name)
    return kept


def inspect_inventory_file(inventory: ProjectInventory, path: Path) -> None:
    if path.is_symlink():
        if has_supported_name(path) or path.suffix.lower() in UNSUPPORTED_CODE_SUFFIXES:
            inventory.symlink_files.append(path)
        return
    if path.suffix.lower() in UNSUPPORTED_CODE_SUFFIXES:
        inventory.unsupported_code_files.append(path)
    if not has_supported_name(path):
        return
    if path.suffix in SOURCE_SUFFIXES:
        inventory.supported_candidate_count += 1
    try:
        size = path.stat().st_size
    except OSError:
        inventory.unreadable_files.append(path)
        return
    if size > MAX_TEXT_BYTES:
        inventory.oversized_files.append(path)
        return
    if path.is_file():
        inventory.files.append(path)


def add_project_file(files: list[Path], path: Path) -> None:
    if is_project_file(path):
        files.append(path)


def is_project_file(path: Path) -> bool:
    if has_ignored_part(path):
        return False
    if not path.is_file():
        return False
    if not has_supported_name(path):
        return False
    return is_small_enough(path)


def has_ignored_part(path: Path) -> bool:
    return bool(IGNORED_PARTS.intersection(path.parts))


def has_supported_name(path: Path) -> bool:
    return path.suffix in SOURCE_SUFFIXES or looks_like_config(path)


def is_small_enough(path: Path) -> bool:
    try:
        return path.stat().st_size <= MAX_TEXT_BYTES
    except OSError:
        return False


def looks_like_config(path: Path) -> bool:
    return path.name in CONFIG_NAMES


def is_test_file(path: Path, root: Path | None = None) -> bool:
    if path.suffix == PYTHON_SUFFIX:
        return is_python_test_file(path, root)
    if path.suffix in JS_TEST_SUFFIXES:
        return is_javascript_test_file(path, root)
    return has_test_directory(path, root)


def is_python_test_file(path: Path, root: Path | None = None) -> bool:
    return is_python_test_name(path) or has_test_directory(path, root)


def is_python_test_name(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def is_javascript_test_file(path: Path, root: Path | None = None) -> bool:
    return is_javascript_test_name(path) or has_test_directory(path, root)


def is_javascript_test_name(path: Path) -> bool:
    return ".test." in path.name or ".spec." in path.name or path.stem.startswith("test_")


def has_test_directory(path: Path, root: Path | None = None) -> bool:
    return bool(TEST_DIR_NAMES.intersection(relative_parent_parts(path, root)))


def relative_parent_parts(path: Path, root: Path | None) -> tuple[str, ...]:
    if root is None:
        return path.parent.parts
    try:
        return path.relative_to(root).parent.parts
    except ValueError:
        return path.parent.parts


def is_source_file(path: Path, root: Path | None = None) -> bool:
    return path.suffix in SOURCE_SUFFIXES and not is_test_file(path, root)


def filter_files(files: list[Path], predicate) -> list[Path]:
    return [path for path in files if predicate(path)]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_test_texts(test_files: list[Path]) -> dict[Path, str]:
    return {path: read_text(path) for path in test_files}


def line_count(text: str) -> int:
    return len(text.splitlines())


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)
