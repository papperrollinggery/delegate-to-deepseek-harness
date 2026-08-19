from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dsh_harness.py"
SPEC = importlib.util.spec_from_file_location("dsh_harness", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
dsh_harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsh_harness)


class LoopbackUrlTests(unittest.TestCase):
    def test_accepts_literal_loopback(self) -> None:
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 3080)),
        ]
        with mock.patch.object(
            dsh_harness.socket, "getaddrinfo", return_value=resolved
        ):
            self.assertEqual(
                dsh_harness.loopback_base_url("http://localhost:3080"),
                "http://localhost:3080",
            )

    def test_renders_ipv6_loopback(self) -> None:
        resolved = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 3080, 0, 0)),
        ]
        with mock.patch.object(
            dsh_harness.socket, "getaddrinfo", return_value=resolved
        ):
            self.assertEqual(
                dsh_harness.loopback_base_url("http://[::1]:3080"),
                "http://[::1]:3080",
            )

    def test_rejects_non_loopback_host(self) -> None:
        with self.assertRaisesRegex(dsh_harness.HarnessError, "non-loopback"):
            dsh_harness.loopback_base_url("http://192.0.2.10:3080")

    def test_rejects_https_credentials_and_paths(self) -> None:
        invalid_urls = (
            "https://127.0.0.1:3080",
            "http://user:pass@127.0.0.1:3080",
            "http://127.0.0.1:3080/api",
        )
        for value in invalid_urls:
            with self.subTest(value=value), self.assertRaises(dsh_harness.HarnessError):
                dsh_harness.loopback_base_url(value)

    def test_rejects_loopback_name_resolving_elsewhere(self) -> None:
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 3080)),
        ]
        with (
            mock.patch.object(dsh_harness.socket, "getaddrinfo", return_value=resolved),
            self.assertRaisesRegex(dsh_harness.HarnessError, "non-loopback"),
        ):
            dsh_harness.loopback_base_url("http://localhost:3080")


