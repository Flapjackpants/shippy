#!/usr/bin/env python3
"""Replay benchmark: prepare a workspace from a source commit, grade a change.

Stage 2 covers case loading, workspace preparation, grading and the free
control arms (``oracle`` and ``null``). Agent arms, usage accounting, cost,
judging and reporting are added by later stages.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
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


def run_one(
    case: dict[str, Any],
    arm: str,
    k: int,
    run_id: str,
    opts: argparse.Namespace | dict[str, Any],
) -> dict[str, Any]:
    """Prepare, apply the arm's change, grade and record one run."""
    if arm not in CONTROL_ARMS:
        raise NotImplementedError(arm)
    keep_workspace = bool(
        opts.get("keep_workspace") if isinstance(opts, dict) else getattr(opts, "keep_workspace", False)
    )
    name = f"{case['id']}__{arm}__{k}"
    ws = bench_root() / run_id / name
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
    try:
        base_sha = prepare_workspace(case, ws)
        if arm == "oracle":
            apply_oracle(case, ws, base_sha)
        record["grade"] = grade(case, ws, base_sha, out)
    except Exception as exc:  # the record must survive a failed prep or grade
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        (out / "record.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        if not keep_workspace:
            try:
                inside = ws.resolve().is_relative_to(bench_root())
            except (OSError, ValueError):
                inside = False
            if inside and ws.exists():
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

    args = parser.parse_args(argv)

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
        return 1 if failed else 0

    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if not arms or any(arm not in CONTROL_ARMS for arm in arms):
        print(f"unknown arm(s): {args.arms}", file=sys.stderr)
        return 2
    cases = load_cases(args.cases)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    _write_meta(run_id, cases, arms, args.runs)
    for case in cases:
        for arm in arms:
            for k in range(1, args.runs + 1):
                record = run_one(case, arm, k, run_id, args)
                print(_format_result(record), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
