from __future__ import annotations

import re


SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}
JS_TEST_SUFFIXES = {".js", ".jsx", ".ts", ".tsx"}
PYTHON_SUFFIX = ".py"
CONFIG_NAMES = {"package.json", "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg", "hooks.py"}
TEST_DIR_NAMES = {"tests", "test", "__tests__"}
IGNORED_PARTS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
}
MAX_TEXT_BYTES = 2_000_000
MAX_PROJECT_FILES = 50_000
UNSUPPORTED_CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".kt",
    ".php",
    ".rb",
    ".rs",
    ".scala",
    ".svelte",
    ".swift",
    ".vue",
}
COVERAGE_SCORE = {"covered": 25, "partial": 10}
WORD_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
JS_TEST_RE = re.compile(r"\b(?:it|test)\s*(?:\.\w+)?\s*\(\s*(['\"])(.*?)\1", re.MULTILINE)
JS_ASSERTION_RE = re.compile(r"\b(?:expect|assert)\s*(?:\.|\()")
JS_FUNCTION_RE = re.compile(
    r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("
    r"|\b(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*"
    r"(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][A-Za-z0-9_$]*\s*=>)"
)
PYTHON_TEST_LIFECYCLE_NAMES = {"setUp", "tearDown", "setUpClass", "tearDownClass", "setup_method", "teardown_method"}
PYTHON_FRAMEWORK_TEST_BASES = {"CustomFrameworkTestCase", "FrameworkTestCase", "FrappeTestCase"}
ERROR_ASSERTION_TERMS = {"raises", "raise", "throw", "reject", "exception", "error"}
BOUNDARY_ASSERTION_TERMS = {"none", "null", "empty", "zero", "negative", "min", "max", "edge", "boundary", "0", "-1"}
STATE_ASSERTION_TERMS = {"status", "state", "saved", "updated", "created", "deleted", "changed"}
PERSISTENCE_ASSERTION_TERMS = {"save", "commit", "rollback", "insert", "delete", "db", "database", "store"}
PERMISSION_ASSERTION_TERMS = {"permission", "auth", "role", "allowed", "denied", "forbidden", "unauthorized"}
EXTERNAL_ASSERTION_TERMS = {"mock", "patch", "request", "response", "client", "api", "http", "fetch", "axios"}
MOCK_TERMS = {"mock", "patch", "monkeypatch", "MagicMock", "vi.fn", "jest.fn"}
SCOPED_EVIDENCE = "scoped-evidence-only"
SUCCESSFULLY_ANALYSED_FILES = "successfully-analysed-files-only"
UNAVAILABLE = "unavailable"
