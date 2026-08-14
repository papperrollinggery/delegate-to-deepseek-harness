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
