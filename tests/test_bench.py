import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
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

FAKE_T3 = r'''#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
stdin = sys.stdin.read()
with open(os.environ["FAKE_T3_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "stdin": stdin}) + "\n")


def emit(payload, code=0):
    print(json.dumps(payload))
    raise SystemExit(code)


mode = os.environ.get("FAKE_T3_MODE", "ok")
if argv[:2] == ["project", "add"]:
    print("Added project 00000000-0000-0000-0000-000000000000")
    raise SystemExit(0)
if argv[:2] == ["thread", "show"]:
    print(json.dumps({"thread": {"id": "t1"}, "messages": []}))
    raise SystemExit(0)
if argv[:1] == ["thread"] and len(argv) > 1 and argv[1] in ("start", "send"):
    if mode == "always-two":
        emit({"threadId": "t1", "runId": "r", "status": "waiting", "reply": "?",
              "error": None}, 2)
    if mode == "fail":
        emit({"threadId": "t1", "runId": "r", "status": "failed", "reply": None,
              "error": "boom"}, 1)
    if mode == "nudge-once" and argv[1] == "start":
        emit({"threadId": "t1", "runId": "r", "status": "waiting", "reply": "?",
              "error": None}, 2)
    emit({"threadId": "t1", "runId": "r", "status": "completed", "reply": "done",
          "error": None}, 0)
print("unexpected fake t3 call", file=sys.stderr)
raise SystemExit(1)
'''

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
sys.stdin.read()
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv}) + "\n")
if os.environ.get("FAKE_CLAUDE_MODE", "ok") == "fail":
    print("judge exploded", file=sys.stderr)
    raise SystemExit(1)
