#!/usr/bin/env python3
"""Replay benchmark: prepare a workspace from a source commit, drive arms, grade.

Stage 2 covers case loading, workspace preparation, grading and the free
control arms (``oracle`` and ``null``). Stage 3 adds the t3-driven agent arms,
usage and cost accounting, and the blind judge. Stage 4 adds the aggregate
``report`` command; ``benchmarks/README.md`` documents the method.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
CASES_DIR = BENCH_DIR / "cases"

REQUIRED_KEYS = (
    "id",
    "repo",
    "commit",
    "size",
    "language",
    "task",
    "hidden_tests",
    "setup",
    "exclude",
    "test_command",
    "junit_globs",
    "timeout_min",
)

CONVENTIONAL_SUBJECT = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([^)]+\))?!?: \S"
)
ATTRIBUTION = re.compile(r"(?im)^(co-authored-by:|.*generated with)")

CONTROL_ARMS = ("oracle", "null")

AGENT_ARMS: dict[str, dict[str, str]] = {
    "claude-base": {
        "provider": "claudeAgent",
        "model": "claude-opus-5-5",
        "style": "plan-build",
    },
    "codex-base": {
        "provider": "codex",
        "model": "gpt-6-astra",
        "style": "plan-build",
    },
    "shippy": {
        "provider": "claudeAgent",
        "model": "claude-opus-5-5",
        "style": "skill",
        "skill": "shippy",
    },
    "shippy-t3": {
        "provider": "claudeAgent",
        "model": "claude-opus-5-5",
        "style": "skill",
        "skill": "shippy-t3",
    },
}

ARMS = CONTROL_ARMS + tuple(AGENT_ARMS)

AUTO_CLAUSE = (
    "Benchmark run: no human is available. Treat the plan as approved "
    "(Approval: auto, Commits: per stage); do not ask questions; take your "
    "recommended option for every decision and note it. Do not push."
)
PLAN_SUFFIX = "Write an implementation plan only; do not edit files yet."
BUILD_PROMPT = (
    "The plan is approved. Implement it, run the relevant tests, and commit "
    "with a Conventional Commit message."
)
NUDGE = "No human is available; proceed with your recommendation."

JUDGE_MODEL = "claude-sonnet-5-5"
JUDGE_PATCH_LIMIT = 150_000
JUDGE_TIMEOUT_S = 600

_TOKEN_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")

_COUNT_KEYS = ("tests", "failures", "errors", "skipped")


def results_root() -> Path:
    """Where per-run result directories live."""
    env = os.environ.get("SHIPPY_BENCH_RESULTS")
    if env:
        return Path(env).expanduser()
    return BENCH_DIR / "results"


def bench_root() -> Path:
    """Where temporary workspaces live (outside any repository)."""
    env = os.environ.get("SHIPPY_BENCH_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path("~/shippy-bench").expanduser().resolve()


def t3_bin() -> str:
    """The t3 CLI: explicit override, then the usual install, then PATH."""
    env = os.environ.get("SHIPPY_BENCH_T3")
    if env:
        return env
    installed = Path("~/.t3/bin/t3").expanduser()
    if installed.exists():
        return str(installed)
    return "t3"


def claude_bin() -> str:
    return os.environ.get("SHIPPY_BENCH_CLAUDE") or "claude"


def claude_projects_dir() -> Path:
    env = os.environ.get("SHIPPY_BENCH_CLAUDE_DIR")
    if env:
        return Path(env).expanduser()
    return Path("~/.claude/projects").expanduser()


def codex_sessions_dir() -> Path:
    env = os.environ.get("SHIPPY_BENCH_CODEX_DIR")
    if env:
        return Path(env).expanduser()
    return Path("~/.codex/sessions").expanduser()


def slot_workspace(case_id: str, arm: str) -> Path:
    """Stable per-(case, arm) workspace reused by every k of an agent arm."""
    return bench_root() / "slots" / f"{case_id}__{arm}"


def build_turns(arm: str, task: str) -> list[str]:
    """The messages an arm receives, in order."""
    spec = AGENT_ARMS[arm]
    if spec["style"] == "plan-build":
        return [f"{task}\n\n{PLAN_SUFFIX}", f"{BUILD_PROMPT} {AUTO_CLAUSE}"]
    return [f"${spec['skill']} {task}\n\n{AUTO_CLAUSE}"]


def load_case(path_or_id: str) -> dict[str, Any]:
    """Load one case by id from ``CASES_DIR`` or by explicit JSON path."""
    path = Path(path_or_id).expanduser()
    if not path.is_file():
        path = CASES_DIR / f"{path_or_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"unknown case: {path_or_id}") from None
    case_id = data.get("id", path.stem)
    for key in REQUIRED_KEYS:
        if key not in data:
            raise ValueError(f"{case_id}: missing key {key}")
    if data.get("repo"):
        data["repo"] = str(Path(data["repo"]).expanduser())
    return data


def load_cases(spec: str) -> list[dict[str, Any]]:
    """Resolve ``all`` or a comma-separated id list to case dicts."""
    if spec.strip() == "all":
        cases = [load_case(path.stem) for path in sorted(CASES_DIR.glob("*.json"))]
        return sorted(cases, key=lambda case: case["id"])
    cases = []
    for item in spec.split(","):
        name = item.strip()
        if not name:
            continue
        try:
            cases.append(load_case(name))
        except ValueError:
            raise ValueError(f"unknown case: {name}") from None
    return cases


def git(args: list[str], cwd: Path | str, check: bool = True) -> str:
    """Run git and return stripped stdout."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _git_ok(args: list[str], cwd: Path | str) -> bool:
    return (
        subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
        ).returncode
        == 0
    )


def _bench_commit(ws: Path, message: str) -> None:
    git(
        [
            "-c",
            "user.name=bench",
            "-c",
            "user.email=bench@localhost",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--no-verify",
            "-q",
            "-m",
            message,
        ],
        ws,
    )


