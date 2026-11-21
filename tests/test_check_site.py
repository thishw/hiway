"""Offline tests for scripts/check_site.py."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "check_site", HERE.parent / "scripts" / "check_site.py"
)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


class HandNumbersTests(unittest.TestCase):
    def run_on(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return cs.hand_numbers(tree(Path(tmp), files))

    def test_counts_in_both_languages_and_orders_are_caught(self):
        for text in (
            "ships 15 agents",
            "15 specialized agents",
            "Rules (12)",
            "스킬 15개",
            "15개의 에이전트",
            "규칙 12종",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.run_on({"content/a.md": text}), text)

    def test_review_bypasses_are_caught(self):
        for text in (
            "**15** agents",
            "에이전트 **15개**",
            "<strong>15</strong> agents",
            "15&nbsp;agents",
            "12개 거버넌스 룰",
            "거버넌스 룰 **12개**",
            "15 review agents",
            "15 subagents",
            "agents: 15",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.run_on({"content/a.md": text}), text)

    def test_versions_in_short_forms_and_config_are_caught(self):
        self.assertTrue(self.run_on({"layouts/a.html": "v5.2"}))
        self.assertTrue(self.run_on({"layouts/a.html": "5.2.x"}))
        self.assertTrue(self.run_on({"hugo.toml": 'description = "ships 15 agents"'}))
        self.assertTrue(self.run_on({"assets/css/main.css": '.x::after { content: "15 skills"; }'}))

    def test_version_tail_is_not_a_count(self):
        self.assertEqual(self.run_on({"content/blog/p.md": "v2.18.0부터 각 규칙, removed in v2.17.0 the git-workflow agent"}), [])

    def test_shortcodes_and_unrelated_numbers_pass(self):
        ok = 'The release ships {{< kit "agents" >}} agents. P0 to P3. Six reviewers, 3 rounds, python3 3.9.'
        self.assertEqual(
            self.run_on(
                {"content/a.md": ok, "layouts/x.html": '<rect x="194" y="78">'}
            ),
            [],
        )

    def test_version_outside_blog_fails_but_blog_history_is_allowed(self):
        self.assertTrue(self.run_on({"layouts/home.html": "v5.2.1"}))
        self.assertTrue(self.run_on({"i18n/en.toml": 'x = "5.2.1"'}))
        self.assertEqual(self.run_on({"content/blog/p.md": "removed in v2.16.0"}), [])


class OriginTests(unittest.TestCase):
    def run_on(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            return cs.origins(tree(Path(tmp), files))

    def test_same_origin_and_relative_pass(self):
        html = (
            '<link rel="stylesheet" href="/css/site.css"><script src="/js/t.js"></script>'
            '<link rel="canonical" href="https://hiway.thishw.com/">'
            '<link rel="alternate" hreflang="ko" href="https://hiway.thishw.com/ko/">'
            '<a href="https://github.com/This-HW/hiway-kit">source</a>'
        )
        self.assertEqual(
            self.run_on(
                {
                    "index.html": html,
                    "css/site.css": "@font-face{src:url(/fonts/a.woff2)}",
                }
            ),
            [],
        )

    def test_each_kind_of_foreign_load_fails(self):
        cases = {
            "script": '<script src="https://cdn.example.com/x.js"></script>',
            "stylesheet": '<link rel="stylesheet" href="//fonts.googleapis.com/css2?family=X">',
            "preconnect": '<link rel="preconnect" href="https://fonts.gstatic.com">',
            "img": '<img src="https://example.com/p.png" alt="">',
            "inline style": '<div style="background:url(https://example.com/b.png)"></div>',
            "style block": "<style>@import url('https://example.com/a.css');</style>",
            "tracker": "<script>gtag('config','G-1')</script>",
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                self.assertTrue(self.run_on({"index.html": html}), name)

    def test_review_origin_bypasses_fail(self):
        cases = {
            "base": '<base href="https://evil.example/">',
            "backslash": '<script src="/\\evil.example/x.js"></script>',
            "http same host": '<script src="http://hiway.thishw.com/x.js"></script>',
            "svg image": '<svg><image href="https://evil.example/p.png"/></svg>',
            "prerender": '<link rel="prerender" href="https://evil.example/">',
            "inline fetch": '<script>fetch("https://evil.example/p")</script>',
        }
        for name, html in cases.items():
            with self.subTest(name=name):
                self.assertTrue(self.run_on({"index.html": html}), name)

    def test_script_file_calling_out_fails(self):
        self.assertTrue(self.run_on({"index.html": "", "js/t.js": 'import("https://evil.example/m.js")'}))

    def test_css_font_from_cdn_fails(self):
        self.assertTrue(
            self.run_on(
                {
                    "index.html": "",
                    "css/site.css": "@font-face{src:url(https://cdn.jsdelivr.net/a.woff2)}",
                }
            )
        )

    def test_ads_txt_fails(self):
        self.assertTrue(
            self.run_on({"index.html": "", "ads.txt": "google.com, pub-1, DIRECT"})
        )


FAKE_CHROME = """#!{python}
# Stands in for Chrome: fetches the page from the check's local server (so the measuring
# script must have been appended), then reports a width that depends on the page text.
import sys, urllib.request
page = urllib.request.urlopen(sys.argv[-1]).read().decode()
if "addEventListener('load'" not in page:
    sys.exit(0)