class WaitBehaviorTests(unittest.TestCase):
    @staticmethod
    def running_events(rpc_id: str) -> list[dict[str, object]]:
        return [
            {"seq": 1, "type": "turn/start", "data": {"turn": 4}},
            {
                "seq": 2,
                "type": "user/message",
                "data": {"turn": 4, "source": {"rpcId": rpc_id}},
            },
        ]

    def test_default_wait_has_no_wall_clock_deadline(self) -> None:
        rpc_id = "rpc-long-task"
        running = self.running_events(rpc_id)
        completed = running + [
            {
                "seq": 3,
                "type": "assistant/message",
                "data": {
                    "turn": 4,
                    "message": {"content": [{"type": "text", "text": "done"}]},
                },
            },
            {
                "seq": 4,
                "type": "turn/end",
                "data": {"turn": 4, "reason": {"kind": "completed"}},
            },
        ]
        client = mock.Mock()
        client.history.side_effect = [running, completed]
        client.sessions.return_value = [{"sessionId": "session-1", "running": True}]

        with mock.patch.object(dsh_harness.time, "sleep"):
            outcome = dsh_harness.wait_for_prompt(
                client, "session-1", rpc_id, timeout=None
            )

        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["text"], "done")

    def test_explicit_wait_deadline_returns_pending_without_cancelling(self) -> None:
        rpc_id = "rpc-still-running"
        client = mock.Mock()
        client.history.return_value = self.running_events(rpc_id)
        client.sessions.return_value = [{"sessionId": "session-2", "running": True}]

        with mock.patch.object(
            dsh_harness.time, "monotonic", side_effect=[100.0, 102.0]
        ):
            outcome = dsh_harness.wait_for_prompt(
                client, "session-2", rpc_id, timeout=1.0
            )

        self.assertEqual(outcome["status"], "pending")
        self.assertTrue(outcome["running"])
        self.assertEqual(outcome["waitReason"], "client-deadline-reached")
        self.assertIn("without cancelling", outcome["guidance"])

    def test_wait_reports_stalled_when_session_stops_without_turn_end(self) -> None:
        rpc_id = "rpc-stalled"
        client = mock.Mock()
        client.history.return_value = self.running_events(rpc_id)
        client.sessions.return_value = [{"sessionId": "session-3", "running": False}]

        with (
            mock.patch.object(dsh_harness, "HEALTH_CHECK_INTERVAL", 0.0),
            mock.patch.object(dsh_harness, "INACTIVE_GRACE", 1.0),
            mock.patch.object(
                dsh_harness.time,
                "monotonic",
                side_effect=[100.0, 100.0, 102.0],
            ),
            mock.patch.object(dsh_harness.time, "sleep"),
        ):
            outcome = dsh_harness.wait_for_prompt(
                client, "session-3", rpc_id, timeout=None
            )

        self.assertEqual(outcome["status"], "stalled")
        self.assertFalse(outcome["running"])
        self.assertEqual(
            outcome["waitReason"], "session-not-running-without-turn-end"
        )
        self.assertIn("not cancelled", outcome["guidance"])

    def test_persisted_baseline_survives_prompt_event_history_rollover(self) -> None:
        client = mock.Mock()
        client.history.return_value = [
            {
                "seq": 249,
                "type": "assistant/message",
                "data": {
                    "turn": 8,
                    "message": {
                        "content": [{"type": "text", "text": "late result"}]
                    },
                },
            },
            {
                "seq": 250,
                "type": "turn/end",
                "data": {"turn": 8, "reason": {"kind": "completed"}},
            },
        ]

        outcome = dsh_harness.wait_for_prompt(
            client,
            "session-rollover",
            "rpc-no-longer-in-history",
            timeout=None,
            baseline=100,
            allow_baseline_fallback=True,
        )

        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["turn"], 8)
        self.assertEqual(outcome["text"], "late result")
        client.sessions.assert_not_called()

    def test_synchronous_new_session_wait_survives_history_rollover(self) -> None:
        client = mock.Mock()
        client.history.side_effect = [
            [{"seq": 5, "type": "session/start", "data": {}}],
            [
                {
                    "seq": 249,
                    "type": "assistant/message",
                    "data": {
                        "turn": 2,
                        "message": {
                            "content": [{"type": "text", "text": "sync result"}]
                        },
                    },
                },
                {
                    "seq": 250,
                    "type": "turn/end",
                    "data": {"turn": 2, "reason": {"kind": "completed"}},
                },
            ],
        ]
        client.rpc.return_value = ("sync-rpc", {"accepted": True})

        outcome = dsh_harness.send_prompt(
            client,
            "new-session",
            "long task",
            wait=True,
            timeout=None,
            allow_baseline_fallback=True,
        )

        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["baselineSeq"], 5)
        self.assertEqual(outcome["text"], "sync result")


class ServiceLifecycleTests(unittest.TestCase):
    def test_stop_refuses_while_any_harness_session_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "server.json"
            state.write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "url": "http://127.0.0.1:3080",
                        "cwd": "/tmp/owner",
                    }
                ),
                encoding="utf-8",
            )
            client = mock.Mock()
            client.base_url = "http://127.0.0.1:3080"
            client.probe_root.return_value = 200
            client.sessions.return_value = [
                {
                    "sessionId": "other-running-session",
                    "cwd": "/tmp/other-task",
                    "running": True,
                }
            ]

            with (
                mock.patch.object(dsh_harness, "state_file", return_value=state),
                mock.patch.object(dsh_harness, "pid_alive", return_value=True),
                mock.patch.object(
                    dsh_harness,
                    "process_command",
                    return_value="node dsh web --port 3080",
                ),
                mock.patch.object(dsh_harness.os, "kill") as kill,
                self.assertRaisesRegex(
                    dsh_harness.HarnessError, "Harness sessions are still running"
                ),
            ):
                dsh_harness.stop_server(client)

            kill.assert_not_called()

    def test_stop_allows_recovery_of_an_owned_unresponsive_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "server.json"
            state.write_text(
                json.dumps(
                    {
                        "pid": 12345,
                        "url": "http://127.0.0.1:3080",
                        "cwd": "/tmp/owner",
                    }
                ),
                encoding="utf-8",
            )
            client = mock.Mock()
            client.base_url = "http://127.0.0.1:3080"
            client.probe_root.side_effect = dsh_harness.HarnessError("offline")

            with (
                mock.patch.object(dsh_harness, "state_file", return_value=state),
                mock.patch.object(
                    dsh_harness, "pid_alive", side_effect=[True, False, False]
                ),
                mock.patch.object(
                    dsh_harness,
                    "process_command",
                    return_value="node dsh web --port 3080",
                ),
                mock.patch.object(dsh_harness.os, "kill") as kill,
            ):
                result = dsh_harness.stop_server(client)

            self.assertEqual(result["status"], "stopped")
            client.sessions.assert_not_called()
            kill.assert_called_once_with(12345, dsh_harness.signal.SIGINT)


