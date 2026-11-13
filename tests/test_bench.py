import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "benchmarks" / "bench.py"
)

HIDDEN_TEST = """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mod import value


def test_value():
    assert value() == 2
"""


def load_bench_module():
    spec = importlib.util.spec_from_file_location("bench", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BenchTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self._git("init", "-q")
        (self.repo / "src").mkdir()
        self._write("src/mod.py", "def value():\n    return 1\n")
        self._commit("feat: add value")
        self.base = self._head()
        self._write("src/mod.py", "def value():\n    return 2\n")
        self._write("tests/test_mod.py", HIDDEN_TEST)
        self._commit("fix: return two")
        self.commit = self._head()
        self.case = {
            "id": "fixture",
            "repo": str(self.repo),
            "commit": self.commit,
            "size": "small",
            "language": "python",
            "task": "Make value return two. Add or update tests for the new behavior.",
            "hidden_tests": ["tests/test_mod.py"],
            "setup": [],
            "exclude": [],
            "test_command": (
                "python3 -m pytest -q -p no:cacheprovider tests/test_mod.py "
                "--junitxml .bench-junit/hidden.xml"
            ),
            "suite_command": None,
            "junit_globs": [".bench-junit/*.xml"],
            "timeout_min": 2,
        }
        self.bench_root = self.root / "workspaces"
        self.results_root = self.root / "results"
        self.env = patch.dict(
            os.environ,
            {
                "SHIPPY_BENCH_ROOT": str(self.bench_root),
                "SHIPPY_BENCH_RESULTS": str(self.results_root),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _write(self, relative, text):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _commit(self, message):
        self._git("add", "-A")
        self._git(
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "-q",
            "-m",
            message,
        )

    def _head(self):
        return self._git("rev-parse", "HEAD")


class TestRunOne(BenchTestCase):
    def test_01_oracle_resolves_and_records(self):
        record = self.bench.run_one(
            self.case, "oracle", 1, "run1", {"keep_workspace": False}
        )

        self.assertEqual(record["status"], "ok")
        self.assertIsNone(record["error"])
        self.assertTrue(record["grade"]["resolved"])
        self.assertEqual(record["grade"]["hidden"]["tests"], 1)
        self.assertEqual(record["grade"]["hidden"]["failures"], 0)
        self.assertGreaterEqual(record["grade"]["diff"]["files"], 1)
        self.assertFalse(record["grade"]["diff"]["empty"])
        self.assertEqual(record["wall_s"], 0.0)
        self.assertIsNone(record["judge"])

        out = self.results_root / "run1" / "fixture__oracle__1"
        self.assertTrue((out / "record.json").is_file())
        self.assertTrue((out / "diff.patch").is_file())
        self.assertFalse((self.bench_root / "run1" / "fixture__oracle__1").exists())

        saved = json.loads((out / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["case"], "fixture")
        self.assertEqual(saved["arm"], "oracle")

    def test_02_null_does_not_resolve(self):
        record = self.bench.run_one(
            self.case, "null", 1, "run2", {"keep_workspace": False}
        )

        self.assertEqual(record["status"], "ok")
        self.assertFalse(record["grade"]["resolved"])
        self.assertTrue(record["grade"]["diff"]["empty"])
        self.assertFalse(record["grade"]["hidden"]["green"])


class TestWorkspace(BenchTestCase):
    def test_03_prepare_workspace_is_one_clean_commit(self):
        ws = self.bench_root / "prep" / "ws"
        base_sha = self.bench.prepare_workspace(self.case, ws)

        self.assertEqual(self.bench.git(["rev-list", "--all", "--count"], ws), "1")
        self.assertEqual(len(base_sha), 40)
        self.assertFalse((ws / "tests" / "test_mod.py").exists())
        self.assertTrue((ws / "src" / "mod.py").is_file())
        excludes = (ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn(".bench-junit/", excludes)

        with self.assertRaises(FileExistsError):
            self.bench.prepare_workspace(self.case, ws)
        shutil.rmtree(ws, ignore_errors=True)


class TestCli(BenchTestCase):
    def test_04_unknown_arm_exits_two(self):
        self.assertEqual(
            self.bench.main(["run", "--cases", "all", "--arms", "bogus"]), 2
        )


class TestParseJunit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _xml(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_sums_child_suites_when_root_has_no_counts(self):
        path = self._xml(
            "many.xml",
            '<testsuites>\n'
            '  <testsuite name="a" tests="2" failures="1" errors="0" skipped="0"/>\n'
            '  <testsuite name="b" tests="3" failures="0" errors="1" skipped="2"/>\n'
            "</testsuites>\n",
        )
        self.assertEqual(
            self.bench.parse_junit([path]),
            {
                "tests": 5,
                "failures": 1,
                "errors": 1,
                "skipped": 2,
                "parse_errors": 0,
            },
        )

    def test_accepts_bare_testsuite_root(self):
        path = self._xml(
            "one.xml",
            '<testsuite name="a" tests="4" failures="0" errors="0" skipped="1"/>\n',
        )
        counts = self.bench.parse_junit([path])
        self.assertEqual(counts["tests"], 4)
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(counts["parse_errors"], 0)

    def test_malformed_file_counts_a_parse_error(self):
        path = self._xml("bad.xml", "<testsuites><testsuite")
        counts = self.bench.parse_junit([path])
        self.assertEqual(counts["parse_errors"], 1)
        self.assertEqual(counts["tests"], 0)

    def test_empty_list_is_zero(self):
        self.assertEqual(
            self.bench.parse_junit([]),
            {
                "tests": 0,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "parse_errors": 0,
            },
        )


class TestHygiene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def test_flags_subject_and_attribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

            def commit(message):
                (repo / "file.txt").write_text(message, encoding="utf-8")
                subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.name=test",
                        "-c",
                        "user.email=test@localhost",
                        "commit",
                        "-q",
                        "-m",
                        message,
                    ],
                    cwd=repo,
                    check=True,
                )

            commit("chore: base")
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            commit("feat: x")
            commit("Update stuff\n\nCo-authored-by: A <a@b>")

            result = self.bench.hygiene(repo, base)

            self.assertEqual(result["commits"], ["feat: x", "Update stuff"])
            self.assertEqual(result["non_conventional"], ["Update stuff"])
            self.assertEqual(result["attribution"], ["Update stuff"])
            self.assertEqual(result["uncommitted"], 0)


class TestLoadCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def test_missing_required_key_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(
                json.dumps(
                    {
                        "id": "broken",
                        "repo": "~/somewhere",
                        "commit": "0" * 40,
                        "size": "small",
                        "language": "python",
                        "hidden_tests": [],
                        "setup": [],
                        "exclude": [],
                        "test_command": "true",
                        "junit_globs": [],
                        "timeout_min": 1,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as caught:
                self.bench.load_case(str(path))
            self.assertEqual(str(caught.exception), "broken: missing key task")


if __name__ == "__main__":
    unittest.main()
