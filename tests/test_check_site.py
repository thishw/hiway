"""Offline tests for scripts/check_site.py."""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