class ScopeAndFileTests(unittest.TestCase):
    def test_auto_scope_uses_proposal_language_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".git").mkdir()
            scope, reason = dsh_harness.classify_scope(
                "auto",
                directory,
                "Review only; do not modify project files.",
            )
        self.assertEqual(scope, "proposal-only")
        self.assertEqual(reason, "auto:proposal-language")

    def test_auto_scope_detects_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "pyproject.toml").touch()
            scope, reason = dsh_harness.classify_scope(
                "auto", directory, "Fix the parser"
            )
        self.assertEqual(scope, "cross-file")
        self.assertEqual(reason, "auto:project-root-marker")

    def test_proposal_scope_limits_write_targets(self) -> None:
        document = dsh_harness.scope_document(
            "/tmp/example", "proposal-only", "explicit"
        )
        self.assertIn('"./RESULT.md"', document)
        self.assertIn('"./OPINION.md"', document)
        self.assertIn('"./ASK.md"', document)
        self.assertNotIn('  - "./**"\nread:', document)
        self.assertIn('"**/.dsh-delegation-history/**"', document)

    def test_atomic_write_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = dsh_harness.atomic_write_text(
                directory, "RESULT.md", "done\n"
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), "done\n")
            self.assertEqual(
                dsh_harness.read_control_file(directory, "RESULT.md"), "done\n"
            )

    def test_refuses_symlinked_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.txt"
            target.write_text("data", encoding="utf-8")
            (root / "RESULT.md").symlink_to(target)
            with self.assertRaisesRegex(dsh_harness.HarnessError, "symlinked"):
                dsh_harness.read_control_file(directory, "RESULT.md")

    def test_rejects_home_and_relative_working_directories(self) -> None:
        with self.assertRaises(dsh_harness.HarnessError):
            dsh_harness.require_directory(str(Path.home()))
        with self.assertRaises(dsh_harness.HarnessError):
            dsh_harness.require_directory("relative/path")

    def test_archives_every_previous_run_control_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in dsh_harness.RUN_CONTROL_FILES:
                (root / name).write_text(f"old {name}\n", encoding="utf-8")

            archive_value = dsh_harness.archive_previous_run(directory)

            self.assertIsNotNone(archive_value)
            archive = Path(archive_value or "")
            self.assertEqual(archive.parent.name, dsh_harness.RUN_HISTORY_DIRECTORY)
            for name in dsh_harness.RUN_CONTROL_FILES:
                self.assertFalse((root / name).exists())
                self.assertEqual(
                    (archive / name).read_text(encoding="utf-8"),
                    f"old {name}\n",
                )

    def test_archive_validation_fails_before_moving_any_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "RESULT.md"
            result.write_text("previous result\n", encoding="utf-8")
            target = root / "target.txt"
            target.write_text("data\n", encoding="utf-8")
            (root / "ASK.md").symlink_to(target)

            with self.assertRaisesRegex(dsh_harness.HarnessError, "symlinked"):
                dsh_harness.archive_previous_run(directory)

            self.assertEqual(result.read_text(encoding="utf-8"), "previous result\n")