def run_shell(cmd: str, cwd: Path | str, timeout_s: float) -> tuple[int, str]:
    """Run a shell command, merging streams; timeouts kill the process group."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        out, _ = proc.communicate()
        code = 124
    return code, (out or "")[-4000:]


def prepare_workspace(case: dict[str, Any], ws: Path) -> str:
    """Create a one-commit workspace from ``case['commit']^`` and run setup."""
    ws = Path(ws)
    if ws.exists():
        raise FileExistsError(str(ws))
    repo = Path(case["repo"])
    commit = case["commit"]
    timeout_s = float(case["timeout_min"]) * 60

    ws.parent.mkdir(parents=True, exist_ok=True)
    ws.mkdir()

    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", f"{commit}^"],
        capture_output=True,
    )
    if archive.returncode != 0:
        raise RuntimeError(
            f"git archive {commit}^ failed: "
            f"{archive.stderr.decode('utf-8', 'replace').strip()}"
        )
    extracted = subprocess.run(
        ["tar", "-x", "-C", str(ws)],
        input=archive.stdout,
        capture_output=True,
    )
    if extracted.returncode != 0:
        raise RuntimeError(
            "tar extraction failed: "
            f"{extracted.stderr.decode('utf-8', 'replace').strip()}"
        )

    git(["init", "-q"], ws)
    exclude_path = ws / git(["rev-parse", "--git-path", "info/exclude"], ws)
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    with exclude_path.open("a", encoding="utf-8") as handle:
        for entry in [*case["exclude"], ".bench-junit/"]:
            handle.write(f"{entry}\n")

    git(["add", "-A"], ws)
    _bench_commit(ws, "benchmark base")
    base_sha = git(["rev-parse", "HEAD"], ws)

    for command in case["setup"]:
        rendered = command.replace("{repo}", str(repo))
        code, out = run_shell(rendered, ws, timeout_s)
        if code != 0:
            raise RuntimeError(f"setup failed ({code}): {rendered}\n{out}")
    return base_sha


def apply_oracle(case: dict[str, Any], ws: Path, base_sha: str) -> None:
    """Apply the real commit, minus its changed tests, as a bench commit."""
    repo = Path(case["repo"])
    commit = case["commit"]
    args = ["git", "-C", str(repo), "diff", "--binary", f"{commit}^", commit, "--", "."]
    for hidden in case["hidden_tests"]:
        args.append(f":(exclude){hidden}")
    diff = subprocess.run(args, capture_output=True)
    if diff.returncode != 0:
        raise RuntimeError(
            f"git diff {commit}^ {commit} failed: "
            f"{diff.stderr.decode('utf-8', 'replace').strip()}"
        )
    applied = subprocess.run(
        ["git", "apply", "--binary"],
        cwd=str(ws),
        input=diff.stdout,
        capture_output=True,
    )
    if applied.returncode != 0:
        raise RuntimeError(
            "git apply failed: "
            f"{applied.stderr.decode('utf-8', 'replace').strip()}"
        )
    git(["add", "-A"], ws)
    _bench_commit(ws, "oracle")


def _tail(text: str | None, limit: int = 4000) -> str:
    return (text or "")[-limit:]


def _inside_bench_root(path: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(bench_root())
    except (OSError, ValueError):
        return False


def _reset_slot(ws: Path) -> None:
    """Remove a stale slot workspace, refusing paths outside the bench root."""
    if not ws.exists():
        return
    if not _inside_bench_root(ws):
        raise RuntimeError(f"refusing to remove workspace outside {bench_root()}: {ws}")
    shutil.rmtree(ws)


def _last_json(text: str | None) -> dict[str, Any] | None:
    for line in reversed((text or "").splitlines()):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        return data if isinstance(data, dict) else None
    return None


def ensure_project(ws: Path, title: str) -> None:
    """Register the workspace as a T3 project; an existing one is fine."""
    proc = subprocess.run(
        [t3_bin(), "project", "add", str(ws), "--title", title],
        capture_output=True,
        text=True,
        errors="replace",
    )
    output = _tail((proc.stdout or "") + (proc.stderr or ""))
    if proc.returncode == 0 or "ProjectAlreadyExistsError" in output:
        return
    raise RuntimeError(f"t3 project add failed ({proc.returncode}): {output}")


def drive_t3(
    ws: Path,
    arm: str,
    turns: list[str],
    title: str,
    timeout_s: float,
    out: Path | None = None,
) -> dict[str, Any]:
    """Send ``turns`` to one t3 thread, answering permission waits up to twice."""
    spec = AGENT_ARMS[arm]
    result: dict[str, Any] = {
        "thread_id": None,
        "status": "completed",
        "questions": 0,
        "wall_s": 0.0,
        "replies": [],
        "error": None,
    }
    deadline = time.monotonic() + float(timeout_s)
    thread_id: str | None = None
    index = 0
    queued: str | None = None

    while index < len(turns):
        message = queued if queued is not None else turns[index]
        queued = None
        if thread_id is None:
            args = [
                "thread",
                "start",
                str(ws),
                "-",
                "--provider",
                spec["provider"],
                "--model",
                spec["model"],
                "--title",
                title,
                "--wait",
                "--json",
            ]
        else:
            args = ["thread", "send", thread_id, "-", "--wait", "--json"]

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            result["status"] = "timeout"
            result["error"] = "time budget exhausted before the next t3 call"
            break

        started = time.monotonic()
        try:
            proc = subprocess.run(
                [t3_bin(), *args],
                input=message,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            result["wall_s"] += time.monotonic() - started
            result["status"] = "timeout"
            result["error"] = (
                "t3 call timed out after "
                f"{remaining:.0f}s; the thread keeps running in T3"
            )
            break
        result["wall_s"] += time.monotonic() - started

        payload = _last_json(proc.stdout)
        if proc.returncode == 0:
            if payload is None:
                result["status"] = "failed"
                result["error"] = "t3 printed unparseable output: " + _tail(
                    proc.stdout, 1000
                )
                break
            if not thread_id and payload.get("threadId"):
                thread_id = str(payload["threadId"])
            result["replies"].append(payload.get("reply") or "")
            index += 1
            continue

        if proc.returncode == 2:
            result["questions"] += 1
            if not thread_id and payload and payload.get("threadId"):
                thread_id = str(payload["threadId"])
            if result["questions"] <= 2 and thread_id:
                queued = NUDGE
                continue
            result["status"] = "needs_input"
            result["error"] = "the thread is still waiting for an answer"
            break

        result["status"] = "failed"
        error = payload.get("error") if payload else None
        result["error"] = str(error) if error else (
            _tail(proc.stderr) or f"t3 exited {proc.returncode}"
        )
        break

    result["thread_id"] = thread_id
    if out is not None and thread_id:
        try:
            remaining = max(deadline - time.monotonic(), 1.0)
            shown = subprocess.run(
                [t3_bin(), "thread", "show", thread_id, "--json"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=remaining,
            )
            target = Path(out) / "thread.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(shown.stdout or "", encoding="utf-8")
        except (OSError, subprocess.SubprocessError):
            pass
    result["wall_s"] = round(result["wall_s"], 3)
    return result


def clear_junit(ws: Path, globs: list[str]) -> None:
    for pattern in globs:
        for path in Path(ws).glob(pattern):
            if path.is_file():
                path.unlink()


def collect_junit(ws: Path, globs: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in globs:
        found.extend(path for path in Path(ws).glob(pattern) if path.is_file())
    return sorted(set(found))


def parse_junit(paths: list[Path]) -> dict[str, int]:
    """Sum tests/failures/errors/skipped across JUnit XML files."""
    totals = {key: 0 for key in _COUNT_KEYS}
    totals["parse_errors"] = 0
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            totals["parse_errors"] += 1
            continue
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "testsuites" and any(key in root.attrib for key in _COUNT_KEYS):
            suites = [root]
        else:
            suites = list(root.iter("testsuite"))
            if not suites and tag == "testsuite":
                suites = [root]
        for suite in suites:
            for key in _COUNT_KEYS:
                try:
                    totals[key] += int(suite.attrib.get(key, 0) or 0)
                except (TypeError, ValueError):
                    pass
    return totals


def run_tests(case: dict[str, Any], ws: Path, key: str) -> dict[str, Any] | None:
    """Run a case command and parse its JUnit output."""
    command = case.get(key)
    if not command:
        return None
    clear_junit(ws, case["junit_globs"])
    started = time.monotonic()
    code, output = run_shell(command, ws, float(case["timeout_min"]) * 60)
    duration_s = time.monotonic() - started
    counts = parse_junit(collect_junit(ws, case["junit_globs"]))
    tests = counts["tests"]
    failures = counts["failures"]
    errors = counts["errors"]
    skipped = counts["skipped"]
    passed = tests - failures - errors - skipped
    denominator = tests - skipped
    return {
        "command": command,
        "exit_code": code,
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "parse_errors": counts["parse_errors"],
        "passed": passed,
        "pass_rate": (passed / denominator) if denominator > 0 else 0.0,
        "green": code == 0 and tests > 0 and failures + errors == 0,
        "duration_s": duration_s,
        "output_tail": output,
    }


def hygiene(ws: Path, base_sha: str) -> dict[str, Any]:
    """Check commit subjects, attribution lines and uncommitted paths."""
    subjects = [
        line
        for line in git(["log", "--reverse", "--format=%s", f"{base_sha}..HEAD"], ws).splitlines()
        if line.strip()
    ]
    non_conventional = [
        subject for subject in subjects if not CONVENTIONAL_SUBJECT.match(subject)
    ]
    attribution: list[str] = []
    shas = [
        line
        for line in git(["rev-list", "--reverse", f"{base_sha}..HEAD"], ws).splitlines()
        if line.strip()
    ]
    for sha in shas:
        message = git(["log", "-1", "--format=%B", sha], ws)
        if ATTRIBUTION.search(message):
            attribution.append(git(["log", "-1", "--format=%s", sha], ws))
    uncommitted = len(
        [line for line in git(["status", "--porcelain"], ws).splitlines() if line.strip()]
    )
    return {
        "commits": subjects,
        "non_conventional": non_conventional,
        "attribution": attribution,
        "uncommitted": uncommitted,
    }


def diff_stats(ws: Path, base_sha: str, patch_path: Path) -> dict[str, Any]:
    """Stage everything, save the binary patch and count changed lines."""
    git(["add", "-A"], ws)
    patch = subprocess.run(
        ["git", "diff", "--cached", "--binary", base_sha],
        cwd=str(ws),
        capture_output=True,
    )
    if patch.returncode != 0:
        raise RuntimeError(
            "git diff --cached failed: "
            f"{patch.stderr.decode('utf-8', 'replace').strip()}"
        )
    patch_path = Path(patch_path)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(patch.stdout)

    files = added = deleted = 0
    for line in git(["diff", "--cached", "--numstat", base_sha], ws).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added += int(parts[0]) if parts[0].isdigit() else 0
        deleted += int(parts[1]) if parts[1].isdigit() else 0
    return {
        "files": files,
        "added": added,
        "deleted": deleted,
        "empty": not patch.stdout.strip(),
    }


def install_hidden_tests(case: dict[str, Any], ws: Path) -> None:
    """Copy the graded tests from the source commit over the workspace."""
    repo = Path(case["repo"])
    commit = case["commit"]
    for relative in case["hidden_tests"]:
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{relative}"],
            capture_output=True,
        )
        if blob.returncode != 0:
            raise RuntimeError(
                f"git show {commit}:{relative} failed: "
                f"{blob.stderr.decode('utf-8', 'replace').strip()}"
            )
        target = ws / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob.stdout)


def grade(case: dict[str, Any], ws: Path, base_sha: str, out_dir: Path) -> dict[str, Any]:
    """Grade a finished workspace in the documented order."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks = hygiene(ws, base_sha)
    diff = diff_stats(ws, base_sha, out_dir / "diff.patch")
    install_hidden_tests(case, ws)
    hidden = run_tests(case, ws, "test_command")
    suite = run_tests(case, ws, "suite_command")
    return {
        "hygiene": checks,
        "diff": diff,
        "hidden": hidden,
        "suite": suite,
        "resolved": bool(hidden and hidden["green"]),
    }


