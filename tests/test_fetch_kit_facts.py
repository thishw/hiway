"""Offline tests for scripts/fetch-kit-facts.py — fixture trees and a fake HTTP layer.

Runs under both ``python3 -m pytest`` and ``python3 -m unittest discover -s tests``.
"""

from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "fetch_kit_facts", HERE.parent / "scripts" / "fetch-kit-facts.py"
)
fkf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fkf)

SHA = "c67cde870b11e0abcffc75bbce4798571ddbcf29"
PRIVACY = (
    "# Privacy Policy — hiway-kit\n\n_Last updated: 2026-09-30_\n\n"
    "hiway-kit is an open-source plugin. "
    + "It collects nothing and makes no network calls. " * 8
    + "\n\n## Contact\n\nOpen an issue.\n"
)
CHANGELOG = """# Changelog

## [2.1.0] — 2026-10-02

### Fixed — newest fix

## [2.0.0] — 2026-09-30

### Changed — something
### Added — another

## [1.0.0] — 2026-09-01

### Added — first
"""


def make_kit(root: Path, version: str = "2.1.0") -> Path:
    def w(rel: str, text: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    w(
        "plugins/common/.claude-plugin/plugin.json",
        json.dumps({"name": "hiway-kit", "version": version}),
    )
    # agents: two real (one nested in a category dir), one helper doc without name:
    w("plugins/common/agents/dev/a.md", "---\nname: a\n---\n")
    w("plugins/common/agents/meta/deep/b.md", "---\nname: b\n---\n")
    w("plugins/common/agents/README.md", "# not an agent\nname appears mid-line: no\n")
    # skills: nested SKILL.md counted, a reference .md not
    w("plugins/common/skills/one/SKILL.md", "---\nname: one\n---\n")
    w("plugins/common/skills/two/SKILL.md", "---\nname: two\n---\n")
    w("plugins/common/skills/two/references/x.md", "ref\n")
    w("plugins/common/skills/three/SKILL.md", "---\nname: three\n---\n")
    # rules: only top-level *.md
    w("plugins/common/rules/r1.md", "r\n")
    w("plugins/common/rules/sub/ignored.md", "r\n")
    w("CHANGELOG.md", CHANGELOG)
    w("PRIVACY.md", PRIVACY)
    return root


def tarball_of(root: Path, prefix: str, comment: str | None = SHA) -> bytes:
    buf = io.BytesIO()
    pax = {"comment": comment} if comment else {}
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers=pax) as tf:
        tf.add(root, arcname=prefix)
    return buf.getvalue()


class FakeHttp:
    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        for key, val in self.routes.items():
            if key in url:
                if isinstance(val, Exception):
                    raise val
                return val
        raise fkf.FactsError(f"GET {url} failed: 404")


class CountTests(unittest.TestCase):
    def test_counts_follow_check_doc_counts_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = fkf.count_actuals(make_kit(Path(tmp)))
        self.assertEqual(c, {"agents": 2, "skills": 3, "rules": 1})

    def test_changelog_takes_newest_entries_and_headings(self):
        cl = fkf.parse_changelog(CHANGELOG, limit=2)
        self.assertEqual([e["version"] for e in cl], ["2.1.0", "2.0.0"])
        self.assertEqual(cl[1]["headings"], ["Changed — something", "Added — another"])
        self.assertEqual(cl[0]["date"], "2026-10-02")

    def test_privacy_drops_title_and_reads_date(self):
        p = fkf.parse_privacy(PRIVACY)
        self.assertEqual(p["updated"], "2026-09-30")
        self.assertFalse(p["markdown"].startswith("#"))
        self.assertIn("## Contact", p["markdown"])


class TagSelectionTests(unittest.TestCase):
    def test_highest_semver_wins_and_non_release_tags_are_ignored(self):
        tags = [
            {"name": "v5.2.1", "commit": {"sha": "a"}},
            {"name": "v5.10.0", "commit": {"sha": "b"}},
            {"name": "v6.0.0-rc1", "commit": {"sha": "c"}},
            {"name": "nightly", "commit": {"sha": "d"}},
        ]
        self.assertEqual(fkf.latest_tag(tags)["name"], "v5.10.0")

    def test_no_release_tag_is_an_error(self):
        with self.assertRaises(fkf.FactsError):
            fkf.latest_tag([{"name": "nightly", "commit": {"sha": "d"}}])


