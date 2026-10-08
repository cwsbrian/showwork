#!/usr/bin/env python3
"""Record evidence for a coding task. Evidence coverage is not acceptance."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills' / 'showwork' / 'scripts'))
from runtime import temporary_root, workspace

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_run(directory, run):
    fd, temporary = tempfile.mkstemp(prefix=".run-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(run, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, directory / "run.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_run(directory):
    run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    if not isinstance(run, dict) or run.get("schema_version") != 1:
        raise ValueError("Unsupported run format; expected schema_version 1")
    if not isinstance(run.get("criteria"), list) or not run["criteria"]:
        raise ValueError("Run has no acceptance criteria")
    if not isinstance(run.get("evidence"), list):
        raise ValueError("Run evidence must be a list")
    if not directory.is_relative_to(temporary_root()) or directory.is_relative_to(Path(run['workspace']).resolve()):
        raise ValueError('Move legacy evidence to temporary storage outside the project before using it')
    return run


@contextmanager
def run_lock(directory):
    with (directory / ".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append_evidence(directory, record):
    # Checks may run in parallel; merge into the latest manifest while locked.
    with run_lock(directory):
        run = read_run(directory)
        require_criterion(run, record["criterion"])
        run["evidence"].append(record)
        write_run(directory, run)


def require_criterion(run, criterion):
    if criterion not in {item["id"] for item in run["criteria"]}:
        raise ValueError(f"Unknown criterion {criterion}; inspect run.json for criterion IDs")


def init_run(args):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.slug):
        raise ValueError("Use a lowercase slug such as order-cancellation")
    if not args.title.strip() or any(not value.strip() for value in args.criterion):
        raise ValueError("Title and acceptance criteria cannot be blank")
    root = args.root.expanduser().resolve() if args.root else workspace(Path.cwd()) / 'runs'
    if not root.is_relative_to(temporary_root()) or root.is_relative_to(Path.cwd().resolve()):
        raise ValueError('Evidence root must be in temporary storage outside the project')
    directory = root / args.slug
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "evidence").mkdir()
    run = {
        "schema_version": 1,
        "title": args.title.strip(),
        "created_at": now(),
        "workspace": str(Path.cwd()),
        "criteria": [
            {"id": f"C{index}", "text": value.strip()}
            for index, value in enumerate(args.criterion, start=1)
        ],
        "evidence": [],
    }
    write_run(directory, run)
    print(directory)
    for criterion in run["criteria"]:
        print(f"{criterion['id']}: {criterion['text']}")
    return 0


def revision(cwd):
    """Context only: a HEAD plus dirty flag is not a complete tree fingerprint."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
            text=True, timeout=5, check=False,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=cwd, capture_output=True,
            text=True, timeout=5, check=False,
        )
        return {
            "head": head.stdout.strip() if head.returncode == 0 else None,
            "dirty": bool(status.stdout) if status.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"head": None, "dirty": None}


def stop_process(process):
    # POSIX checks run in their own session, so timed-out child processes stop too.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


class Terminated(Exception):
    pass


def handle_termination(signum, frame):
    raise Terminated()


def check(args, command):
    if not command:
        raise ValueError("Provide a command after --")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("Timeout must be a positive, finite number of seconds")
    directory = args.run.expanduser().resolve()
    run = read_run(directory)
    require_criterion(run, args.criterion)
    cwd = (args.cwd or Path(run["workspace"])).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd}")
    identifier = uuid4().hex[:12]
    relative_path = f"evidence/{identifier}.log"
    log_path = directory / relative_path
    record = {
        "id": identifier, "criterion": args.criterion, "kind": "check",
        "started_at": now(), "command": command, "cwd": str(cwd),
        "revision": revision(cwd), "path": relative_path,
    }
    with log_path.open("wb") as stream:
        process = None
        previous_handler = signal.signal(signal.SIGTERM, handle_termination)
        try:
            process = subprocess.Popen(
                command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=(os.name == "posix"),
            )
            code = process.wait(timeout=args.timeout)
            record.update(exit_code=code, result="passed" if code == 0 else "failed")
        except OSError as error:
            stream.write(f"Could not start command: {error}\n".encode())
            record.update(exit_code=127, result="error")
        except subprocess.TimeoutExpired:
            stop_process(process)
            stream.write(f"\nTimed out after {args.timeout:g} seconds\n".encode())
            record.update(exit_code=124, result="timeout")
        except (KeyboardInterrupt, Terminated) as error:
            if process is not None:
                stop_process(process)
            stream.write(b"\nInterrupted\n")
            record.update(exit_code=143 if isinstance(error, Terminated) else 130, result="interrupted")
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
    record.update(finished_at=now(), sha256=digest(log_path))
    append_evidence(directory, record)
    print(f"{record['result']}: {args.criterion} (exit {record['exit_code']})")
    print(log_path)
    # Preserve useful shell exit codes, including a process killed by a signal.
    code = record["exit_code"]
    return code if 0 <= code <= 255 else min(255, 128 + abs(code))


