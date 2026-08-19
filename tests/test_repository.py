from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SkillMetadataTests(unittest.TestCase):
    def test_skill_frontmatter_has_only_supported_keys(self) -> None:
        source = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(source.startswith("---\n"))
        frontmatter = source.split("---", 2)[1]
        keys = [
            line.split(":", 1)[0]
            for line in frontmatter.splitlines()
            if line and not line.startswith((" ", "\t"))
        ]
        self.assertEqual(keys, ["name", "description"])
        self.assertIn("name: delegate-to-deepseek-harness", frontmatter)
        self.assertLessEqual(len(source.splitlines()), 500)

    def test_openai_metadata_matches_skill(self) -> None:
        source = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$delegate-to-deepseek-harness", source)
        match = re.search(r'^  short_description: "([^"]+)"$', source, re.MULTILINE)
        self.assertIsNotNone(match)
        description = match.group(1) if match is not None else ""
        self.assertGreaterEqual(len(description), 25)
        self.assertLessEqual(len(description), 64)

    def test_runtime_script_is_executable(self) -> None:
        for relative in (
            "scripts/dsh_harness.py",
            "scripts/check-update.sh",
            "scripts/install-global.sh",
            "scripts/update-global.sh",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).stat().st_mode & 0o111)

    def test_version_is_stable_semver(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")


class UpdateAndInstallTests(unittest.TestCase):
    def test_update_check_notifies_throttles_and_fails_silently(self) -> None:
        if shutil.which("curl") is None:
            self.skipTest("curl is unavailable")
        script = ROOT / "scripts" / "check-update.sh"
        local_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

        def run(cache: Path, version_file: Path, **extra: str) -> subprocess.CompletedProcess[str]:
            env = {
                **os.environ,
                "XDG_CACHE_HOME": str(cache),
                "DSH_UPDATE_URL": version_file.as_uri(),
                **extra,
            }
            return subprocess.run(
                ["bash", str(script)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            newer = root / "newer"
            newer.write_text('{"tag_name": "v9.9.9"}\n', encoding="utf-8")
            same = root / "same"
            same.write_text(
                '{"tag_name": "v' + local_version + '"}\n', encoding="utf-8"
            )

            first = run(root / "cache-new", newer)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("v9.9.9", first.stdout)
            self.assertIn("Ask the user whether to update", first.stdout)
            second = run(root / "cache-new", newer)
            self.assertEqual(second.stdout, "")

            current = run(root / "cache-same", same)
            self.assertEqual(current.returncode, 0, current.stderr)
            self.assertEqual(current.stdout, "")

            disabled = run(root / "cache-disabled", newer, DSH_DISABLE_UPDATE_CHECK="1")
            self.assertEqual(disabled.stdout, "")

            missing = run(root / "cache-missing", root / "missing")
            self.assertEqual(missing.returncode, 0, missing.stderr)
            self.assertEqual(missing.stdout, "")

            no_home_env = {
                "PATH": os.environ.get("PATH", ""),
                "DSH_UPDATE_URL": newer.as_uri(),
            }
            no_home = subprocess.run(
                ["bash", str(script)],
                check=False,
                capture_output=True,
                text=True,
                env=no_home_env,
            )
            self.assertEqual(no_home.returncode, 0, no_home.stderr)
            self.assertEqual(no_home.stdout, "")

    def test_global_installer_copies_only_runtime_artifacts(self) -> None:
        if shutil.which("rsync") is None:
            self.skipTest("rsync is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "install-global.sh")],
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "CODEX_HOME": str(codex_home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = codex_home / "skills" / "delegate-to-deepseek-harness"
            runtime_files = (
                "VERSION",
                "SKILL.md",
                "agents/openai.yaml",
                "scripts/dsh_harness.py",
                "scripts/check-update.sh",
                "scripts/install-global.sh",
                "scripts/update-global.sh",
            )
            for relative in runtime_files:
                with self.subTest(relative=relative):
                    self.assertEqual(
                        (installed / relative).read_bytes(),
                        (ROOT / relative).read_bytes(),
                    )
            self.assertFalse((installed / "README.md").exists())

    def test_approved_updater_installs_matching_release_archive(self) -> None:
        if shutil.which("curl") is None or shutil.which("rsync") is None:
            self.skipTest("curl or rsync is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
            version_file = root / "remote-version"
            version_file.write_text(
                '{"tag_name": "v' + version + '"}\n', encoding="utf-8"
            )
            archive_path = root / "release.tar.gz"
            runtime_files = (
                "VERSION",
                "SKILL.md",
                "agents/openai.yaml",
                "scripts/dsh_harness.py",
                "scripts/check-update.sh",
                "scripts/install-global.sh",
                "scripts/update-global.sh",
            )
            with tarfile.open(archive_path, "w:gz") as archive:
                for relative in runtime_files:
                    archive.add(
                        ROOT / relative,
                        arcname=f"delegate-to-deepseek-harness-{version}/{relative}",
                    )

            codex_home = root / "codex-home"
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "update-global.sh")],
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "CODEX_HOME": str(codex_home),
                    "DSH_UPDATE_URL": version_file.as_uri(),
                    "DSH_UPDATE_ARCHIVE_URL": archive_path.as_uri(),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = codex_home / "skills" / "delegate-to-deepseek-harness"
            self.assertEqual(
                (installed / "VERSION").read_text(encoding="utf-8").strip(),
                version,
            )
            self.assertEqual(
                (installed / "scripts" / "dsh_harness.py").read_bytes(),
                (ROOT / "scripts" / "dsh_harness.py").read_bytes(),
            )


class DocumentationTests(unittest.TestCase):
    DOCUMENTS = (
        "README.md",
        "README.zh-CN.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/use-cases.md",
        "docs/use-cases.zh-CN.md",
    )

    def test_relative_markdown_links_resolve(self) -> None:
        link_pattern = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
        missing: list[str] = []
        for relative in self.DOCUMENTS:
            document = ROOT / relative
            source = document.read_text(encoding="utf-8")
            for raw_target in link_pattern.findall(source):
                target = raw_target.strip().split("#", 1)[0]
                if not target or "://" in target or target.startswith(("#", "mailto:")):
                    continue
                resolved = (document.parent / target).resolve()
                if not resolved.exists():
                    missing.append(f"{relative}: {raw_target}")
        self.assertEqual(missing, [])

    def test_language_navigation_is_bidirectional(self) -> None:
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("README.zh-CN.md", english)
        self.assertIn("README.md", chinese)
        self.assertIn("docs/use-cases.md", english)
        self.assertIn("docs/use-cases.zh-CN.md", chinese)


if __name__ == "__main__":
    unittest.main()
