from __future__ import annotations

import re
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
        script = ROOT / "scripts" / "dsh_harness.py"
        self.assertTrue(script.stat().st_mode & 0o111)


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