if "NOMEASURE" in page:
    print("<html><title>x</title></html>")
else:
    width = 470 if "WIDE" in page else 390
    print("<html><title>ovf|%d|390|pre.code</title></html>" % width)
"""


class OverflowTests(unittest.TestCase):
    def run_on(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            chrome = Path(tmp) / "fake-chrome"
            chrome.write_text(FAKE_CHROME.format(python=sys.executable), encoding="utf-8")
            chrome.chmod(chrome.stat().st_mode | stat.S_IEXEC)
            public = tree(Path(tmp) / "public", files)
            return cs.overflow(public, str(chrome))

    def test_page_wider_than_the_window_fails(self):
        problems = self.run_on({"index.html": "<p>ok</p>", "docs/a/index.html": "<p>WIDE</p>"})
        self.assertEqual(len(problems), 1)
        self.assertIn("docs/a/index.html: 470px wide in a 390px window", problems[0])
        self.assertIn("pre.code", problems[0])

    def test_fitting_pages_pass(self):
        self.assertEqual(self.run_on({"index.html": "<p>ok</p>", "b/index.html": "<p>ok</p>"}), [])

    def test_alias_redirect_pages_are_skipped(self):
        alias = "<meta http-equiv=refresh content=\"0; url=https://hiway.thishw.com/x/\">WIDE"
        self.assertEqual(self.run_on({"index.html": "<p>ok</p>", "posts/x/index.html": alias}), [])

    def test_unmeasurable_page_fails(self):
        problems = self.run_on({"index.html": "<p>NOMEASURE</p>"})
        self.assertEqual(len(problems), 1)
        self.assertIn("could not be measured", problems[0])

    def test_missing_build_output_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(cs.overflow(Path(tmp) / "nope", "unused"))

    def test_no_chrome_is_exit_2_not_a_silent_pass(self):
        old = {k: os.environ.get(k) for k in ("CHROME", "PATH")}
        os.environ["CHROME"], os.environ["PATH"] = "", ""
        try:
            self.assertIsNone(cs.find_chrome())
            self.assertEqual(cs.main(["overflow", "--public", "nowhere"]), 2)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


KIT_README = """# hiway-kit

## Quick Install

## Where it runs

### What's Included

## Other Harnesses (Codex · Antigravity · Gemini CLI)

## 핵심 개념 & AI 엔지니어링 로직

## [Start here](#start-here) `now`

## Notes
## Notes

<a id="custom-anchor"></a>

