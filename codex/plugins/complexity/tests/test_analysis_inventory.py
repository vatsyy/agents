from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = PLUGIN_ROOT / "scripts" / "complexity"
sys.path.insert(0, str(SCRIPT_ROOT))

from analysis import AnalysisRequest, analyse


class AnalysisInventoryTests(unittest.TestCase):
    def test_external_child_symlink_is_not_reported_as_in_scope(self) -> None:
        with TemporaryDirectory(prefix="complexity scope ") as tmp:
            base = Path(tmp)
            root = base / "requested root"
            external = base / "external source"
            root.mkdir()
            external.mkdir()
            (root / "inside.py").write_text(
                "def inside():\n    return 1\n", encoding="utf-8"
            )
            outside = external / "outside.py"
            outside.write_text("def outside():\n    return 2\n", encoding="utf-8")
            self.make_symlink(root / "external alias.py", outside)

            outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.discovered_files, 1)
        self.assertEqual(outcome.coverage.skipped_files, 1)
        self.assertEqual(outcome.coverage.failed_files, 0)
        self.assertEqual([item.path for item in outcome.metrics], ["inside.py"])
        self.assertFalse(any("external alias.py" in item.path for item in outcome.metrics))
        skip_diagnostics = [
            item for item in outcome.diagnostics if item.stage == "inventory-skip"
        ]
        self.assertEqual(len(skip_diagnostics), 1)
        self.assertEqual(skip_diagnostics[0].reason, "skipped discovered file symlink")

    def test_in_tree_file_symlink_is_skipped_without_alias_evidence(self) -> None:
        with TemporaryDirectory(prefix="complexity scope ") as tmp:
            root = Path(tmp) / "requested root"
            root.mkdir()
            source = root / "inside.py"
            source.write_text("def inside():\n    return 1\n", encoding="utf-8")
            self.make_symlink(root / "inside alias.py", source)

            resolved_paths: list[Path] = []
            original_resolve = Path.resolve

            def record_resolve(path: Path, *args: object, **kwargs: object) -> Path:
                resolved_paths.append(path)
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", new=record_resolve):
                outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.discovered_files, 1)
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.skipped_files, 1)
        self.assertEqual([item.path for item in outcome.metrics], ["inside.py"])
        self.assertFalse(any("inside alias.py" in item.path for item in outcome.metrics))
        self.assertFalse(any(path.name == "inside alias.py" for path in resolved_paths))
        skip_diagnostics = [
            item for item in outcome.diagnostics if item.stage == "inventory-skip"
        ]
        self.assertEqual(len(skip_diagnostics), 1)
        self.assertEqual(
            skip_diagnostics[0].path, str(root.resolve() / "inside alias.py")
        )
        self.assertEqual(skip_diagnostics[0].reason, "skipped discovered file symlink")

    def test_broken_and_non_regular_file_symlinks_are_skipped(self) -> None:
        with TemporaryDirectory(prefix="complexity scope ") as tmp:
            root = Path(tmp) / "requested root"
            root.mkdir()
            (root / "inside.py").write_text(
                "def inside():\n    return 1\n", encoding="utf-8"
            )
            self.make_symlink(root / "broken alias.py", root / "missing.py")
            pipe = root / "source pipe"
            try:
                os.mkfifo(pipe)
            except (AttributeError, OSError) as error:
                self.skipTest(f"named pipes unavailable on this platform: {error}")
            self.make_symlink(root / "pipe alias.py", pipe)

            outcome = analyse(AnalysisRequest(target=root))

        self.assertEqual(outcome.status, "partial")
        self.assertEqual(outcome.coverage.discovered_files, 1)
        self.assertEqual(outcome.coverage.analysed_files, 1)
        self.assertEqual(outcome.coverage.skipped_files, 2)
        self.assertEqual([item.path for item in outcome.metrics], ["inside.py"])
        skip_diagnostics = [
            item for item in outcome.diagnostics if item.stage == "inventory-skip"
        ]
        self.assertEqual(len(skip_diagnostics), 2)
        self.assertEqual(
            {item.path for item in skip_diagnostics},
            {
                str(root.resolve() / "broken alias.py"),
                str(root.resolve() / "pipe alias.py"),
            },
        )
        self.assertTrue(
            all(item.reason == "skipped discovered file symlink" for item in skip_diagnostics)
        )

    def test_excluded_directory_is_not_counted_as_discovered_or_skipped(self) -> None:
        with TemporaryDirectory(prefix="complexity scope ") as tmp:
            root = Path(tmp) / "requested root"
            excluded = root / "excluded files"
            root.mkdir()
            excluded.mkdir()
            (root / "inside.py").write_text(
                "def inside():\n    return 1\n", encoding="utf-8"
            )
            (excluded / "ignored.py").write_text(
                "def ignored():\n    return 2\n", encoding="utf-8"
            )

            outcome = analyse(
                AnalysisRequest(
                    target=root,
                    excludes=frozenset({"excluded files"}),
                )
            )

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.coverage.discovered_files, 1)
        self.assertEqual(outcome.coverage.skipped_files, 0)
        self.assertEqual([item.path for item in outcome.metrics], ["inside.py"])
        self.assertFalse(any("ignored.py" in item.path for item in outcome.metrics))

    def test_named_symlink_file_keeps_explicit_resolved_target_semantics(self) -> None:
        with TemporaryDirectory(prefix="complexity scope ") as tmp:
            base = Path(tmp)
            requested = base / "requested root"
            external = base / "external source"
            requested.mkdir()
            external.mkdir()
            target = external / "outside.py"
            target.write_text("def outside():\n    return 1\n", encoding="utf-8")
            named_link = requested / "named alias.py"
            self.make_symlink(named_link, target)

            outcome = analyse(AnalysisRequest(target=named_link))

        self.assertEqual(outcome.status, "complete")
        self.assertEqual(outcome.target_kind, "file")
        self.assertEqual(outcome.target, str(target.resolve()))
        self.assertEqual(outcome.coverage.discovered_files, 1)
        self.assertEqual(outcome.coverage.skipped_files, 0)
        self.assertEqual([item.path for item in outcome.metrics], ["outside.py"])

    def make_symlink(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable on this platform: {error}")


if __name__ == "__main__":
    unittest.main()