result = (
    "Here: {\"correctness\": 4, \"completeness\": 4, \"scope\": 5, "
    "\"maintainability\": 4, \"tests\": 3, \"overall\": 8, \"notes\": \"ok\"}"
)
print(json.dumps({"result": result, "total_cost_usd": 0.05}))
'''


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


class FakeBinaries(unittest.TestCase):
    """Shared fake ``t3``/``claude`` binaries; no network or real agents."""

    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.t3 = self._script("fake_t3.py", FAKE_T3)
        self.claude = self._script("fake_claude.py", FAKE_CLAUDE)
        self.t3_log = self.root / "t3.log"
        self.claude_log = self.root / "claude.log"
        self.env = patch.dict(
            os.environ,
            {
                "SHIPPY_BENCH_T3": str(self.t3),
                "SHIPPY_BENCH_CLAUDE": str(self.claude),
                "FAKE_T3_LOG": str(self.t3_log),
                "FAKE_CLAUDE_LOG": str(self.claude_log),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("FAKE_T3_MODE", None)
        os.environ.pop("FAKE_CLAUDE_MODE", None)
        self.addCleanup(os.environ.pop, "FAKE_T3_MODE", None)
        self.addCleanup(os.environ.pop, "FAKE_CLAUDE_MODE", None)

    def _script(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
        return path

    def _calls(self, log):
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestTurns(FakeBinaries):
    def test_plan_build_arm_has_two_exact_turns(self):
        task = "Fix the retake counter."
        turns = self.bench.build_turns("claude-base", task)

        self.assertEqual(
            turns,
            [
                task + "\n\nWrite an implementation plan only; do not edit files yet.",
                "The plan is approved. Implement it, run the relevant tests, and "
                "commit with a Conventional Commit message. "
                "Benchmark run: no human is available. Treat the plan as approved "
                "(Approval: auto, Commits: per stage); do not ask questions; take "
                "your recommended option for every decision and note it. Do not push.",
            ],
        )
        self.assertEqual(self.bench.AGENT_ARMS["claude-base"]["style"], "plan-build")
        self.assertEqual(self.bench.AGENT_ARMS["codex-base"]["model"], "gpt-6-astra")

    def test_skill_arm_has_one_prefixed_turn(self):
        turns = self.bench.build_turns("shippy-t3", "Do the thing.")
        self.assertEqual(len(turns), 1)
        self.assertTrue(turns[0].startswith("$shippy-t3 Do the thing."))
        self.assertIn(self.bench.AUTO_CLAUSE, turns[0])


class TestClaudeUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def test_dedupes_filters_and_splits_cache_writes(self):
        base = datetime(2026, 11, 13, 3, 0, 0, tzinfo=timezone.utc).timestamp()
        start, end = base, base + 600

        def stamp(offset):
            return (
                datetime.fromtimestamp(base + offset, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "ws"
            ws.mkdir()
            projects = root / "projects"
            slug = projects / self.bench.claude_slug(ws)
            subagents = slug / "s1" / "subagents"
            subagents.mkdir(parents=True)

            lines = [
                {
                    "type": "assistant",
                    "timestamp": stamp(10),
                    "message": {
                        "id": "m1",
                        "model": "claude-haiku-5-5",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 1,
                            "cache_read_input_tokens": 2,
                            "cache_creation_input_tokens": 100,
                            "cache_creation": {
                                "ephemeral_5m_input_tokens": 40,
                                "ephemeral_1h_input_tokens": 60,
                            },
                        },
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": stamp(20),
                    "message": {
                        "id": "m1",
                        "model": "claude-haiku-5-5",
                        "usage": {
                            "input_tokens": 20,
                            "output_tokens": 2,
                            "cache_read_input_tokens": 3,
                            "cache_creation_input_tokens": 100,
                            "cache_creation": {
                                "ephemeral_5m_input_tokens": 40,
                                "ephemeral_1h_input_tokens": 60,
                            },
                        },
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": stamp(25),
                    "message": {
                        "id": "synthetic",
                        "model": "<synthetic>",
                        "usage": {"input_tokens": 999, "output_tokens": 999},
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": stamp(30),
                    "message": {
                        "id": "m2",
                        "model": "claude-opus-5-5",
                        "usage": {
                            "input_tokens": 5,
                            "output_tokens": 5,
                            "cache_creation_input_tokens": 7,
                        },
                    },
                },
                {
                    "type": "assistant",
                    "timestamp": stamp(-100),
                    "message": {
                        "id": "m3",
                        "model": "claude-opus-5-5",
                        "usage": {"input_tokens": 777, "output_tokens": 777},
                    },
                },
                {
                    "type": "api-request-shape",
                    "timestamp": stamp(35),
                    "message": {"model": "claude-unrelated"},
                },
            ]
            (slug / "s1.jsonl").write_text(
                "\n".join([*(json.dumps(line) for line in lines), "{not json"]) + "\n",
                encoding="utf-8",
            )
            (subagents / "a.jsonl").write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": stamp(40),
                        "message": {
                            "id": "m4",
                            "model": "claude-opus-5-5",
                            "usage": {"input_tokens": 1, "output_tokens": 2},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ, {"SHIPPY_BENCH_CLAUDE_DIR": str(projects)}
            ):
                usage = self.bench.collect_claude_usage(ws, start, end)

            self.assertEqual(
                usage,
                {
                    "claude-haiku-5-5": {
                        "input": 20,
                        "output": 2,
                        "cache_read": 3,
                        "cache_write_5m": 40,
                        "cache_write_1h": 60,
                    },
                    "claude-opus-5-5": {
                        "input": 6,
                        "output": 7,
                        "cache_read": 0,
                        "cache_write_5m": 7,
                        "cache_write_1h": 0,
                    },
                },
            )


class TestCodexUsage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def test_matches_workspace_cwd_and_last_token_count(self):
        now = time.time()
        start, end = now - 60, now + 60
        stamp = (
            datetime.fromtimestamp(now, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ws = root / "ws"
            ws.mkdir()
            sessions = root / "sessions"
            sessions.mkdir()

            def rollout(name, cwd, tokens):
                lines = [
                    {
                        "type": "session_meta",
                        "timestamp": stamp,
                        "payload": {"cwd": str(cwd)},
                    },
                    {
                        "type": "turn_context",
                        "timestamp": stamp,
                        "payload": {"model": "gpt-6-astra"},
                    },
                    {
                        "type": "token_count",
                        "timestamp": stamp,
                        "payload": {
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": tokens[0],
                                    "cached_input_tokens": tokens[1],
                                    "output_tokens": tokens[2],
                                    "reasoning_output_tokens": 5,
                                }
                            }
                        },
                    },
                ]
                path = sessions / name
                path.write_text(
                    "\n".join(json.dumps(line) for line in lines) + "\n",
                    encoding="utf-8",
                )
                return path

            rollout("rollout-a.jsonl", ws, (1000, 800, 50))
            rollout("rollout-b.jsonl", root / "elsewhere", (9999, 9999, 9999))

            with patch.dict(
                os.environ, {"SHIPPY_BENCH_CODEX_DIR": str(sessions)}
            ):
                usage = self.bench.collect_codex_usage(ws, start, end)

            self.assertEqual(
                usage,
                {
                    "gpt-6-astra": {
                        "input": 200,
                        "cache_read": 800,
                        "output": 50,
                        "cache_write_5m": 0,
                        "cache_write_1h": 0,
                    }
                },
            )


class TestCost(FakeBinaries):
    def test_prices_and_null_models(self):
        prices = self.bench.load_prices()
        tokens = {
            "claude-opus-5-5": {
                "input": 1_000_000,
                "output": 100_000,
                "cache_read": 1_000_000,
                "cache_write_5m": 0,
                "cache_write_1h": 1_000_000,
            }
        }
        cost, complete = self.bench.cost_of(tokens, prices)
        self.assertAlmostEqual(cost, 14.2, places=6)
        self.assertTrue(complete)

        tokens["gpt-6-astra"] = {
            "input": 1_000_000,
            "output": 1_000_000,
            "cache_read": 0,
            "cache_write_5m": 0,
            "cache_write_1h": 0,
        }
        cost, complete = self.bench.cost_of(tokens, prices)
        self.assertAlmostEqual(cost, 14.2, places=6)
        self.assertFalse(complete)

    def test_no_usage_is_zero_and_complete(self):
        cost, complete = self.bench.cost_of({}, self.bench.load_prices())
        self.assertEqual(cost, 0.0)
        self.assertTrue(complete)


class TestDriveT3(FakeBinaries):
    def setUp(self):
        super().setUp()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.out = self.root / "out"
        self.out.mkdir()
        self.turns = self.bench.build_turns("claude-base", "Implement it.")

    def test_nudges_once_then_completes(self):
        os.environ["FAKE_T3_MODE"] = "nudge-once"
        result = self.bench.drive_t3(
            self.ws, "claude-base", self.turns, "bench title", 30, out=self.out
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["questions"], 1)
        self.assertEqual(result["thread_id"], "t1")
        self.assertEqual(result["error"], None)
        self.assertEqual(len(result["replies"]), 2)

        calls = self._calls(self.t3_log)
        message_calls = [
            call
            for call in calls
            if call["argv"][:1] == ["thread"]
            and len(call["argv"]) > 1
            and call["argv"][1] in ("start", "send")
        ]
        self.assertEqual(len(message_calls), 3)
        self.assertEqual(message_calls[0]["argv"][:2], ["thread", "start"])
        self.assertIn("claudeAgent", message_calls[0]["argv"])
        self.assertIn("claude-opus-5-5", message_calls[0]["argv"])
        self.assertEqual(message_calls[0]["stdin"], self.turns[0])
        self.assertEqual(message_calls[1]["argv"][:3], ["thread", "send", "t1"])
        self.assertEqual(message_calls[1]["stdin"], self.bench.NUDGE)
        self.assertEqual(message_calls[2]["stdin"], self.turns[1])
        self.assertTrue(
            any(call["argv"][:2] == ["thread", "show"] for call in calls)
        )
        self.assertTrue((self.out / "thread.json").is_file())

    def test_always_waiting_needs_input_after_two_nudges(self):
        os.environ["FAKE_T3_MODE"] = "always-two"
        result = self.bench.drive_t3(
            self.ws, "claude-base", self.turns, "bench title", 30, out=self.out
        )

        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["questions"], 3)
        self.assertEqual(result["thread_id"], "t1")
        nudges = [
            call
            for call in self._calls(self.t3_log)
            if call["stdin"] == self.bench.NUDGE
        ]
        self.assertEqual(len(nudges), 2)

    def test_exit_one_fails_with_error(self):
        os.environ["FAKE_T3_MODE"] = "fail"
        result = self.bench.drive_t3(
            self.ws, "claude-base", self.turns, "bench title", 30, out=self.out
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "boom")


class TestAgentRunOne(BenchTestCase):
    def setUp(self):
        super().setUp()
        self.t3 = self.root / "fake_t3.py"
        self.t3.write_text(FAKE_T3, encoding="utf-8")
        self.t3.chmod(0o755)
        self.claude = self.root / "fake_claude.py"
        self.claude.write_text(FAKE_CLAUDE, encoding="utf-8")
        self.claude.chmod(0o755)
        self.t3_log = self.root / "t3.log"
        empty_projects = self.root / "projects"
        empty_codex = self.root / "codex"
        empty_projects.mkdir()
        empty_codex.mkdir()
        self.fake_env = patch.dict(
            os.environ,
            {
                "SHIPPY_BENCH_T3": str(self.t3),
                "SHIPPY_BENCH_CLAUDE": str(self.claude),
                "FAKE_T3_LOG": str(self.t3_log),
                "SHIPPY_BENCH_CLAUDE_DIR": str(empty_projects),
                "SHIPPY_BENCH_CODEX_DIR": str(empty_codex),
            },
        )
        self.fake_env.start()
        self.addCleanup(self.fake_env.stop)

    def test_claude_base_run_records_and_keeps_slot(self):
        record = self.bench.run_one(
            self.case, "claude-base", 1, "run6", {"timeout_min": 2}
        )

        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["thread_id"], "t1")
        self.assertEqual(record["tokens_by_model"], {})
        self.assertEqual(record["cost_usd"], 0.0)
        self.assertTrue(record["cost_complete"])
        self.assertIsNone(record["judge"])
        self.assertEqual(record["judge_cost_usd"], 0.0)
        self.assertEqual(record["questions"], 0)

        slot = self.bench_root.resolve() / "slots" / "fixture__claude-base"
        self.assertEqual(record["workspace"], str(slot))
        self.assertTrue((slot / ".git").is_dir())
        out = self.results_root / "run6" / "fixture__claude-base__1"
        self.assertTrue((out / "record.json").is_file())
        saved = json.loads((out / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["arm"], "claude-base")
        self.assertEqual(saved["thread_id"], "t1")

        add_calls = [
            call
            for call in [
                json.loads(line)
                for line in self.t3_log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if call["argv"][:2] == ["project", "add"]
        ]
        self.assertEqual(len(add_calls), 1)
        self.assertIn(str(slot), add_calls[0]["argv"])

        again = self.bench.run_one(
            self.case, "claude-base", 1, "run6b", {"timeout_min": 2}
        )
        self.assertEqual(again["status"], "ok")
        self.assertTrue((slot / ".git").is_dir())


class TestJudge(FakeBinaries):
    def test_scores_are_parsed_and_tools_disabled(self):
        judge = self.bench.judge(self._case(), "reference diff", "candidate diff")

        self.assertEqual(judge["overall"], 8)
        self.assertEqual(judge["correctness"], 4)
        self.assertAlmostEqual(judge["cost_usd"], 0.05)
        self.assertEqual(judge["model"], "claude-sonnet-5-5")
        self.assertEqual(
            judge["truncated"], {"reference": False, "candidate": False}
        )

        calls = self._calls(self.claude_log)
        self.assertEqual(len(calls), 1)
        argv = calls[0]["argv"]
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertIn("claude-sonnet-5-5", argv)

    def test_empty_candidate_is_skipped(self):
        self.assertIsNone(self.bench.judge(self._case(), "reference", "   \n"))
        self.assertEqual(self._calls(self.claude_log), [])

    def test_failure_returns_error(self):
        os.environ["FAKE_CLAUDE_MODE"] = "fail"
        judge = self.bench.judge(self._case(), "reference", "candidate")
        self.assertIn("error", judge)
        self.assertIn("judge exploded", judge["error"])

    def _case(self):
        return {"id": "fixture", "task": "Make value return two."}


class TestMainCostGuard(BenchTestCase):
    def test_agent_arm_requires_max_cost(self):
        cases = self.root / "cases"
        cases.mkdir()
        (cases / "fixture.json").write_text(
            json.dumps(self.case), encoding="utf-8"
        )
        original = self.bench.CASES_DIR
        self.bench.CASES_DIR = cases
        try:
            code = self.bench.main(
                ["run", "--cases", "fixture", "--arms", "claude-base"]
            )
        finally:
            self.bench.CASES_DIR = original

        self.assertEqual(code, 2)
        self.assertFalse((self.results_root / "fixture").exists())


class TestSkillHash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bench = load_bench_module()

    def test_hash_tracks_files_and_ignores_pycache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skill"
            root.mkdir()
            (root / "SKILL.md").write_text("hello\n", encoding="utf-8")
            first = self.bench.skill_hash(root)
            self.assertIsNotNone(first)

            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_bytes(b"cache")
            self.assertEqual(self.bench.skill_hash(root), first)

            (root / "SKILL.md").write_text("changed\n", encoding="utf-8")
            self.assertNotEqual(self.bench.skill_hash(root), first)

        self.assertIsNone(self.bench.skill_hash(Path(tmp) / "missing"))


if __name__ == "__main__":
    unittest.main()