def claude_slug(path: Path | str) -> str:
    """Claude Code's project directory name for an absolute path."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def _epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def _count(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _empty_tokens() -> dict[str, int]:
    return {key: 0 for key in _TOKEN_KEYS}


def collect_claude_usage(ws: Path, start: float, end: float) -> dict[str, dict]:
    """Sum Claude transcript usage for ``ws`` inside ``[start, end]``."""
    root = claude_projects_dir() / claude_slug(ws)
    latest: dict[str, dict[str, Any]] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    data = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict) or data.get("type") != "assistant":
                    continue
                message = data.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                model = message.get("model")
                if not isinstance(usage, dict) or not isinstance(model, str):
                    continue
                if not model or model == "<synthetic>":
                    continue
                stamp = _epoch(data.get("timestamp"))
                if stamp is None or stamp < start or stamp > end:
                    continue
                message_id = message.get("id")
                if not isinstance(message_id, str) or not message_id:
                    continue
                latest[message_id] = {"model": model, "usage": usage}

    totals: dict[str, dict[str, int]] = {}
    for entry in latest.values():
        usage = entry["usage"]
        tokens = totals.setdefault(entry["model"], _empty_tokens())
        tokens["input"] += _count(usage.get("input_tokens"))
        tokens["output"] += _count(usage.get("output_tokens"))
        tokens["cache_read"] += _count(usage.get("cache_read_input_tokens"))
        written = _count(usage.get("cache_creation_input_tokens"))
        split = usage.get("cache_creation")
        if isinstance(split, dict) and (
            "ephemeral_5m_input_tokens" in split
            or "ephemeral_1h_input_tokens" in split
        ):
            tokens["cache_write_5m"] += _count(split.get("ephemeral_5m_input_tokens"))
            tokens["cache_write_1h"] += _count(split.get("ephemeral_1h_input_tokens"))
        else:
            tokens["cache_write_5m"] += written
    return totals


def collect_codex_usage(ws: Path, start: float, end: float) -> dict[str, dict]:
    """Read the last Codex token count from rollouts started for ``ws``."""
    root = codex_sessions_dir()
    target = Path(ws).resolve()
    totals: dict[str, dict[str, int]] = {}
    if not root.is_dir():
        return totals
    for path in sorted(root.rglob("rollout-*.jsonl")):
        try:
            if path.stat().st_mtime < start:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        meta: dict[str, Any] | None = None
        model: str | None = None
        tokens: dict[str, int] | None = None
        for line in lines:
            try:
                data = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            payload = data.get("payload")
            if not isinstance(payload, dict):
                continue
            if kind == "session_meta" and meta is None:
                meta = data
            elif kind == "turn_context" and model is None:
                name = payload.get("model")
                if isinstance(name, str) and name:
                    model = name
            elif kind == "token_count":
                info = payload.get("info")
                usage = (info if isinstance(info, dict) else payload).get(
                    "total_token_usage"
                )
                if isinstance(usage, dict):
                    cached = _count(usage.get("cached_input_tokens"))
                    tokens = {
                        "input": _count(usage.get("input_tokens")) - cached,
                        "output": _count(usage.get("output_tokens")),
                        "cache_read": cached,
                        "cache_write_5m": 0,
                        "cache_write_1h": 0,
                    }
        if meta is None or tokens is None:
            continue
        payload = meta.get("payload") or {}
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        if not isinstance(cwd, str):
            continue
        try:
            if Path(cwd).expanduser().resolve() != target:
                continue
        except (OSError, ValueError):
            continue
        stamp = _epoch(meta.get("timestamp"))
        if stamp is None or stamp < start or stamp > end:
            continue
        name = model or "codex-unknown"
        entry = totals.setdefault(name, _empty_tokens())
        for key in _TOKEN_KEYS:
            entry[key] += tokens[key]
    return totals


def merge_usage(*usages: dict[str, dict]) -> dict[str, dict]:
    """Sum token dicts per model."""
    merged: dict[str, dict[str, int]] = {}
    for usage in usages:
        for model, tokens in (usage or {}).items():
            entry = merged.setdefault(model, _empty_tokens())
            for key in _TOKEN_KEYS:
                entry[key] += _count(tokens.get(key))
    return merged


def load_prices() -> dict[str, Any]:
    return json.loads((BENCH_DIR / "prices.json").read_text(encoding="utf-8"))


def cost_of(
    tokens_by_model: dict[str, dict], prices: dict[str, Any]
) -> tuple[float, bool]:
    """Cost in USD and whether every model had a price."""
    total = 0.0
    complete = True
    for model, tokens in tokens_by_model.items():
        price = prices.get(model)
        if not isinstance(price, dict):
            complete = False
            continue
        for key, count in tokens.items():
            rate = price.get(key)
            if rate is None:
                complete = False
                continue
            total += float(count) * float(rate) / 1_000_000
    return round(total, 6), complete


def reference_patch(case: dict[str, Any]) -> str:
    """The real commit's diff, used as the judge's reference solution."""
    repo = Path(case["repo"])
    return git(["diff", f"{case['commit']}^", case["commit"]], repo)


def _judge_prompt(
    case: dict[str, Any], reference: str, candidate: str
) -> str:
    return f"""You are grading a candidate software change against a task.