```bash
# Not A Heading
```
"""

KIT_FILES = {
    "README.md": KIT_README,
    "docs/harnesses.md": "# Harnesses\n\n## Codex\n",
    "plugins/common/agents/review-code.md": "---\nname: review-code\n---\n",
    "plugins/common/skills/plan-task/SKILL.md": "---\nname: plan-task\n---\n",
}
URL = "https://github.com/This-HW/hiway-kit"


def home(*paths: str) -> str:
    items = "".join(f'    - where:\n        path: "{p}"\n' for p in paths)
    return f"---\nfeatures:\n  items:\n{items}---\n"


class GithubSlugTests(unittest.TestCase):
    def test_anchors_match_github(self):
        anchors = cs.md_anchors(KIT_README)
        for a in (
            "quick-install",
            "where-it-runs",
            "whats-included",
            "other-harnesses-codex--antigravity--gemini-cli",
            "핵심-개념--ai-엔지니어링-로직",
            "start-here-now",
            "notes",
            "notes-1",
            "custom-anchor",
        ):
            with self.subTest(anchor=a):
                self.assertIn(a, anchors)

    def test_headings_inside_code_fences_make_no_anchor(self):
        self.assertNotIn("not-a-heading", cs.md_anchors(KIT_README))


class KitLinksTests(unittest.TestCase):
    def run_on(self, content: dict[str, str]) -> tuple[int, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            kit = tree(Path(tmp) / "kit", KIT_FILES)
            site = tree(Path(tmp) / "site", content)
            return cs.kit_links(site, kit, "vtest")

    def test_links_that_exist_pass(self):
        checked, problems = self.run_on(
            {
                "content/_index.en.md": home(
                    "tree/plugins/common/skills/plan-task",
                    "blob/plugins/common/agents/review-code.md",
                    "blob/README.md#where-it-runs",
                ),
                "content/blog/a.en.md": (
                    f"[r]({URL}/blob/main/plugins/common/agents/review-code.md) and "
                    f"[h]({URL}/blob/main/docs/harnesses.md#codex) and "
                    f"[k]({URL}/blob/main/README.md#%ED%95%B5%EC%8B%AC-%EA%B0%9C%EB%85%90--ai-%EC%97%94%EC%A7%80%EB%8B%88%EC%96%B4%EB%A7%81-%EB%A1%9C%EC%A7%81) "
                    f"[s]({URL}/tree/main/plugins/common/skills/plan-task/)\n"
                ),
            }
        )
        self.assertEqual(problems, [])
        self.assertEqual(checked, 7)

    def test_each_kind_of_broken_link_fails_with_file_and_line(self):
        cases = {
            "blob/plugins/common/agents/dev/review-code.md": "no such file",
            "tree/plugins/common/skills/gone": "no such directory",
            "blob/plugins/common/skills/plan-task": "is a directory",
            "tree/README.md": "is a file",
            "blob/README.md#other-harnesses-codex--antigravity": "no heading in README.md makes anchor",
            "blob/README.md#not-a-heading": "no heading in README.md makes anchor",
            "blob/../site/content/_index.en.md": "leaves the kit checkout",
        }
        for path, why in cases.items():
            with self.subTest(path=path):
                _, problems = self.run_on({"content/_index.en.md": home("blob/README.md", path)})
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith("content/_index.en.md:7: "), problems[0])
                self.assertIn(path, problems[0])
                self.assertIn("at vtest", problems[0])
                self.assertIn(why, problems[0])

    def test_broken_url_in_prose_fails(self):
        _, problems = self.run_on(
            {"content/docs/x.ko.md": f"line one\n[a]({URL}/blob/main/plugins/common/agents/dev/review-code.md)\n"}
        )
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("content/docs/x.ko.md:2: blob/plugins/common/agents/dev/review-code.md"))

    def test_symlink_out_of_the_checkout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = tree(Path(tmp) / "kit", KIT_FILES)
            secret = tree(Path(tmp) / "outside", {"secret.md": "# Secret\n"}) / "secret.md"
            (kit / "docs/escape.md").symlink_to(secret)
            site = tree(Path(tmp) / "site", {"content/a.md": f"{URL}/blob/main/docs/escape.md#secret\n"})
            _, problems = cs.kit_links(site, kit, "vtest")
        self.assertEqual(len(problems), 1)
        self.assertIn("leaves the kit checkout", problems[0])

    def test_other_repositories_and_non_kit_paths_are_ignored(self):
        checked, problems = self.run_on(
            {
                "content/a.md": "https://github.com/thishw/hiway/blob/main/nope.md\n"
                "https://github.com/This-HW/hiway-kit\n"
                '  path: "docs/getting-started"\n'
            }
        )
        self.assertEqual((checked, problems), (0, []))


def kit_tarball(files: dict[str, str], sha: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        root = tree(Path(tmp) / "kit", files)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT, pax_headers={"comment": sha}) as tf:
            tf.add(root, arcname="hiway-kit-x")
        return buf.getvalue()


class KitLinksMainTests(unittest.TestCase):
    """The command line: exit codes and which kit tree is read."""

    def main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            rc = cs.main(list(argv))
        return rc, out.getvalue()

    def test_from_path_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = tree(Path(tmp) / "kit", KIT_FILES)
            good = tree(Path(tmp) / "good", {"content/_index.en.md": home("blob/README.md#where-it-runs")})
            bad = tree(Path(tmp) / "bad", {"content/_index.en.md": home("blob/README.md#gone")})
            rc, out = self.main("kit-links", "--root", str(good), "--from-path", str(kit))
            self.assertEqual(rc, 0, out)
            self.assertIn("1 link checked against", out)
            rc, out = self.main("kit-links", "--root", str(bad), "--from-path", str(kit))
            self.assertEqual(rc, 1, out)
            self.assertIn("content/_index.en.md:5: blob/README.md#gone", out)
            rc, out = self.main("kit-links", "--root", str(good), "--from-path", str(Path(tmp) / "missing"))
            self.assertEqual(rc, 2, out)

    def tag_mode(self, routes: dict, *argv: str) -> tuple[int, str]:
        fkf = cs._load_fetch_kit_facts()

        def get(url: str) -> bytes:
            for key, val in routes.items():
                if key in url:
                    return val
            raise fkf.FactsError(f"GET {url} failed: 404")

        fkf.http_get = get
        with mock.patch.object(cs, "_load_fetch_kit_facts", lambda: fkf):
            return self.main("kit-links", *argv)

    def test_default_reads_the_newest_release_tag_and_tag_pins_another(self):
        new, old = "a" * 40, "b" * 40
        routes = {
            "/tags?": json.dumps(
                [{"name": "v1.0.0", "commit": {"sha": old}}, {"name": "v2.0.0", "commit": {"sha": new}}]
            ).encode(),
            "/refs/tags/v2.0.0": kit_tarball(KIT_FILES, new),
            "/refs/tags/v1.0.0": kit_tarball({"README.md": "# Old\n"}, old),
        }
        with tempfile.TemporaryDirectory() as tmp:
            site = tree(Path(tmp) / "site", {"content/_index.en.md": home("blob/README.md#where-it-runs")})
            rc, out = self.tag_mode(routes, "--root", str(site))
            self.assertEqual(rc, 0, out)
            self.assertIn("checked against v2.0.0", out)
            rc, out = self.tag_mode(routes, "--root", str(site), "--tag", "v1.0.0")
            self.assertEqual(rc, 1, out)
            self.assertIn("at v1.0.0: no heading in README.md makes anchor #where-it-runs", out)
            rc, out = self.tag_mode(routes, "--root", str(site), "--tag", "v9.9.9")
            self.assertEqual(rc, 2, out)

    def test_kit_that_cannot_be_fetched_is_exit_2_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = tree(Path(tmp) / "site", {"content/a.md": "no links\n"})
            rc, out = self.tag_mode({}, "--root", str(site))
        self.assertEqual(rc, 2, out)
        self.assertIn("cannot read the kit", out)


if __name__ == "__main__":
    unittest.main()