class DelegateTaskTests(unittest.TestCase):
    def test_state_directory_has_stable_fallback_without_getuid(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(dsh_harness.os, "getuid", None),
            mock.patch.object(
                dsh_harness.tempfile, "gettempdir", return_value=directory
            ),
        ):
            first = dsh_harness.state_directory()
            second = dsh_harness.state_directory()

        self.assertEqual(first, second)
        self.assertEqual(first.parent, Path(directory))
        self.assertTrue(first.name.startswith("deepseek-harness-delegate-"))

    def test_windows_locking_fallback_is_reachable(self) -> None:
        fake_msvcrt = mock.Mock(LK_NBLCK=1, LK_UNLCK=2)
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(dsh_harness, "fcntl", None),
            mock.patch.object(dsh_harness, "msvcrt", fake_msvcrt),
            mock.patch.object(
                dsh_harness, "state_directory", return_value=Path(directory)
            ),
            dsh_harness.delegate_directory_lock("/example/project"),
        ):
            pass

        self.assertEqual(fake_msvcrt.locking.call_count, 2)
        self.assertEqual(fake_msvcrt.locking.call_args_list[0].args[1:], (1, 1))
        self.assertEqual(fake_msvcrt.locking.call_args_list[1].args[1:], (2, 1))

    def test_same_directory_lock_rejects_concurrent_delegate(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            dsh_harness.delegate_directory_lock(directory),
            self.assertRaisesRegex(
                dsh_harness.HarnessError, "another Harness prompting command"
            ),
            dsh_harness.delegate_directory_lock(directory),
        ):
            self.fail("a concurrent lock must not be acquired")

    def test_run_uses_the_same_directory_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                cwd=directory,
                text="Low-level task",
                text_file=None,
                preset="standard",
                model="deepseek-v4-pro",
                title="Run lock test",
                timeout=1.0,
                no_wait=False,
            )
            client = mock.Mock()

            with (
                dsh_harness.delegate_directory_lock(directory),
                mock.patch.object(dsh_harness, "create_session") as create_session,
                self.assertRaisesRegex(
                    dsh_harness.HarnessError, "another Harness prompting command"
                ),
            ):
                dsh_harness.run_task(client, args)

            create_session.assert_not_called()

    def test_send_allows_target_but_rejects_other_running_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                session_id="target-session",
                text="Follow-up task",
                text_file=None,
                timeout=1.0,
            )
            target = {
                "sessionId": "target-session",
                "cwd": directory,
                "running": True,
            }
            other = {
                "sessionId": "other-session",
                "cwd": directory,
                "running": True,
            }
            client = mock.Mock()
            client.sessions.return_value = [target]
            completed = {
                "status": "completed",
                "sessionId": "target-session",
                "rpcId": "follow-up-rpc",
                "completionReason": "completed",
                "text": "done",
            }

            with mock.patch.object(
                dsh_harness, "send_prompt", return_value=completed
            ) as send_prompt:
                self.assertEqual(dsh_harness.send_task(client, args), completed)
            send_prompt.assert_called_once()

            client.sessions.return_value = [target, other]
            with (
                mock.patch.object(dsh_harness, "send_prompt") as send_prompt,
                self.assertRaisesRegex(dsh_harness.HarnessError, "still running"),
            ):
                dsh_harness.send_task(client, args)
            send_prompt.assert_not_called()

    def test_send_recovers_matching_file_channel_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dsh_harness.write_status_file(
                directory,
                "error",
                "recover-session",
                "connection refused",
                model="deepseek-v4-pro",
                preset="code",
                scope="proposal-only",
                previousRunArchive="/tmp/previous",
            )
            args = argparse.Namespace(
                session_id="recover-session",
                text="Resume interrupted review",
                text_file=None,
                timeout=None,
                no_wait=True,
            )
            client = mock.Mock()
            client.sessions.return_value = [
                {
                    "sessionId": "recover-session",
                    "cwd": directory,
                    "running": False,
                }
            ]
            accepted = {
                "status": "accepted",
                "sessionId": "recover-session",
                "rpcId": "recovery-rpc",
                "baselineSeq": 12,
            }

            with mock.patch.object(
                dsh_harness, "send_prompt", return_value=accepted
            ):
                outcome = dsh_harness.send_task(client, args)

            self.assertEqual(outcome["delegateStatus"], "running")
            status = dsh_harness.read_status_file(directory)
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["reason"], "prompt-accepted")
            self.assertEqual(status["rpcId"], "recovery-rpc")
            self.assertEqual(status["baselineSeq"], 12)

    def test_send_fails_before_prompting_when_file_channel_status_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "STATUS.json").write_text("not-json\n", encoding="utf-8")
            args = argparse.Namespace(
                session_id="invalid-status-session",
                text="Do not send this",
                text_file=None,
                timeout=None,
                no_wait=True,
            )
            client = mock.Mock()
            client.sessions.return_value = [
                {
                    "sessionId": "invalid-status-session",
                    "cwd": directory,
                    "running": False,
                }
            ]

            with (
                mock.patch.object(dsh_harness, "send_prompt") as send_prompt,
                self.assertRaisesRegex(dsh_harness.HarnessError, "invalid STATUS.json"),
            ):
                dsh_harness.send_task(client, args)

            send_prompt.assert_not_called()

    def test_queued_send_does_not_replace_active_file_channel_rpc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dsh_harness.write_status_file(
                directory,
                "running",
                "active-session",
                "prompt-accepted",
                model="deepseek-v4-pro",
                preset="standard",
                scope="proposal-only",
                rpcId="active-rpc",
                baselineSeq=3,
            )
            args = argparse.Namespace(
                session_id="active-session",
                text="Queue a later follow-up",
                text_file=None,
                timeout=None,
                no_wait=True,
            )
            client = mock.Mock()
            client.sessions.return_value = [
                {
                    "sessionId": "active-session",
                    "cwd": directory,
                    "running": True,
                }
            ]
            accepted = {
                "status": "accepted",
                "sessionId": "active-session",
                "rpcId": "queued-rpc",
                "baselineSeq": 9,
            }

            with mock.patch.object(
                dsh_harness, "send_prompt", return_value=accepted
            ):
                outcome = dsh_harness.send_task(client, args)

            self.assertEqual(outcome, accepted)
            current = dsh_harness.read_status_file(directory)
            self.assertEqual(current["rpcId"], "active-rpc")
            self.assertEqual(current["baselineSeq"], 3)

    def test_running_session_blocks_reuse_before_archiving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "RESULT.md"
            result.write_text("previous result\n", encoding="utf-8")
            args = argparse.Namespace(
                cwd=directory,
                text="Create a current result",
                text_file=None,
                scope="proposal-only",
                preset="standard",
                model="deepseek-v4-pro",
                title="Active-session regression test",
                timeout=1.0,
            )
            client = mock.Mock()
            client.sessions.return_value = [
                {
                    "sessionId": "previous-active-session",
                    "cwd": directory,
                    "running": True,
                }
            ]

            with (
                mock.patch.object(dsh_harness, "create_session") as create_session,
                self.assertRaisesRegex(dsh_harness.HarnessError, "still running"),
            ):
                dsh_harness.delegate_task(client, args)

            create_session.assert_not_called()
            self.assertEqual(result.read_text(encoding="utf-8"), "previous result\n")
            self.assertFalse((root / dsh_harness.RUN_HISTORY_DIRECTORY).exists())

    def test_unsafe_minimal_is_rejected_before_file_channel_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / "RESULT.md"
            previous.write_text("keep me\n", encoding="utf-8")
            args = argparse.Namespace(
                cwd=directory,
                text="Do not start",
                text_file=None,
                scope="proposal-only",
                preset="minimal",
                model="deepseek-v4-pro",
                title="Rejected preset",
                timeout=None,
                wait=False,
            )
            client = mock.Mock()

            with (
                mock.patch.object(dsh_harness, "create_session") as create_session,
                self.assertRaisesRegex(dsh_harness.HarnessError, "unsafe minimal"),
            ):
                dsh_harness.delegate_task(client, args)

            create_session.assert_not_called()
            client.sessions.assert_not_called()
            self.assertEqual(previous.read_text(encoding="utf-8"), "keep me\n")
            self.assertFalse((root / dsh_harness.RUN_HISTORY_DIRECTORY).exists())
            self.assertFalse((root / "SCOPE.md").exists())
            self.assertFalse((root / "TASK.md").exists())
            self.assertFalse((root / "STATUS.json").exists())

    def test_reusing_cwd_never_returns_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RESULT.md").write_text("old result\n", encoding="utf-8")
            (root / "OPINION.md").write_text("old opinion\n", encoding="utf-8")
            (root / "ASK.md").write_text("old question\n", encoding="utf-8")
            args = argparse.Namespace(
                cwd=directory,
                text="Create a current result",
                text_file=None,
                scope="proposal-only",
                preset="standard",
                model="deepseek-v4-pro",
                title="Regression test",
                timeout=1.0,
            )
            created = {
                "sessionId": "new-session",
                "preset": "standard",
                "model": "deepseek-v4-pro",
                "provider": "deepseek-official",
                "cwd": directory,
                "title": "Regression test",
            }
            completed = {
                "status": "completed",
                "sessionId": "new-session",
                "rpcId": "new-rpc",
                "completionReason": "completed",
                "text": "current result",
            }
            client = mock.Mock()
            client.sessions.return_value = []

            with (
                mock.patch.object(dsh_harness, "create_session", return_value=created),
                mock.patch.object(dsh_harness, "send_prompt", return_value=completed),
            ):
                outcome = dsh_harness.delegate_task(client, args)

            read_back = dsh_harness.read_back(directory)
            self.assertEqual(read_back["files"], {"RESULT.md": "current result\n"})
            archive = Path(outcome["files"]["previousRunArchive"])
            self.assertEqual(
                (archive / "RESULT.md").read_text(encoding="utf-8"), "old result\n"
            )
            self.assertEqual(
                (archive / "OPINION.md").read_text(encoding="utf-8"),
                "old opinion\n",
            )
            self.assertEqual(
                (archive / "ASK.md").read_text(encoding="utf-8"), "old question\n"
            )
            status = json.loads((root / "STATUS.json").read_text(encoding="utf-8"))
            self.assertEqual(status["previousRunArchive"], str(archive))

    def test_delegate_returns_after_acceptance_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(
                cwd=directory,
                text="Long independent task",
                text_file=None,
                scope="proposal-only",
                preset="standard",
                model="deepseek-v4-pro",
                title="Async test",
                timeout=None,
                wait=False,
            )
            created = {
                "sessionId": "async-session",
                "preset": "standard",
                "model": "deepseek-v4-pro",
                "provider": "deepseek-official",
                "cwd": directory,
                "title": "Async test",
            }
            accepted = {
                "status": "accepted",
                "sessionId": "async-session",
                "rpcId": "async-rpc",
                "baselineSeq": 12,
            }
            client = mock.Mock()
            client.sessions.return_value = []

            with (
                mock.patch.object(dsh_harness, "create_session", return_value=created),
                mock.patch.object(dsh_harness, "send_prompt", return_value=accepted) as send_prompt,
            ):
                outcome = dsh_harness.delegate_task(client, args)

            self.assertEqual(outcome["delegateStatus"], "running")
            self.assertFalse(Path(directory, "RESULT.md").exists())
            self.assertFalse(send_prompt.call_args.args[3])
            status = json.loads(Path(directory, "STATUS.json").read_text(encoding="utf-8"))
            self.assertEqual(status["rpcId"], "async-rpc")
            self.assertEqual(status["baselineSeq"], 12)
            self.assertEqual(status["reason"], "prompt-accepted")

    def test_collect_finalizes_async_delegate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dsh_harness.write_status_file(
                directory,
                "running",
                "collect-session",
                "prompt-accepted",
                model="deepseek-v4-pro",
                preset="standard",
                scope="proposal-only",
                rpcId="collect-rpc",
                baselineSeq=7,
                completionReason=None,
                previousRunArchive=None,
            )
            args = argparse.Namespace(cwd=directory, timeout=None)
            completed = {
                "status": "completed",
                "sessionId": "collect-session",
                "rpcId": "collect-rpc",
                "baselineSeq": 7,
                "completionReason": "completed",
                "text": "collected result",
            }

            with mock.patch.object(
                dsh_harness, "wait_for_prompt", return_value=completed
            ):
                outcome = dsh_harness.collect_delegate(mock.Mock(), args)

            self.assertEqual(outcome["delegateStatus"], "done")
            self.assertEqual(
                Path(directory, "RESULT.md").read_text(encoding="utf-8"),
                "collected result\n",
            )
            status = json.loads(Path(directory, "STATUS.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "done")
            self.assertEqual(status["baselineSeq"], 7)
            self.assertEqual(status["completionReason"], "completed")


class TaskInputTests(unittest.TestCase):
    def test_rejects_obvious_secret_pattern(self) -> None:
        fake_secret = "sk-" + ("x" * 20)
        with self.assertRaisesRegex(
            dsh_harness.HarnessError, "appears to contain a secret"
        ):
            dsh_harness.reject_obvious_secrets(f"token={fake_secret}")

    def test_reads_utf8_task_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory, "prompt.txt")
            task_file.write_text("整理这段文案", encoding="utf-8")
            args = argparse.Namespace(text=None, text_file=str(task_file))
            self.assertEqual(dsh_harness.read_task(args), "整理这段文案")


class CliTests(unittest.TestCase):
    def test_help_is_available(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("delegate", result.stdout)
        self.assertIn("read-back", result.stdout)
        self.assertIn("collect", result.stdout)

    def test_delegate_defaults_to_async_without_a_timeout(self) -> None:
        args = dsh_harness.parser().parse_args(
            ["delegate", "--cwd", "/tmp/example", "--text", "task"]
        )
        self.assertFalse(args.wait)
        self.assertIsNone(args.timeout)

    def test_wait_can_explicitly_enable_safe_baseline_fallback(self) -> None:
        args = dsh_harness.parser().parse_args(
            [
                "wait",
                "session-1",
                "--rpc-id",
                "rpc-1",
                "--baseline-seq",
                "4",
                "--baseline-fallback",
            ]
        )
        self.assertTrue(args.baseline_fallback)

    def test_client_deadline_is_successful_for_send_run_and_wait(self) -> None:
        pending = {"status": "pending", "sessionId": "s", "rpcId": "r"}
        cases = (
            (
                ["dsh_harness.py", "send", "s", "--text", "x", "--timeout", "1"],
                "send_task",
                pending,
            ),
            (
                [
                    "dsh_harness.py",
                    "run",
                    "--cwd",
                    "/tmp/example",
                    "--text",
                    "x",
                    "--timeout",
                    "1",
                ],
                "run_task",
                ({}, pending),
            ),
            (
                [
                    "dsh_harness.py",
                    "wait",
                    "s",
                    "--rpc-id",
                    "r",
                    "--timeout",
                    "1",
                ],
                "wait_for_prompt",
                pending,
            ),
        )
        for argv, function_name, outcome in cases:
            with (
                self.subTest(command=argv[1]),
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(dsh_harness, "HarnessClient"),
                mock.patch.object(dsh_harness, function_name, return_value=outcome),
                mock.patch.object(dsh_harness, "emit"),
            ):
                self.assertEqual(dsh_harness.main(), 0)

    def test_non_loopback_cli_fails_closed(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--base-url",
                "http://192.0.2.10:3080",
                "probe",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("non-loopback", payload["error"])


if __name__ == "__main__":
    unittest.main()