Score the CANDIDATE against the task requirements. Use the REFERENCE human
solution only as a guide: the candidate need not match it when it reaches the
same behavior another way. Judge correctness, completeness, scope discipline,
maintainability and tests.

Reply with only one JSON object and nothing else:
{{"correctness": 1-5, "completeness": 1-5, "scope": 1-5, "maintainability": 1-5, "tests": 1-5, "overall": 1-10, "notes": "<=60 words"}}

TASK:
{case.get("task", "")}

REFERENCE SOLUTION DIFF:
{reference}

CANDIDATE DIFF:
{candidate}
"""


def judge(
    case: dict[str, Any], reference_patch: str, candidate_patch: str
) -> dict[str, Any] | None:
    """Blind LLM judge of the candidate diff; None when there is no change."""
    if not candidate_patch or not candidate_patch.strip():
        return None
    truncated = {
        "reference": len(reference_patch) > JUDGE_PATCH_LIMIT,
        "candidate": len(candidate_patch) > JUDGE_PATCH_LIMIT,
    }
    prompt = _judge_prompt(
        case,
        reference_patch[:JUDGE_PATCH_LIMIT],
        candidate_patch[:JUDGE_PATCH_LIMIT],
    )
    workdir = tempfile.mkdtemp(prefix="shippy-judge-")
    try:
        proc = subprocess.run(
            [
                claude_bin(),
                "-p",
                "--model",
                JUDGE_MODEL,
                "--output-format",
                "json",
                "--max-budget-usd",
                "1",
                "--tools",
                "",
            ],
            input=prompt,
            cwd=workdir,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=JUDGE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "cost_usd": 0.0}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    payload = _last_json(proc.stdout)
    try:
        if payload is None:
            payload = json.loads((proc.stdout or "").strip())
    except (ValueError, TypeError):
        payload = None
    cost = 0.0
    if isinstance(payload, dict):
        try:
            cost = float(payload.get("total_cost_usd") or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
    if proc.returncode != 0:
        detail = _tail(proc.stderr) or f"judge exited {proc.returncode}"
        return {"error": detail, "cost_usd": cost}
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, str):
        return {"error": "judge printed no result text", "cost_usd": cost}
    start = result.find("{")
    end = result.rfind("}")
    if start < 0 or end <= start:
        return {"error": "judge result has no JSON object", "cost_usd": cost}
    try:
        scores = json.loads(result[start : end + 1])
    except (ValueError, TypeError):
        return {"error": "judge result JSON is malformed", "cost_usd": cost}
    if not isinstance(scores, dict):
        return {"error": "judge result is not an object", "cost_usd": cost}
    scores["cost_usd"] = cost
    scores["truncated"] = truncated
    scores["model"] = JUDGE_MODEL
    return scores


def skill_hash(path: Path | str) -> str | None:
    """sha256 over every file's relative path and bytes; None when missing."""
    root = Path(path)
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    files = [
        item
        for item in root.rglob("*")
        if item.is_file() and "__pycache__" not in item.relative_to(root).parts
    ]
    for item in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(item.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
    return digest.hexdigest()


def run_one(
    case: dict[str, Any],
    arm: str,
    k: int,
    run_id: str,
    opts: argparse.Namespace | dict[str, Any],
) -> dict[str, Any]:
    """Prepare, drive or apply the arm's change, grade and record one run."""
    if arm not in ARMS:
        raise NotImplementedError(arm)
    options = opts if isinstance(opts, dict) else vars(opts)
    keep_workspace = bool(options.get("keep_workspace", False))
    timeout_min = float(options.get("timeout_min") or 90)
    no_judge = bool(options.get("no_judge", False))
    agent = arm in AGENT_ARMS

    name = f"{case['id']}__{arm}__{k}"
    ws = slot_workspace(case["id"], arm) if agent else bench_root() / run_id / name
    out = results_root() / run_id / name
    out.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "run_id": run_id,
        "case": case["id"],
        "arm": arm,
        "k": k,
        "status": "ok",
        "error": None,
        "wall_s": 0.0,
        "questions": 0,
        "tokens_by_model": {},
        "cost_usd": 0.0,
        "cost_complete": True,
        "grade": None,
        "judge": None,
        "workspace": str(ws),
    }
    if agent:
        record.update(thread_id=None, drive_error=None, judge_cost_usd=0.0)
    try:
        if agent:
            _reset_slot(ws)
            base_sha = prepare_workspace(case, ws)
            ensure_project(ws, f"bench {case['id']} {arm}")
            started = time.time()
            drive = drive_t3(
                ws,
                arm,
                build_turns(arm, case["task"]),
                f"bench {run_id} {case['id']} {arm} {k}",
                timeout_min * 60,
                out=out,
            )
            ended = time.time() + 120
            usage = merge_usage(
                collect_claude_usage(ws, started, ended),
                collect_codex_usage(ws, started, ended),
            )
            cost, complete = cost_of(usage, load_prices())
            record["thread_id"] = drive["thread_id"]
            record["drive_error"] = drive["error"]
            record["wall_s"] = drive["wall_s"]
            record["questions"] = drive["questions"]
            record["tokens_by_model"] = usage
            record["cost_usd"] = cost
            record["cost_complete"] = complete
            record["status"] = (
                "ok" if drive["status"] == "completed" else drive["status"]
            )
            if drive["error"]:
                record["error"] = drive["error"]
            record["grade"] = grade(case, ws, base_sha, out)
            if not no_judge:
                candidate = (out / "diff.patch").read_text(
                    encoding="utf-8", errors="replace"
                )
                verdict = judge(case, reference_patch(case), candidate)
                record["judge"] = verdict
                if verdict:
                    record["judge_cost_usd"] = float(verdict.get("cost_usd") or 0.0)
        else:
            base_sha = prepare_workspace(case, ws)
            if arm == "oracle":
                apply_oracle(case, ws, base_sha)
            record["grade"] = grade(case, ws, base_sha, out)
    except Exception as exc:  # the record must survive a failed prep, run or grade
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        (out / "record.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        if not agent and not keep_workspace:
            if _inside_bench_root(ws) and ws.exists():
                shutil.rmtree(ws, ignore_errors=True)
    return record


def _format_result(record: dict[str, Any]) -> str:
    checks = record.get("grade")
    if checks:
        hidden = checks.get("hidden")
        suite = checks.get("suite")
        hidden_text = f"{hidden['passed']}/{hidden['tests']}" if hidden else "n/a"
        suite_text = "n/a" if not suite else ("green" if suite["green"] else "red")
        resolved = checks.get("resolved", False)
    else:
        hidden_text = suite_text = "n/a"
        resolved = False
    return (
        f"{record['case']} {record['arm']} {record['k']} {record['status']} "
        f"resolved={resolved} hidden={hidden_text} suite={suite_text} "
        f"wall={record['wall_s']}s"
    )


def _k_value(record: dict[str, Any]) -> int:
    try:
        return int(record.get("k") or 0)
    except (TypeError, ValueError):
        return 0


def load_records(run_ids: list[str]) -> list[dict[str, Any]]:
    """Every ``record.json`` under the given run ids, sorted by case/arm/k."""
    records: list[dict[str, Any]] = []
    for run_id in run_ids:
        run_dir = results_root() / run_id
        if not run_dir.is_dir():
            continue
        for path in run_dir.glob("*/record.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                records.append(data)
    records.sort(
        key=lambda record: (
            str(record.get("case")),
            str(record.get("arm")),
            _k_value(record),
        )
    )
    return records


def total_tokens(record: dict[str, Any]) -> int:
    """Sum every token count over every model in one record."""
    tokens_by_model = record.get("tokens_by_model")
    if not isinstance(tokens_by_model, dict):
        return 0
    total = 0
    for tokens in tokens_by_model.values():
        if isinstance(tokens, dict):
            total += sum(_count(value) for value in tokens.values())
    return total


def _median(values: list[float]) -> float | None:
    numbers = sorted(float(value) for value in values)
    if not numbers:
        return None
    middle = len(numbers) // 2
    if len(numbers) % 2:
        return numbers[middle]
    return (numbers[middle - 1] + numbers[middle]) / 2


def _grade_of(record: dict[str, Any]) -> dict[str, Any]:
    grade = record.get("grade")
    return grade if isinstance(grade, dict) else {}


def _hidden_of(record: dict[str, Any]) -> dict[str, Any] | None:
    hidden = _grade_of(record).get("hidden")
    return hidden if isinstance(hidden, dict) else None


def _suite_of(record: dict[str, Any]) -> dict[str, Any] | None:
    suite = _grade_of(record).get("suite")
    return suite if isinstance(suite, dict) else None


def _resolved_of(record: dict[str, Any]) -> bool:
    return bool(_grade_of(record).get("resolved"))


def _judge_overall(record: dict[str, Any]) -> float | None:
    verdict = record.get("judge")
    if not isinstance(verdict, dict):
        return None
    overall = verdict.get("overall")
    if isinstance(overall, bool) or not isinstance(overall, (int, float)):
        return None
    return float(overall)


def _hygiene_issue(record: dict[str, Any]) -> bool:
    checks = _grade_of(record).get("hygiene")
    if not isinstance(checks, dict):
        return False
    return bool(
        checks.get("non_conventional")
        or checks.get("attribution")
        or _count(checks.get("uncommitted")) > 0
    )


def _arm_order(grouped: dict[str, Any]) -> list[str]:
    order = [arm for arm in ARMS if arm in grouped]
    order += sorted(arm for arm in grouped if arm not in ARMS)
    return order


def summarize(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-arm aggregates over one or more runs."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        arm = record.get("arm")
        if isinstance(arm, str):
            grouped.setdefault(arm, []).append(record)

    summary: dict[str, dict[str, Any]] = {}
    for arm in _arm_order(grouped):
        items = grouped[arm]
        count = len(items)
        pass_rates = [
            hidden["pass_rate"]
            for hidden in (_hidden_of(record) for record in items)
            if isinstance(hidden, dict)
            and isinstance(hidden.get("pass_rate"), (int, float))
        ]
        suites = [
            suite for suite in (_suite_of(record) for record in items) if suite
        ]
        costs = [
            float(record["cost_usd"])
            for record in items
            if record.get("cost_complete", True)
            and isinstance(record.get("cost_usd"), (int, float))
        ]
        judged = [
            overall
            for overall in (_judge_overall(record) for record in items)
            if overall is not None
        ]
        walls = [
            float(record["wall_s"]) / 60.0
            for record in items
            if isinstance(record.get("wall_s"), (int, float))
        ]
        summary[arm] = {
            "n": count,
            "errors": sum(1 for record in items if record.get("status") != "ok"),
            "resolved_rate": (
                sum(1 for record in items if _resolved_of(record)) / count
                if count
                else None
            ),
            "hidden_pass_mean": (
                sum(pass_rates) / len(pass_rates) if pass_rates else None
            ),
            "suite_green_rate": (
                sum(1 for suite in suites if suite.get("green")) / len(suites)
                if suites
                else None
            ),
            "wall_min_median": _median(walls),
            "cost_median": _median(costs),
            "cost_incomplete": sum(
                1 for record in items if not record.get("cost_complete", True)
            ),
            "tokens_median": _median([total_tokens(record) for record in items]),
            "judge_mean": sum(judged) / len(judged) if judged else None,
            "questions": sum(_count(record.get("questions")) for record in items),
            "hygiene_issues": sum(
                1 for record in items if _hygiene_issue(record)
            ),
        }
    return summary


_PAIRED_METRICS = ("cost", "wall", "resolved", "judge")


def _case_metric(records: list[dict[str, Any]], metric: str) -> float | None:
    if metric == "cost":
        values = [
            float(record["cost_usd"])
            for record in records
            if record.get("cost_complete", True)
            and isinstance(record.get("cost_usd"), (int, float))
        ]
    elif metric == "wall":
        values = [
            float(record["wall_s"])
            for record in records
            if isinstance(record.get("wall_s"), (int, float))
        ]
    elif metric == "resolved":
        values = [1.0 if _resolved_of(record) else 0.0 for record in records]
    else:
        values = [
            overall
            for overall in (_judge_overall(record) for record in records)
            if overall is not None
        ]
    return _median(values)


def paired(
    records: list[dict[str, Any]], baseline: str = "claude-base"
) -> dict[str, dict[str, Any]]:
    """Per-case win/loss/tie counts of every arm against ``baseline``."""
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        arm = record.get("arm")
        if isinstance(arm, str):
            grouped.setdefault(arm, {}).setdefault(
                str(record.get("case")), []
            ).append(record)
    if baseline not in grouped:
        return {}

    base = grouped[baseline]
    result: dict[str, dict[str, Any]] = {}
    for arm in _arm_order(grouped):
        if arm == baseline:
            continue
        cases = sorted(
            case
            for case, items in grouped[arm].items()
            if case in base
            and all(record.get("status") == "ok" for record in items)
            and all(record.get("status") == "ok" for record in base[case])
        )
        counts = {metric: [0, 0, 0] for metric in _PAIRED_METRICS}
        for case in cases:
            for metric in _PAIRED_METRICS:
                arm_value = _case_metric(grouped[arm][case], metric)
                base_value = _case_metric(base[case], metric)
                if arm_value is None or base_value is None:
                    continue
                if arm_value == base_value:
                    counts[metric][2] += 1
                elif metric in ("cost", "wall"):
                    counts[metric][0 if arm_value < base_value else 1] += 1
                else:
                    counts[metric][0 if arm_value > base_value else 1] += 1
        entry: dict[str, Any] = {"cases": len(cases)}
        entry.update(counts)
        result[arm] = entry
    return result


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _verdict(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _version_text(value: Any, label: str) -> str:
    """Render a version string without repeating its own label."""
    if not value:
        return "n/a"
    text = str(value).strip()
    prefix = f"{label} "
    if text.lower().startswith(prefix.lower()):
        text = text[len(prefix):]
    return text or "n/a"


def render_report(
    run_ids: list[str],
    records: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
    baseline: str = "claude-base",
) -> str:
    """Markdown report: versions, per-arm aggregates, paired and per-run tables."""
    meta = meta or {}
    head = meta.get("shippy_head") or "n/a"
    lines = [
        f"# Benchmark report: {', '.join(run_ids)}",
        "",
        (
            f"Versions: claude {_version_text(meta.get('claude_version'), 'claude')} · "
            f"t3 {_version_text(meta.get('t3_version'), 't3')} · "
            f"shippy {head[:12]}"
        ),
    ]
    skills = meta.get("skills")
    if isinstance(skills, dict):
        mismatched = sorted(
            name
            for name, state in skills.items()
            if isinstance(state, dict) and not state.get("match")
        )
        if mismatched:
            lines += [
                "",
                "Warning: installed skill copy differs from repo: "
                f"{', '.join(mismatched)}.",
            ]

    lines += [
        "",
        "## Arms",
        "",
        "| Arm | n | Errors | Resolved | Hidden pass | Suite green | "
        "Median wall (min) | Median cost ($) | Median tokens | Judge | "
        "Questions | Hygiene issues |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, stats in summarize(records).items():
        lines.append(
            "| "
            + " | ".join(
                [
                    arm,
                    str(stats["n"]),
                    str(stats["errors"]),
                    _pct(stats["resolved_rate"]),
                    _pct(stats["hidden_pass_mean"]),
                    _pct(stats["suite_green_rate"]),
                    _num(stats["wall_min_median"]),
                    _money(stats["cost_median"]),
                    _num(stats["tokens_median"], 0),
                    _num(stats["judge_mean"]),
                    str(stats["questions"]),
                    str(stats["hygiene_issues"]),
                ]
            )
            + " |"
        )

    lines += ["", f"## Paired vs {baseline}", ""]
    comparisons = paired(records, baseline)
    if not comparisons:
        if not any(record.get("arm") == baseline for record in records):
            lines.append(
                f"_Paired comparison omitted: baseline {baseline} has no records._"
            )
        else:
            lines.append(
                "_Paired comparison omitted: no other arm has records._"
            )
    else:
        lines += [
            f"| Arm | Cases | Cost W/L/T | Wall W/L/T | Resolved W/L/T | "
            f"Judge W/L/T |",
            "|---|---|---|---|---|---|",
        ]
        for arm, entry in comparisons.items():
            lines.append(
                "| "
                + " | ".join(
                    [
                        arm,
                        str(entry["cases"]),
                        *(
                            f"{entry[metric][0]}/{entry[metric][1]}/"
                            f"{entry[metric][2]}"
                            for metric in _PAIRED_METRICS
                        ),
                    ]
                )
                + " |"
            )

    lines += [
        "",
        "## Runs",
        "",
        "| Case | Arm | k | Status | Resolved | Hidden | Suite | "
        "Wall (min) | Cost ($) | Tokens | Judge |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        hidden = _hidden_of(record)
        suite = _suite_of(record)
        cost = record.get("cost_usd")
        cost_text = _money(cost if isinstance(cost, (int, float)) else None)
        if isinstance(cost, (int, float)) and not record.get(
            "cost_complete", True
        ):
            cost_text += "*"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.get("case")),
                    str(record.get("arm")),
                    str(_k_value(record)),
                    str(record.get("status")),
                    "yes" if _resolved_of(record) else "no",
                    (
                        f"{hidden.get('passed', 0)}/{hidden.get('tests', 0)}"
                        if hidden
                        else "-"
                    ),
                    (
                        "green"
                        if suite and suite.get("green")
                        else ("red" if suite else "-")
                    ),
                    _num(
                        float(record["wall_s"]) / 60.0
                        if isinstance(record.get("wall_s"), (int, float))
                        else None
                    ),
                    cost_text,
                    str(total_tokens(record)),
                    _verdict(_judge_overall(record)),
                ]
            )
            + " |"
        )
    lines += ["", "* marks a cost that omits at least one unpriced model."]
    return "\n".join(lines)


def _preflight_case(case: dict[str, Any]) -> list[str]:
    repo = Path(case["repo"])
    commit = case["commit"]
    problems: list[str] = []
    if not repo.is_dir():
        return [f"repo missing: {repo}"]
    if not _git_ok(["rev-parse", "--git-dir"], repo):
        return [f"repo is not a git repo: {repo}"]
    for revision in (f"{commit}^{{commit}}", f"{commit}^"):
        if not _git_ok(["cat-file", "-e", revision], repo):
            problems.append(f"missing revision {revision}")
    for hidden in case["hidden_tests"]:
        if not _git_ok(["cat-file", "-e", f"{commit}:{hidden}"], repo):
            problems.append(f"missing test {hidden} at {commit[:12]}")
    return problems


def _binary_version(binary: str) -> tuple[bool, str]:
    """Run ``<binary> --version``; return (ok, version or error)."""
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc) or type(exc).__name__
    text = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0:
        first = text.splitlines()[0].strip() if text else f"exit {proc.returncode}"
        return False, first
    if not text:
        return False, "no version output"
    return True, text.splitlines()[0].strip()


def _version_or_none(binary: str) -> str | None:
    ok, text = _binary_version(binary)
    return text if ok else None


def _skills_state() -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    installed_root = Path("~/.claude/skills").expanduser()
    for name in ("shippy", "shippy-t3"):
        repo = BENCH_DIR.parent / "skills" / name
        installed = installed_root / name
        repo_hash = skill_hash(repo)
        installed_hash = skill_hash(installed)
        state[name] = {
            "repo": str(repo),
            "installed": str(installed),
            "match": repo_hash is not None and repo_hash == installed_hash,
        }
    return state


def _write_meta(run_id: str, cases: list[dict[str, Any]], arms: list[str], runs: int) -> None:
    try:
        head = git(["rev-parse", "HEAD"], BENCH_DIR.parent, check=False)
    except OSError:
        head = None
    meta = {
        "run_id": run_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shippy_head": head or None,
        "python": sys.version.split()[0],
        "cases": [case["id"] for case in cases],
        "arms": arms,
        "runs": runs,
        "claude_version": _version_or_none(claude_bin()),
        "t3_version": _version_or_none(t3_bin()),
        "prices": load_prices(),
        "skills": _skills_state(),
    }
    out = results_root() / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="check every case's repositories and revisions")

    run = sub.add_parser("run", help="prepare, run and grade cases")
    run.add_argument("--cases", default="all")
    run.add_argument("--arms", default="oracle,null")
    run.add_argument("--runs", type=int, default=1)
    run.add_argument("--run-id", default=None)
    run.add_argument("--max-cost-usd", type=float, default=None)
    run.add_argument("--timeout-min", type=int, default=90)
    run.add_argument("--no-judge", action="store_true")
    run.add_argument("--keep-workspace", action="store_true")

    report = sub.add_parser("report", help="aggregate run records into a report")
    report.add_argument("run_ids", nargs="+", metavar="RUN_ID")
    report.add_argument("--baseline", default="claude-base")

    args = parser.parse_args(argv)

    if args.command == "report":
        records = load_records(args.run_ids)
        if not records:
            print(
                f"no records found under {results_root()} for "
                f"{', '.join(args.run_ids)}",
                file=sys.stderr,
            )
            return 1
        meta: dict[str, Any] | None = None
        meta_path = results_root() / args.run_ids[0] / "meta.json"
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                loaded = None
            if isinstance(loaded, dict):
                meta = loaded
        text = render_report(args.run_ids, records, meta, args.baseline)
        target = results_root() / args.run_ids[0] / "report.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0

    if args.command == "preflight":
        cases = load_cases("all")
        failed = False
        for case in cases:
            problems = _preflight_case(case)
            if problems:
                failed = True
                print(f"FAIL {case['id']} {'; '.join(problems)}")
            else:
                print(f"OK {case['id']}")
        for label, binary in (("t3", t3_bin()), ("claude", claude_bin())):
            ok, text = _binary_version(binary)
            if not ok:
                failed = True
                print(f"FAIL {label} {text}")
            else:
                print(f"OK {label} {text}")
        for name, state in _skills_state().items():
            if not state["match"]:
                print(f"WARN skill {name} installed copy differs from repo")
        return 1 if failed else 0

    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if not arms or any(arm not in ARMS for arm in arms):
        print(f"unknown arm(s): {args.arms}", file=sys.stderr)
        return 2
    max_cost = args.max_cost_usd
    if any(arm in AGENT_ARMS for arm in arms) and max_cost is None:
        print("agent arms require --max-cost-usd", file=sys.stderr)
        return 2
    cases = load_cases(args.cases)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    _write_meta(run_id, cases, arms, args.runs)
    spent = 0.0
    for case in cases:
        for arm in arms:
            for k in range(1, args.runs + 1):
                if max_cost is not None and spent >= max_cost:
                    print(
                        f"cost cap reached: ${spent:.6g} >= ${max_cost:.6g}",
                        flush=True,
                    )
                    return 2
                record = run_one(case, arm, k, run_id, args)
                print(_format_result(record), flush=True)
                spent += float(record.get("cost_usd") or 0.0)
                spent += float(record.get("judge_cost_usd") or 0.0)
                if arm in AGENT_ARMS and not record.get("cost_complete", True):
                    print(
                        f"{case['id']} {arm} {k}: cost is incomplete "
                        "(unpriced model); it is not counted toward the cap",
                        flush=True,
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
