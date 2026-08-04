from __future__ import annotations

import re
from pathlib import Path

from .constants import JS_TEST_SUFFIXES, PYTHON_FRAMEWORK_TEST_BASES, PYTHON_SUFFIX
from .files import read_text


def detect_frameworks(
    root: Path,
    test_files: list[Path],
    project_files: list[Path] | None = None,
    texts: dict[Path, str] | None = None,
) -> list[str]:
    hints = framework_hints(root, test_files, project_files, texts)
    return sorted(hints) if hints else ["unknown"]


def framework_hints(
    root: Path,
    test_files: list[Path],
    project_files: list[Path] | None = None,
    texts: dict[Path, str] | None = None,
) -> set[str]:
    hints: set[str] = set()
    add_hint(hints, "pytest/python", has_python_tests(test_files))
    add_hint(hints, "pytest", has_pytest_config(root))
    add_hint(hints, "pytest", pyproject_mentions_pytest(root, texts))
    add_hint(hints, "unittest/python", mentions_unittest(test_files, texts))
    add_hint(hints, "framework-adapter/python", has_framework_adapter_clues(root, test_files, project_files, texts))
    add_javascript_hints(hints, root, test_files, texts)
    return hints


def add_hint(hints: set[str], name: str, condition: bool) -> None:
    if condition:
        hints.add(name)


def has_python_tests(test_files: list[Path]) -> bool:
    return any(path.suffix == PYTHON_SUFFIX for path in test_files)


def has_pytest_config(root: Path) -> bool:
    return any((root / name).exists() for name in ("pytest.ini", "tox.ini"))


def pyproject_mentions_pytest(root: Path, texts: dict[Path, str] | None = None) -> bool:
    pyproject = root / "pyproject.toml"
    return pyproject.exists() and "pytest" in cached_text(pyproject, texts).lower()


def has_javascript_tests(test_files: list[Path]) -> bool:
    return any(path.suffix in JS_TEST_SUFFIXES for path in test_files)


def mentions_unittest(test_files: list[Path], texts: dict[Path, str] | None = None) -> bool:
    return any(mentions_unittest_text(cached_text(path, texts)) for path in python_test_files(test_files))


def mentions_unittest_text(text: str) -> bool:
    return "unittest" in text or "unittest.TestCase" in text


def python_test_files(test_files: list[Path]) -> list[Path]:
    return [path for path in test_files if path.suffix == PYTHON_SUFFIX]


def has_framework_adapter_clues(
    root: Path,
    test_files: list[Path],
    project_files: list[Path] | None = None,
    texts: dict[Path, str] | None = None,
) -> bool:
    return has_framework_hooks(root, project_files) or mentions_framework_base(test_files, texts)


def has_framework_hooks(root: Path, project_files: list[Path] | None = None) -> bool:
    if project_files is not None:
        return any(path.name == "hooks.py" for path in project_files)
    return (root / "hooks.py").exists() or any(path.name == "hooks.py" for path in root.rglob("hooks.py"))


def mentions_framework_base(test_files: list[Path], texts: dict[Path, str] | None = None) -> bool:
    return any(mentions_any(cached_text(path, texts), PYTHON_FRAMEWORK_TEST_BASES) for path in python_test_files(test_files))


def mentions_any(text: str, values: set[str]) -> bool:
    return any(value in text for value in values)


def add_javascript_hints(
    hints: set[str],
    root: Path,
    test_files: list[Path],
    texts: dict[Path, str] | None = None,
) -> None:
    add_hint(hints, "javascript", has_javascript_tests(test_files))
    package_text = package_json_text(root, texts)
    test_texts = javascript_test_texts(test_files, texts)
    add_hint(hints, "jest/javascript", mentions_jest(package_text, test_texts))
    add_hint(hints, "vitest/javascript", mentions_vitest(package_text, test_texts))


def package_json_text(root: Path, texts: dict[Path, str] | None = None) -> str:
    package_json = root / "package.json"
    return cached_text(package_json, texts) if package_json.exists() else ""


def javascript_test_texts(test_files: list[Path], texts: dict[Path, str] | None = None) -> list[str]:
    return [cached_text(path, texts).lower() for path in test_files if path.suffix in JS_TEST_SUFFIXES]


def cached_text(path: Path, texts: dict[Path, str] | None) -> str:
    if texts is not None and path in texts:
        return texts[path]
    return read_text(path)


def mentions_jest(package_text: str, test_texts: list[str]) -> bool:
    return "jest" in package_text.lower() or any(has_jest_text(text) for text in test_texts)


def mentions_vitest(package_text: str, test_texts: list[str]) -> bool:
    return "vitest" in package_text.lower() or any("vitest" in text for text in test_texts)


def has_jest_text(text: str) -> bool:
    if "vitest" in text:
        return False
    return "jest" in text or bool(re.search(r"\b(?:test|it)\s*\(", text) and re.search(r"\bexpect\s*\(", text))