class FromTagTests(unittest.TestCase):
    def routes(self, kit: Path, *, tag="v2.1.0", comment=SHA):
        return {
            "/tags?": json.dumps(
                [
                    {"name": tag, "commit": {"sha": SHA}},
                    {"name": "v1.0.0", "commit": {"sha": "x"}},
                ]
            ).encode(),
            f"/commits/{SHA}": json.dumps(
                {"commit": {"committer": {"date": "2026-10-02T03:00:00Z"}}}
            ).encode(),
            f"/tar.gz/refs/tags/{tag}": tarball_of(kit, "hiway-kit-2.1.0", comment),
        }

    def test_facts_come_from_the_tag_tarball(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = FakeHttp(self.routes(make_kit(Path(tmp) / "kit")))
            facts = fkf.from_tag("This-HW/hiway-kit", http)
        fkf.validate(facts)
        self.assertEqual(
            facts["source"],
            {
                "repo": "This-HW/hiway-kit",
                "mode": "tag",
                "tag": "v2.1.0",
                "commit": SHA,
                "date": "2026-10-02",
            },
        )
        self.assertEqual(facts["counts"], {"agents": 2, "skills": 3, "rules": 1})
        self.assertEqual(facts["version"], "2.1.0")
        self.assertTrue(any("/tar.gz/refs/tags/v2.1.0" in c for c in http.calls))

    def test_tarball_from_another_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = FakeHttp(self.routes(make_kit(Path(tmp) / "kit"), comment="f" * 40))
            with self.assertRaisesRegex(fkf.FactsError, "tarball commit"):
                fkf.from_tag("This-HW/hiway-kit", http)

    def test_tarball_without_commit_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = FakeHttp(self.routes(make_kit(Path(tmp) / "kit"), comment=None))
            with self.assertRaisesRegex(fkf.FactsError, "tarball commit"):
                fkf.from_tag("This-HW/hiway-kit", http)

    def test_link_inside_plugins_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = make_kit(Path(tmp) / "kit")
            (kit / "plugins/common/skills/four").mkdir()
            (kit / "plugins/common/skills/four/SKILL.md").symlink_to(kit / "plugins/common/skills/one/SKILL.md")
            http = FakeHttp(self.routes(kit))
            with self.assertRaisesRegex(fkf.FactsError, "link inside plugins"):
                fkf.from_tag("This-HW/hiway-kit", http)

    def test_failure_removes_facts_from_an_earlier_run(self):
        http = FakeHttp({"/tags?": fkf.FactsError("GET tags failed: offline")})
        with mock.patch.object(fkf, "http_get", http), tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "kit.json"
            out.write_text('{"stale": true}', encoding="utf-8")
            self.assertEqual(fkf.main(["--out", str(out)]), 1)
            self.assertFalse(out.exists(), "stale facts must not survive a failed fetch")

    def test_network_failure_fails_the_build(self):
        http = FakeHttp({"/tags?": fkf.FactsError("GET tags failed: timed out")})
        rc = self._main_with(http)
        self.assertEqual(rc, 1)

    def test_tag_that_disagrees_with_plugin_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            http = FakeHttp(self.routes(make_kit(Path(tmp) / "kit", version="2.0.9")))
            facts = fkf.from_tag("This-HW/hiway-kit", http)
        with self.assertRaisesRegex(fkf.FactsError, "does not match plugin version"):
            fkf.validate(facts)

    def _main_with(self, http) -> int:
        with mock.patch.object(fkf, "http_get", http), tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "kit.json"
            rc = fkf.main(["--out", str(out)])
            self.assertFalse(out.exists(), "a failed fetch must not leave a data file behind")
            return rc


class SchemaTests(unittest.TestCase):
    def good(self) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            return fkf.collect(
                make_kit(Path(tmp)),
                {
                    "repo": "r",
                    "mode": "tag",
                    "tag": "v2.1.0",
                    "commit": SHA,
                    "date": "2026-10-02",
                },
            )

    def test_good_facts_pass(self):
        fkf.validate(self.good())

    def test_zero_count_fails(self):
        f = self.good()
        f["counts"]["rules"] = 0
        with self.assertRaisesRegex(fkf.FactsError, "counts.rules"):
            fkf.validate(f)

    def test_non_integer_count_fails(self):
        f = self.good()
        f["counts"]["agents"] = "15"
        with self.assertRaisesRegex(fkf.FactsError, "counts.agents"):
            fkf.validate(f)

    def test_missing_privacy_fails(self):
        f = self.good()
        f["privacy"] = {}
        with self.assertRaisesRegex(fkf.FactsError, "privacy"):
            fkf.validate(f)

    def test_changelog_behind_version_fails(self):
        f = self.good()
        f["changelog"] = f["changelog"][1:]
        with self.assertRaisesRegex(fkf.FactsError, "newest CHANGELOG"):
            fkf.validate(f)


class FromPathTests(unittest.TestCase):
    def test_local_checkout_without_git_still_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts = fkf.from_path(make_kit(Path(tmp)))
        fkf.validate(facts)
        self.assertEqual(facts["source"]["mode"], "local")
        self.assertEqual(facts["counts"]["skills"], 3)

    def test_missing_directory_fails(self):
        rc = fkf.main(
            ["--from-path", "/nonexistent/kit", "--out", "/nonexistent/out.json"]
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