def attach(args):
    directory = args.run.expanduser().resolve()
    run = read_run(directory)
    require_criterion(run, args.criterion)
    source = args.path.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Evidence file does not exist: {source}")
    if not args.note.strip():
        raise ValueError("Describe what the evidence shows with --note")
    identifier = uuid4().hex[:12]
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", source.name)
    relative_path = f"evidence/{identifier}-{filename}"
    destination = directory / relative_path
    shutil.copyfile(source, destination)
    append_evidence(directory, {
        "id": identifier, "criterion": args.criterion, "kind": args.kind,
        "recorded_at": now(), "path": relative_path,
        "sha256": digest(destination), "note": args.note.strip(),
        "source": str(source), "result": "recorded",
    })
    print(f"Recorded {args.kind} for {args.criterion}; inspect it before judging acceptance.")
    print(destination)
    return 0


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def status(args):
    directory = args.run.expanduser().resolve()
    run = read_run(directory)
    print(f"# {cell(run['title'])}\n")
    print("Evidence inventory — acceptance requires review.\n")
    print("| Criterion | Evidence state | Requirement |")
    print("| --- | --- | --- |")
    incomplete = False
    for criterion in run["criteria"]:
        records = [item for item in run["evidence"] if item["criterion"] == criterion["id"]]
        checks = [item for item in records if item["kind"] == "check"]
        state = "missing"
        if records:
            state = f"{len(records)} item(s) recorded; review required"
        if checks:
            state = f"latest check {checks[-1]['result']}; review required"
        if not records or (checks and checks[-1]["result"] != "passed"):
            incomplete = True
        print(f"| {criterion['id']} | {state} | {cell(criterion['text'])} |")
    print("\nRecorded files:")
    for record in run["evidence"]:
        path = (directory / record["path"]).resolve()
        valid_path = path.is_relative_to(directory / "evidence")
        intact = valid_path and path.is_file() and digest(path) == record["sha256"]
        if not intact:
            incomplete = True
        integrity = "intact" if intact else "MISSING OR CHANGED"
        print(f"- {record['criterion']}: {record['path']} ({record['kind']}; {integrity})")
    print("\nThese records do not establish correctness or freshness. Inspect their relevance,")
    print("rerun affected checks after changes, and explain remaining limitations in the handoff.")
    return 1 if incomplete else 0


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create a task with observable acceptance criteria")
    init.add_argument("slug")
    init.add_argument("--title", required=True)
    init.add_argument("--criterion", action="append", required=True)
    init.add_argument("--root", type=Path, help="Optional temporary root outside the project; defaults to private /tmp storage")
    run = sub.add_parser("check", help="Capture a command: check RUN --criterion C1 -- COMMAND ...")
    run.add_argument("run", type=Path)
    run.add_argument("--criterion", required=True)
    run.add_argument("--cwd", type=Path)
    run.add_argument("--timeout", type=float, default=300)
    attachment = sub.add_parser("attach", help="Copy an existing artifact into the evidence inventory")
    attachment.add_argument("run", type=Path)
    attachment.add_argument("--criterion", required=True)
    attachment.add_argument("--kind", choices=["screenshot", "video", "api", "manual"], required=True)
    attachment.add_argument("--path", type=Path, required=True)
    attachment.add_argument("--note", required=True)
    report = sub.add_parser("status", help="Print evidence coverage, check results, and file integrity")
    report.add_argument("run", type=Path)
    return cli


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in arguments:
        separator = arguments.index("--")
        arguments, command = arguments[:separator], arguments[separator + 1:]
    cli = parser()
    args = cli.parse_args(arguments)
    if command and args.action != "check":
        cli.error("Commands after -- are supported only by check")
    try:
        if args.action == "init":
            return init_run(args)
        if args.action == "check":
            return check(args, command)
        if args.action == "attach":
            return attach(args)
        return status(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"showwork: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
