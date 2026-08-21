#!/usr/bin/env python3
"""Loopback-only client for delegating work to DeepSeek Harness."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX path
    msvcrt = None


DEFAULT_BASE_URL = "http://127.0.0.1:3080"
DEFAULT_TIMEOUT: float | None = None
POLL_INTERVAL = 1.0
HEALTH_CHECK_INTERVAL = 15.0
INACTIVE_GRACE = 60.0
START_TIMEOUT = 20.0
ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")
REASONING_EFFORTS = ("off", "low", "high", "max")
SCOPES = ("auto", "single-dir", "cross-file", "proposal-only")
PROJECT_ROOT_MARKERS = (
    ".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "Makefile", "AGENTS.md",
)
FORBIDDEN_GLOBS = (
    "**/.env", "**/.env.*", "**/*.key", "**/*.pem", "**/*.p12",
    "~/.ssh/**", "~/.gnupg/**", "~/.aws/**", "**/credentials*",
    "**/.dsh-delegation-history/**",
)
CONTROL_FILES = ("RESULT.md", "OPINION.md", "ASK.md")
RUN_CONTROL_FILES = ("SCOPE.md", "TASK.md", "STATUS.json", *CONTROL_FILES)
RUN_HISTORY_DIRECTORY = ".dsh-delegation-history"
DELEGATE_LOCK_DIRECTORY = "delegate-locks"


class HarnessError(RuntimeError):
    """A transport, protocol, or Harness business error."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep a loopback request from being redirected outside the boundary."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def loopback_base_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if parsed.scheme != "http":
        raise HarnessError("base URL must use http")
    if parsed.username is not None or parsed.password is not None:
        raise HarnessError("base URL must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise HarnessError("base URL must contain only scheme, loopback host, and port")
    host = parsed.hostname
    if host is None:
        raise HarnessError("base URL has no host")
    host = host.lower()
    if host not in ALLOWED_LOOPBACK_HOSTS:
        raise HarnessError("refusing non-loopback DeepSeek Harness endpoint")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise HarnessError("base URL has an invalid port") from exc
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HarnessError(f"cannot resolve loopback host {host}: {exc}") from exc
    if not resolved or any(not ipaddress.ip_address(item[4][0]).is_loopback for item in resolved):
        raise HarnessError("loopback hostname resolved to a non-loopback address")
    rendered_host = f"[{host}]" if host == "::1" else host
    return urlunsplit(("http", f"{rendered_host}:{port}", "", "", ""))


class HarnessClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = loopback_base_url(base_url)
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirectHandler(),
        )

    def _json_request(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise HarnessError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise HarnessError(f"cannot reach {self.base_url}: {exc.reason}") from exc
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HarnessError("Harness returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise HarnessError("Harness returned a non-object JSON response")
        return value

    def probe_root(self) -> int:
        request = urllib.request.Request(f"{self.base_url}/", method="GET")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                response.read(1)
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except urllib.error.URLError as exc:
            raise HarnessError(f"cannot reach {self.base_url}: {exc.reason}") from exc

    def rpc(self, method: str, payload: dict[str, Any]) -> tuple[str, Any]:
        rpc_id = str(uuid.uuid4())
        envelope = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload,
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/{method}",
            data=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        response = self._json_request(request)
        if response.get("type") != "server-response":
            raise HarnessError(f"unexpected response type for {method}")
        if response.get("rpcId") != rpc_id:
            raise HarnessError(f"rpcId mismatch for {method}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise HarnessError(f"missing result for {method}")
        if result.get("ok") is not True:
            error = result.get("error")
            if isinstance(error, dict):
                code = str(error.get("code", "unknown"))
                message = str(error.get("message", "Harness request failed"))
                details = json.dumps(error.get("details", {}), ensure_ascii=False, sort_keys=True)
                raise HarnessError(f"{method} failed [{code}]: {message}; details={details}")
            raise HarnessError(f"{method} failed")
        return rpc_id, result.get("value")

    def sessions(self) -> list[dict[str, Any]]:
        _, value = self.rpc("session.list", {})
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise HarnessError("session.list returned an invalid value")
        return [item for item in value["items"] if isinstance(item, dict)]

    def history(self, session_id: str) -> list[dict[str, Any]]:
        _, value = self.rpc(
            "session.history",
            {"sessionId": session_id, "maxMessages": 200},
        )
        if not isinstance(value, dict) or not isinstance(value.get("events"), list):
            raise HarnessError("session.history returned an invalid value")
        events: list[dict[str, Any]] = []
        for entry in value["events"]:
            if isinstance(entry, dict) and isinstance(entry.get("event"), dict):
                events.append(entry["event"])
        return events

    def select_model(
        self,
        session_id: str,
        model: str,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "sessionId": session_id,
            "provider": "deepseek-official",
            "model": model,
        }
        if reasoning_effort is not None:
            payload["reasoningEffort"] = reasoning_effort
        _, value = self.rpc(
            "session.selectModel",
            payload,
        )
        if not isinstance(value, dict) or not isinstance(value.get("selected"), dict):
            raise HarnessError("session.selectModel returned an invalid value")
        selected = value["selected"]
        if selected.get("provider") != "deepseek-official" or selected.get("model") != model:
            raise HarnessError("session.selectModel returned an unexpected selection")
        if (
            reasoning_effort is not None
            and selected.get("reasoningEffort") != reasoning_effort
        ):
            raise HarnessError(
                "session.selectModel returned an unexpected reasoning effort"
            )
        return selected


def require_directory(raw: str) -> str:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise HarnessError("working directory must be an absolute path")
    path = candidate.resolve()
    if not path.is_dir():
        raise HarnessError(f"working directory does not exist: {path}")
    if path == Path(path.anchor) or path == Path.home():
        raise HarnessError("working directory must be narrower than a filesystem or user-home root")
    return str(path)


def ensure_directory(raw: str) -> str:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise HarnessError("working directory must be an absolute path")
    path = candidate.resolve(strict=False)
    if path == Path(path.anchor) or path == Path.home():
        raise HarnessError("working directory must be narrower than a filesystem or user-home root")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise HarnessError(f"working directory is not a directory: {path}")
    return str(path.resolve())


def atomic_write_text(directory: str, name: str, text: str) -> Path:
    root = Path(directory).resolve()
    if Path(name).name != name:
        raise HarnessError(f"invalid control filename: {name}")
    destination = root / name
    fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=root, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


def read_control_file(directory: str, name: str) -> str | None:
    root = Path(directory).resolve()
    path = root / name
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise HarnessError(f"refusing symlinked control file: {path}")
    resolved = path.resolve()
    if resolved.parent != root or not resolved.is_file():
        raise HarnessError(f"invalid control file: {path}")
    return resolved.read_text(encoding="utf-8")


def reject_obvious_secrets(text: str) -> None:
    patterns = (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\bsk-[A-Za-z0-9_-]{16,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{16,}\b",
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[^\s]{8,}",
    )
    if any(re.search(pattern, text) for pattern in patterns):
        raise HarnessError("task text appears to contain a secret; remove it before delegation")


def read_task(args: argparse.Namespace) -> str:
    if args.text is not None:
        text = args.text
    elif args.text_file == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.text_file).expanduser().read_text(encoding="utf-8")
    if not text.strip():
        raise HarnessError("task text must not be empty")
    reject_obvious_secrets(text)
    return text


def classify_scope(requested: str, cwd: str, task: str) -> tuple[str, str]:
    if requested != "auto":
        return requested, "explicit"
    proposal_markers = (
        "proposal only", "review only", "do not modify", "不要修改", "不改码",
        "只出方案", "只写 result.md", "评审", "审查", "重构建议",
    )
    lowered = task.lower()
    if any(marker in lowered for marker in proposal_markers):
        return "proposal-only", "auto:proposal-language"
    root = Path(cwd)
    if any((root / marker).exists() for marker in PROJECT_ROOT_MARKERS):
        return "cross-file", "auto:project-root-marker"
    return "single-dir", "auto:no-project-root-marker"


def scope_document(cwd: str, task_type: str, decision: str) -> str:
    write_globs = (
        ("./RESULT.md", "./OPINION.md", "./ASK.md", "./STATUS.json")
        if task_type == "proposal-only"
        else ("./**",)
    )
    lines = ["write:"]
    lines.extend(f"  - {json.dumps(item)}" for item in write_globs)
    lines.append("read:")
    lines.append(f"  - {json.dumps('./**')}")
    lines.append("forbidden:")
    lines.extend(f"  - {json.dumps(item)}" for item in FORBIDDEN_GLOBS)
    lines.extend([
        f"taskType: {json.dumps(task_type)}",
        f"cwd: {json.dumps(cwd)}",
        f"decision: {json.dumps(decision)}",
        "enforcement:",
        f"  writeBoundary: {json.dumps('DeepSeek Harness session cwd')}",
        f"  readBoundary: {json.dumps('instructional only; workspace-write does not restrict reads')}",
    ])
    return "\n".join(lines) + "\n"


def task_document(task: str, task_type: str, decision: str) -> str:
    scope_instruction = (
        "先读 SCOPE.md 再开工；发现需要触碰范围外路径就停止并写 ASK.md，"
        "不要越界、不要擅自放宽范围。"
    )
    output_instruction = (
        "把最终结果写入 RESULT.md；可选建议写入 OPINION.md；需要扩权或反问写入 ASK.md。"
    )
    if task_type == "proposal-only":
        output_instruction += " 本任务只允许写 RESULT.md/OPINION.md/ASK.md/STATUS.json，不要修改任何项目文件。"
    return (
        "# Delegated Task\n\n"
        f"- taskType: `{task_type}`\n"
        f"- scopeDecision: `{decision}`\n\n"
        "## Scope protocol\n\n"
        f"{scope_instruction}\n\n"
        "## Output protocol\n\n"
        f"{output_instruction}\n\n"
        "## Task\n\n"
        f"{task.rstrip()}\n"
    )


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def archive_previous_run(directory: str) -> str | None:
    root = Path(directory).resolve()
    existing: list[Path] = []
    for name in RUN_CONTROL_FILES:
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            raise HarnessError(f"refusing symlinked control file: {path}")
        resolved = path.resolve()
        if resolved.parent != root or not resolved.is_file():
            raise HarnessError(f"invalid control file: {path}")
        existing.append(resolved)
    if not existing:
        return None

    history_root = root / RUN_HISTORY_DIRECTORY
    if history_root.exists() or history_root.is_symlink():
        if history_root.is_symlink():
            raise HarnessError(f"refusing symlinked run history: {history_root}")
        resolved_history = history_root.resolve()
        if resolved_history.parent != root or not resolved_history.is_dir():
            raise HarnessError(f"invalid run history directory: {history_root}")
    else:
        history_root.mkdir(mode=0o700)
    try:
        history_root.chmod(0o700)
    except OSError:
        pass

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = history_root / f"{timestamp}-{uuid.uuid4().hex[:8]}"
    archive.mkdir(mode=0o700)
    for source in existing:
        os.replace(source, archive / source.name)
    return str(archive)


def reject_running_sessions_for_cwd(
    client: HarnessClient,
    directory: str,
    allowed_session_id: str | None = None,
) -> None:
    root = Path(directory).resolve()
    running_ids: list[str] = []
    for item in client.sessions():
        session_cwd = item.get("cwd")
        if item.get("running") is not True or not isinstance(session_cwd, str):
            continue
        try:
            same_directory = Path(session_cwd).expanduser().resolve() == root
        except OSError:
            same_directory = False
        if same_directory:
            session_id = item.get("sessionId")
            if session_id == allowed_session_id:
                continue
            running_ids.append(session_id if isinstance(session_id, str) else "unknown")
    if running_ids:
        raise HarnessError(
            "refusing to reuse cwd while a Harness session is still running: "
            + ", ".join(running_ids)
        )


def delegate_lock_path(directory: str) -> Path:
    digest = hashlib.sha256(str(Path(directory).resolve()).encode("utf-8")).hexdigest()
    lock_root = state_directory() / DELEGATE_LOCK_DIRECTORY
    lock_root.mkdir(mode=0o700, exist_ok=True)
    try:
        lock_root.chmod(0o700)
    except OSError:
        pass
    return lock_root / f"{digest}.lock"


@contextmanager
def delegate_directory_lock(directory: str) -> Any:
    path = delegate_lock_path(directory)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise HarnessError(f"cannot open delegation lock for {directory}: {exc}") from exc
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise HarnessError(f"invalid delegation lock for {directory}")
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise HarnessError(
                    f"another Harness prompting command is already using {directory}"
                ) from exc
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            if metadata.st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise HarnessError(
                    f"another Harness prompting command is already using {directory}"
                ) from exc
        else:  # pragma: no cover - unsupported Python platform
            raise HarnessError("this platform has no supported file-locking API")
        locked = True
        yield
    finally:
        if locked:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows fallback
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


def summary(item: dict[str, Any]) -> dict[str, Any]:
    projections = item.get("projections")
    values = projections.get("values") if isinstance(projections, dict) else None
    title = values.get("title") if isinstance(values, dict) else None
    return {
        "sessionId": item.get("sessionId"),
        "title": title if isinstance(title, str) else None,
        "running": bool(item.get("running")),
        "blank": bool(item.get("blank")),
        "cwd": item.get("cwd"),
        "agentPreset": item.get("agentPreset"),
        "updatedAt": item.get("updatedAt"),
    }


def event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def message_text(content: Any) -> str:
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            chunks.append(block["text"])
    return "\n".join(chunks).strip()


def max_event_seq(events: list[dict[str, Any]]) -> int:
    sequences = [event.get("seq") for event in events if isinstance(event.get("seq"), int)]
    return max(sequences, default=-1)


def prompt_event_seq(events: list[dict[str, Any]], rpc_id: str) -> int | None:
    for event in sorted(events, key=lambda value: value.get("seq", -1)):
        if event.get("type") != "user/message":
            continue
        source = event_data(event).get("source")
        if isinstance(source, dict) and source.get("rpcId") == rpc_id:
            seq = event.get("seq")
            return seq if isinstance(seq, int) else None
    return None


def turn_for_rpc(events: list[dict[str, Any]], rpc_id: str) -> int | None:
    current_turn: int | None = None
    for event in sorted(events, key=lambda value: value.get("seq", -1)):
        kind = event.get("type")
        data = event_data(event)
        if kind == "turn/start" and isinstance(data.get("turn"), int):
            current_turn = data["turn"]
        elif kind == "turn/end":
            current_turn = None
        elif kind == "user/message":
            source = data.get("source")
            if isinstance(source, dict) and source.get("rpcId") == rpc_id:
                return current_turn
    return None


def completed_turn(events: list[dict[str, Any]], turn: int) -> dict[str, Any] | None:
    ending: dict[str, Any] | None = None
    texts: list[str] = []
    for event in sorted(events, key=lambda value: value.get("seq", -1)):
        data = event_data(event)
        if data.get("turn") != turn:
            continue
        if event.get("type") == "assistant/message":
            message = data.get("message")
            if isinstance(message, dict):
                text = message_text(message.get("content"))
                if text:
                    texts.append(text)
        elif event.get("type") == "turn/end":
            ending = event
    if ending is None:
        return None
    reason = event_data(ending).get("reason")
    completion_reason = reason.get("kind") if isinstance(reason, dict) else None
    return {
        "status": "completed" if completion_reason == "completed" else "ended",
        "turn": turn,
        "completionReason": completion_reason,
        "completionDetail": reason if isinstance(reason, dict) else None,
        "text": "\n".join(texts),
        "turnEndSeq": ending.get("seq"),
    }


def last_completed_turn(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    endings: list[tuple[int, int]] = []
    for event in events:
        if event.get("type") == "turn/end":
            turn = event_data(event).get("turn")
            seq = event.get("seq")
            if isinstance(turn, int) and isinstance(seq, int):
                endings.append((seq, turn))
    return completed_turn(events, max(endings)[1]) if endings else None


def first_completed_turn_after(
    events: list[dict[str, Any]], baseline: int
) -> dict[str, Any] | None:
    endings: list[tuple[int, int]] = []
    for event in events:
        if event.get("type") != "turn/end":
            continue
        turn = event_data(event).get("turn")
        seq = event.get("seq")
        if isinstance(turn, int) and isinstance(seq, int) and seq > baseline:
            endings.append((seq, turn))
    return completed_turn(events, min(endings)[1]) if endings else None


def running_state(client: HarnessClient, session_id: str) -> bool | None:
    for item in client.sessions():
        if item.get("sessionId") == session_id:
            return bool(item.get("running"))
    return None


def wait_for_prompt(
    client: HarnessClient,
    session_id: str,
    rpc_id: str,
    timeout: float | None,
    baseline: int | None = None,
    allow_baseline_fallback: bool = False,
) -> dict[str, Any]:
    started_at = time.monotonic()
    deadline = started_at + timeout if timeout is not None else None
    next_health_check = started_at
    target_turn: int | None = None
    last_running: bool | None = None
    inactive_since: float | None = None
    while True:
        events = client.history(session_id)
        if baseline is None:
            prompt_seq = prompt_event_seq(events, rpc_id)
            if prompt_seq is not None:
                baseline = prompt_seq - 1
        if target_turn is None:
            target_turn = turn_for_rpc(events, rpc_id)
        if baseline is not None and target_turn is not None:
            result = completed_turn(events, target_turn)
            if result is not None and isinstance(result.get("turnEndSeq"), int) and result["turnEndSeq"] > baseline:
                return {
                    "sessionId": session_id,
                    "rpcId": rpc_id,
                    "baselineSeq": baseline,
                    **result,
                }
        elif baseline is not None and allow_baseline_fallback:
            result = first_completed_turn_after(events, baseline)
            if result is not None:
                return {
                    "sessionId": session_id,
                    "rpcId": rpc_id,
                    "baselineSeq": baseline,
                    **result,
                }
        now = time.monotonic()
        if now >= next_health_check:
            last_running = running_state(client, session_id)
            next_health_check = now + HEALTH_CHECK_INTERVAL
            if last_running is True:
                inactive_since = None
            elif inactive_since is None:
                inactive_since = now
            elif now - inactive_since >= INACTIVE_GRACE:
                return {
                    "status": "stalled",
                    "sessionId": session_id,
                    "rpcId": rpc_id,
                    "baselineSeq": baseline,
                    "targetTurn": target_turn,
                    "running": last_running,
                    "waitReason": "session-not-running-without-turn-end",
                    "guidance": (
                        "Harness stopped reporting this session as running without a matching turn/end. "
                        "The task was not cancelled; inspect status and the Web UI before retrying or cancelling."
                    ),
                }
        if deadline is not None and now >= deadline:
            return {
                "status": "pending",
                "sessionId": session_id,
                "rpcId": rpc_id,
                "baselineSeq": baseline,
                "targetTurn": target_turn,
                "running": last_running,
                "waitReason": "client-deadline-reached",
                "guidance": (
                    "The client wait deadline ended without cancelling the Harness task. "
                    "Continue with wait using the same sessionId and rpcId, and inspect status or the Web UI only if progress appears stalled."
                ),
            }
        time.sleep(POLL_INTERVAL)


def create_session(client: HarnessClient, args: argparse.Namespace) -> dict[str, Any]:
    if args.preset == "minimal":
        raise HarnessError("refusing unsafe minimal preset")
    cwd = require_directory(args.cwd)
    payload: dict[str, Any] = {"cwd": cwd, "agentPreset": args.preset}
    _, value = client.rpc("session.create", payload)
    if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
        raise HarnessError("session.create returned an invalid value")
    session_id = value["sessionId"]
    model = getattr(args, "model", MODELS[0])
    selected = client.select_model(
        session_id,
        model,
        getattr(args, "reasoning_effort", None),
    )
    if getattr(args, "title", None):
        client.rpc("session.rename", {"sessionId": session_id, "title": args.title})
    return {
        "sessionId": session_id,
        "preset": value.get("agentPreset", args.preset),
        "model": selected.get("model", model),
        "provider": selected.get("provider", "deepseek-official"),
        "reasoningEffort": selected.get("reasoningEffort"),
        "cwd": cwd,
        "title": getattr(args, "title", None),
    }


def send_prompt(
    client: HarnessClient,
    session_id: str,
    text: str,
    wait: bool,
    timeout: float | None,
    allow_baseline_fallback: bool = False,
) -> dict[str, Any]:
    baseline = max_event_seq(client.history(session_id))
    rpc_id, value = client.rpc(
        "session.prompt",
        {
            "sessionId": session_id,
            "mode": "queue",
            "content": [{"type": "text", "text": text}],
        },
    )
    if not isinstance(value, dict) or value.get("accepted") is not True:
        raise HarnessError("session.prompt was not accepted")
    if not wait:
        return {
            "status": "accepted",
            "sessionId": session_id,
            "rpcId": rpc_id,
            "baselineSeq": baseline,
        }
    return wait_for_prompt(
        client,
        session_id,
        rpc_id,
        timeout,
        baseline,
        allow_baseline_fallback,
    )


def session_directory(client: HarnessClient, session_id: str) -> str:
    for item in client.sessions():
        if item.get("sessionId") != session_id:
            continue
        cwd = item.get("cwd")
        if not isinstance(cwd, str):
            raise HarnessError(f"session has no valid cwd: {session_id}")
        return require_directory(cwd)
    raise HarnessError(f"session not found: {session_id}")


def send_task(client: HarnessClient, args: argparse.Namespace) -> dict[str, Any]:
    task = read_task(args)
    cwd = session_directory(client, args.session_id)
    with delegate_directory_lock(cwd):
        reject_running_sessions_for_cwd(client, cwd, args.session_id)
        was_running = running_state(client, args.session_id)
        current = (
            read_status_file(cwd)
            if read_control_file(cwd, "STATUS.json") is not None
            else None
        )
        outcome = send_prompt(
            client,
            args.session_id,
            task,
            not getattr(args, "no_wait", False),
            args.timeout,
        )
        if (
            current is None
            or was_running is True
            or current.get("sessionId") != args.session_id
            or current.get("status") not in {"error", "failed", "pending", "stalled"}
        ):
            return outcome
        status_payload = record_delegate_outcome(
            cwd,
            outcome,
            model=current.get("model"),
            reasoning_effort=current.get("reasoningEffort"),
            preset=current.get("preset"),
            scope=current.get("scope"),
            previous_run_archive=current.get("previousRunArchive"),
        )
        return {
            **outcome,
            "delegateStatus": status_payload["status"],
            "files": delegate_files(cwd, current.get("previousRunArchive")),
        }


def run_task(
    client: HarnessClient,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    task = read_task(args)
    cwd = require_directory(args.cwd)
    with delegate_directory_lock(cwd):
        reject_running_sessions_for_cwd(client, cwd)
        created = create_session(client, args)
        outcome = send_prompt(
            client,
            created["sessionId"],
            task,
            not args.no_wait,
            args.timeout,
            True,
        )
    return created, outcome


def write_status_file(
    cwd: str,
    status: str,
    session_id: str | None,
    reason: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "sessionId": session_id,
        "reason": reason,
        "updatedAt": utc_timestamp(),
        **extra,
    }
    atomic_write_text(cwd, "STATUS.json", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return payload


def read_status_file(cwd: str) -> dict[str, Any]:
    raw = read_control_file(cwd, "STATUS.json")
    if raw is None:
        raise HarnessError(f"STATUS.json not found in {cwd}")
    try:
        status = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HarnessError(f"invalid STATUS.json in {cwd}") from exc
    if not isinstance(status, dict):
        raise HarnessError(f"STATUS.json must contain an object: {cwd}")
    return status


def delegate_files(cwd: str, previous_run_archive: Any) -> dict[str, Any]:
    return {
        "task": str(Path(cwd) / "TASK.md"),
        "scope": str(Path(cwd) / "SCOPE.md"),
        "result": str(Path(cwd) / "RESULT.md"),
        "status": str(Path(cwd) / "STATUS.json"),
        "previousRunArchive": previous_run_archive,
    }


def record_delegate_outcome(
    cwd: str,
    outcome: dict[str, Any],
    *,
    model: Any,
    reasoning_effort: Any,
    preset: Any,
    scope: Any,
    previous_run_archive: Any,
) -> dict[str, Any]:
    outcome_status = outcome.get("status")
    if outcome_status in ("completed", "ended"):
        result_text = str(outcome.get("text", ""))
        if read_control_file(cwd, "RESULT.md") is None:
            atomic_write_text(cwd, "RESULT.md", result_text.rstrip() + ("\n" if result_text else ""))
    completion_reason = outcome.get("completionReason")
    if outcome_status == "completed":
        status = "done"
        reason = "completed"
    elif outcome_status == "accepted":
        status = "running"
        reason = "prompt-accepted"
    elif outcome_status == "pending":
        status = "running" if outcome.get("running") else "pending"
        reason = str(outcome.get("waitReason") or "waiting")
    elif outcome_status == "stalled":
        status = "stalled"
        reason = str(outcome.get("waitReason") or "stalled")
    else:
        status = "failed"
        reason = str(completion_reason or outcome_status or "unknown")
    return write_status_file(
        cwd,
        status,
        str(outcome.get("sessionId")) if outcome.get("sessionId") else None,
        reason,
        model=model,
        reasoningEffort=reasoning_effort,
        preset=preset,
        scope=scope,
        rpcId=outcome.get("rpcId"),
        baselineSeq=outcome.get("baselineSeq"),
        completionReason=completion_reason,
        previousRunArchive=previous_run_archive,
    )


def _delegate_task_locked(
    client: HarnessClient,
    args: argparse.Namespace,
    cwd: str,
) -> dict[str, Any]:
    task = read_task(args)
    if args.preset == "minimal":
        raise HarnessError("refusing unsafe minimal preset")
    task_type, decision = classify_scope(args.scope, cwd, task)
    reject_running_sessions_for_cwd(client, cwd)
    previous_run_archive = archive_previous_run(cwd)
    atomic_write_text(cwd, "SCOPE.md", scope_document(cwd, task_type, decision))
    atomic_write_text(cwd, "TASK.md", task_document(task, task_type, decision))
    session_id: str | None = None
    try:
        created = create_session(client, args)
        session_id = created["sessionId"]
        write_status_file(
            cwd,
            "running",
            session_id,
            "prompt-pending",
            model=created["model"],
            reasoningEffort=created.get("reasoningEffort"),
            preset=created["preset"],
            scope=task_type,
            previousRunArchive=previous_run_archive,
        )
        prompt = (
            "先读取当前工作目录中的 SCOPE.md 和 TASK.md，再严格按其中范围执行任务。"
            "需要范围外路径时停止并写 ASK.md；完成后写 RESULT.md，可选写 OPINION.md。"
        )
        should_wait = getattr(args, "wait", False) or args.timeout is not None
        outcome = send_prompt(
            client,
            session_id,
            prompt,
            should_wait,
            args.timeout,
            True,
        )
        status_payload = record_delegate_outcome(
            cwd,
            outcome,
            model=created["model"],
            reasoning_effort=created.get("reasoningEffort"),
            preset=created["preset"],
            scope=task_type,
            previous_run_archive=previous_run_archive,
        )
        return {
            **created,
            **outcome,
            "scope": task_type,
            "scopeDecision": decision,
            "delegateStatus": status_payload["status"],
            "files": delegate_files(cwd, previous_run_archive),
        }
    except (HarnessError, OSError) as exc:
        write_status_file(
            cwd,
            "error",
            session_id,
            str(exc),
            scope=task_type,
            previousRunArchive=previous_run_archive,
        )
        raise


def delegate_task(client: HarnessClient, args: argparse.Namespace) -> dict[str, Any]:
    cwd = ensure_directory(args.cwd)
    with delegate_directory_lock(cwd):
        return _delegate_task_locked(client, args, cwd)


def collect_delegate(client: HarnessClient, args: argparse.Namespace) -> dict[str, Any]:
    cwd = require_directory(args.cwd)
    with delegate_directory_lock(cwd):
        current = read_status_file(cwd)
        session_id = current.get("sessionId")
        rpc_id = current.get("rpcId")
        if not isinstance(session_id, str) or not isinstance(rpc_id, str):
            raise HarnessError("STATUS.json does not contain a collectable sessionId and rpcId")
        if current.get("status") == "done" and current.get("completionReason") == "completed":
            return {
                "status": "completed",
                "sessionId": session_id,
                "rpcId": rpc_id,
                "completionReason": "completed",
                "delegateStatus": "done",
                "files": delegate_files(cwd, current.get("previousRunArchive")),
            }
        baseline = current.get("baselineSeq")
        outcome = wait_for_prompt(
            client,
            session_id,
            rpc_id,
            args.timeout,
            baseline if isinstance(baseline, int) else None,
            True,
        )
        status_payload = record_delegate_outcome(
            cwd,
            outcome,
            model=current.get("model"),
            reasoning_effort=current.get("reasoningEffort"),
            preset=current.get("preset"),
            scope=current.get("scope"),
            previous_run_archive=current.get("previousRunArchive"),
        )
        return {
            **outcome,
            "delegateStatus": status_payload["status"],
            "files": delegate_files(cwd, current.get("previousRunArchive")),
        }


def read_back(directory: str) -> dict[str, Any]:
    cwd = require_directory(directory)
    return {
        "cwd": cwd,
        "files": {
            name: content
            for name in CONTROL_FILES
            if (content := read_control_file(cwd, name)) is not None
        },
    }


def directory_status(client: HarnessClient, directory: str) -> dict[str, Any]:
    cwd = require_directory(directory)
    status = read_status_file(cwd)
    session_id = status.get("sessionId")
    running = running_state(client, session_id) if isinstance(session_id, str) else None
    return {"cwd": cwd, "status": status, "running": running}


def state_directory() -> Path:
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        user_key = str(getuid())
    else:  # pragma: no cover - exercised through a simulated Windows test
        home = str(Path.home().resolve())
        user_key = hashlib.sha256(home.encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"deepseek-harness-delegate-{user_key}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def state_file() -> Path:
    return state_directory() / "server.json"


def write_state(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    fd = os.open(state_file(), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, encoded)
    finally:
        os.close(fd)


def process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def start_server(client: HarnessClient, args: argparse.Namespace) -> dict[str, Any]:
    try:
        status = client.probe_root()
        client.sessions()
        if args.open_ui:
            webbrowser.open(client.base_url)
        return {"status": "already-running", "url": client.base_url, "httpStatus": status}
    except HarnessError:
        pass

    executable = shutil.which("dsh")
    if executable is None:
        raise HarnessError("dsh is not installed or not on PATH")
    cwd = require_directory(args.cwd)
    parsed = urlsplit(client.base_url)
    port = parsed.port or 80
    env = os.environ.copy()
    env["DSH_TELEMETRY_MODE"] = "DISABLED"
    env["DSH_TELEMETRY_DISABLED"] = "1"
    runtime = state_directory()
    dsh_home = Path(args.dsh_home).expanduser().resolve() if args.dsh_home is not None else runtime / "dsh-home"
    dsh_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    env["DSH_HOME"] = str(dsh_home)
    log_path = runtime / "server.log"
    log_fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    log_handle = os.fdopen(log_fd, "a", encoding="utf-8")
    process = subprocess.Popen(
        [executable, "web", "--port", str(port)],
        cwd=cwd,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    log_handle.close()

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise HarnessError(f"dsh web exited with {process.returncode}: {tail}")
        try:
            status = client.probe_root()
            client.sessions()
            payload = {"pid": process.pid, "url": client.base_url, "cwd": cwd}
            write_state(payload)
            if args.open_ui:
                webbrowser.open(client.base_url)
            return {
                "status": "started",
                "url": client.base_url,
                "httpStatus": status,
                "pid": process.pid,
                "cwd": cwd,
                "log": str(log_path),
            }
        except HarnessError:
            time.sleep(0.25)

    process.send_signal(signal.SIGINT)
    raise HarnessError(f"dsh web did not become ready within {START_TIMEOUT:g} seconds")


def stop_server(client: HarnessClient) -> dict[str, Any]:
    path = state_file()
    if not path.exists():
        raise HarnessError("no server owned by this script; refusing to stop an unmanaged process")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        pid = int(state["pid"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HarnessError("invalid owned-server state file") from exc
    if state.get("url") != client.base_url:
        raise HarnessError("owned server URL differs; pass its original --base-url to stop it")
    if not pid_alive(pid):
        path.unlink(missing_ok=True)
        return {"status": "already-stopped", "pid": pid, "url": state.get("url")}
    command = process_command(pid)
    if "dsh" not in command or "web" not in command:
        raise HarnessError("owned PID no longer looks like dsh web; refusing to signal it")
    try:
        client.probe_root()
    except HarnessError:
        # An owned but unresponsive process has no queryable session state and
        # may still need to be stopped for recovery.
        pass
    else:
        running_ids = [
            item.get("sessionId") if isinstance(item.get("sessionId"), str) else "unknown"
            for item in client.sessions()
            if item.get("running") is True
        ]
        if running_ids:
            raise HarnessError(
                "refusing to stop dsh web while Harness sessions are still running: "
                + ", ".join(running_ids)
            )
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + 10.0
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if pid_alive(pid):
        raise HarnessError("dsh web did not stop after SIGINT; refusing escalation")
    path.unlink(missing_ok=True)
    return {"status": "stopped", "pid": pid, "url": state.get("url", client.base_url)}


def add_text_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Task text supplied directly")
    group.add_argument("--text-file", help="UTF-8 task file, or - for stdin")


def add_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd", required=True, help="Existing task working directory")
    parser.add_argument(
        "--preset",
        choices=("standard", "code", "cordis", "minimal"),
        default="standard",
        help="Agent preset; minimal is rejected at runtime",
    )
    parser.add_argument(
        "--model",
        choices=MODELS,
        default=MODELS[0],
        help=(
            "Model for the new session (default: deepseek-v4-pro); RC.7 also "
            "persists this as the deployment-wide default"
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        help=(
            "Optional DeepSeek reasoning effort; omit to use the adapter default. "
            "RC.7 persists the resolved effort with the deployment-wide model default."
        ),
    )
    parser.add_argument("--title", help="Optional session title")


def add_wait_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help=(
            "Optional client-side wait deadline; omit to wait until the matching "
            "turn/end. Reaching the deadline does not cancel the Harness task."
        ),
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "--base-url",
        default=os.environ.get("DEEPSEEK_HARNESS_URL", DEFAULT_BASE_URL),
        help=f"Loopback Harness URL (default: {DEFAULT_BASE_URL})",
    )
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("probe", help="Check Web and API readiness")
    commands.add_parser("list", help="List concise session summaries")

    create = commands.add_parser("create", help="Create an idle session")
    add_create_arguments(create)

    send = commands.add_parser("send", help="Send a prompt to an existing session")
    send.add_argument("session_id")
    add_text_arguments(send)
    add_wait_timeout_argument(send)
    send.add_argument("--no-wait", action="store_true", help="Return after the prompt is accepted")

    run = commands.add_parser("run", help="Create a session, send a prompt, and wait")
    add_create_arguments(run)
    add_text_arguments(run)
    add_wait_timeout_argument(run)
    run.add_argument("--no-wait", action="store_true")

    delegate = commands.add_parser(
        "delegate",
        help="Submit a scoped file-channel task and return after acceptance",
    )
    add_create_arguments(delegate)
    add_text_arguments(delegate)
    add_wait_timeout_argument(delegate)
    delegate.add_argument("--scope", choices=SCOPES, default="auto")
    delegate.add_argument(
        "--wait",
        action="store_true",
        help="Wait for completion instead of returning after acceptance",
    )

    collect = commands.add_parser(
        "collect",
        help="Collect and finalize the current directory's delegated task",
    )
    collect.add_argument("--cwd", required=True)
    add_wait_timeout_argument(collect)

    wait = commands.add_parser("wait", help="Wait for one accepted prompt")
    wait.add_argument("session_id")
    wait.add_argument("--rpc-id", required=True)
    wait.add_argument("--baseline-seq", type=int)
    wait.add_argument(
        "--baseline-fallback",
        action="store_true",
        help="Allow first-turn-after-baseline recovery only when no earlier turn can finish after that baseline",
    )
    add_wait_timeout_argument(wait)

    result = commands.add_parser("result", help="Read the last completed turn")
    result.add_argument("session_id")

    cancel = commands.add_parser("cancel", help="Cancel an active session turn")
    cancel.add_argument("session_id")

    commands.add_parser("open-ui", help="Open the local Harness UI")

    read_back_parser = commands.add_parser("read-back", help="Read RESULT/OPINION/ASK files")
    read_back_parser.add_argument("--cwd", required=True)

    status_parser = commands.add_parser("status", help="Read STATUS.json and live running state")
    status_parser.add_argument("--cwd", required=True)

    start = commands.add_parser("start", help="Start a loopback dsh web instance")
    start.add_argument("--cwd", required=True)
    start.add_argument("--dsh-home", help="Optional intended Harness Home")
    start.add_argument("--open-ui", action="store_true")

    commands.add_parser("stop", help="Stop only a server owned by this script")
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "timeout", None) is not None and args.timeout <= 0:
        raise HarnessError("timeout must be positive")
    client = HarnessClient(args.base_url)

    if args.command == "probe":
        http_status = client.probe_root()
        items = client.sessions()
        emit({"status": "ready", "url": client.base_url, "httpStatus": http_status, "sessions": len(items)})
    elif args.command == "list":
        emit({"sessions": [summary(item) for item in client.sessions()]})
    elif args.command == "create":
        emit({"status": "created", **create_session(client, args)})
    elif args.command == "send":
        outcome = send_task(client, args)
        emit(outcome)
        if outcome.get("status") not in ("accepted", "completed", "pending"):
            return 2
    elif args.command == "run":
        created, outcome = run_task(client, args)
        if args.no_wait:
            emit(
                {
                    "sessionId": outcome["sessionId"],
                    "rpcId": outcome["rpcId"],
                    "baselineSeq": outcome.get("baselineSeq"),
                }
            )
        else:
            emit({**created, **outcome})
        if outcome.get("status") not in ("accepted", "completed", "pending"):
            return 2
    elif args.command == "delegate":
        outcome = delegate_task(client, args)
        emit(outcome)
        if outcome.get("delegateStatus") not in ("done", "running", "pending"):
            return 2
    elif args.command == "collect":
        outcome = collect_delegate(client, args)
        emit(outcome)
        if outcome.get("delegateStatus") not in ("done", "running", "pending"):
            return 2
    elif args.command == "wait":
        outcome = wait_for_prompt(
            client,
            args.session_id,
            args.rpc_id,
            args.timeout,
            args.baseline_seq,
            args.baseline_fallback,
        )
        emit(outcome)
        if outcome.get("status") not in ("completed", "pending"):
            return 2
    elif args.command == "result":
        outcome = last_completed_turn(client.history(args.session_id))
        emit({"sessionId": args.session_id, "result": outcome})
        if outcome is None or outcome.get("status") != "completed":
            return 2
    elif args.command == "cancel":
        _, value = client.rpc("session.cancel", {"sessionId": args.session_id})
        emit({"status": "cancel-requested", "sessionId": args.session_id, "value": value})
    elif args.command == "open-ui":
        client.probe_root()
        client.sessions()
        opened = webbrowser.open(client.base_url)
        emit({"status": "opened" if opened else "open-requested", "url": client.base_url})
    elif args.command == "read-back":
        emit(read_back(args.cwd))
    elif args.command == "status":
        emit(directory_status(client, args.cwd))
    elif args.command == "start":
        emit(start_server(client, args))
    elif args.command == "stop":
        emit(stop_server(client))
    else:
        raise HarnessError(f"unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HarnessError, OSError) as exc:
        emit({"status": "error", "error": str(exc)})
        raise SystemExit(1)
