#!/usr/bin/env python3
"""Site checks that CI runs on every pull request (and you can run locally).

  check_site.py hand-numbers [--root .]     no hand-written counts or versions in sources
  check_site.py origins [--public public]   built pages load nothing from another origin,
                                            and carry no analytics or ad code

Exit 0 = clean, 1 = violations (each printed as file:line). Internal links are checked
separately by htmltest (.htmltest.yml).
"""

from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

SITE_HOST = "hiway.thishw.com"

# --- hand-written numbers ------------------------------------------------------
#
# Counts and the current version must come from data/kit.json. These patterns catch
# a number written next to what it counts, in English and Korean, in either order.
COUNT_NOUN_EN = r"(?:sub-?)?(?:agents?|skills?|rules?|hooks?)"
COUNT_NOUN_KO = r"(?:에이전트|서브에이전트|스킬|규칙|룰|훅)"
COUNT_PATTERNS = [
    # "15 agents", "15 specialized agents", "15 review sub-agents" (up to two words between)
    re.compile(rf"(?<![\d.])\b\d+\s+(?:[A-Za-z][\w-]*\s+){{0,2}}{COUNT_NOUN_EN}\b", re.I),
    # "Rules (12)", "agents: 15"
    re.compile(rf"\b{COUNT_NOUN_EN}\s*(?:\(\s*\d+\s*\)|:\s*\d+\b)", re.I),
    # "15개의 에이전트", "12개 거버넌스 룰", "15 전문 에이전트"
    re.compile(rf"(?<![\d.])\d+\s*(?:개의?|종의?)?\s*(?:[가-힣A-Za-z-]+\s+){{0,2}}{COUNT_NOUN_KO}"),
    # "스킬 15개", "거버넌스 룰 12종"
    re.compile(rf"{COUNT_NOUN_KO}\s*\d+\s*(?:개|종)"),
]
# Emphasis and entities must not hide a number from the patterns ("**15** agents").
NORMALIZE = re.compile(r"\*\*|__|</?(?:strong|b|em|i|span)[^>]*>")
SPACES = re.compile(r"&nbsp;|&#160;|&#xa0;|\u00a0", re.I)
# A release version (X.Y.Z, or X.Y with a v). Blog posts are dated case studies and may name
# the release where something changed, so content/blog is exempt from this one only.
VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+\.(?:\d+|x)\b|\bv\d+\.\d+\b", re.I)
# Every hand-written source that reaches a rendered page. data/kit.json is generated.
SCAN_PATHS = ("content", "layouts", "i18n", "assets", "static", "data", "hugo.toml")
SKIP_FILES = {"data/kit.json"}
VERSION_EXEMPT = ("content/blog/",)
TEXT_SUFFIXES = {".md", ".html", ".toml", ".txt", ".xml", ".json", ".yaml", ".yml", ".css", ".js", ".svg"}


def _files(root: Path):
    for entry in SCAN_PATHS:
        p = root / entry
        if p.is_file():
            yield p
        elif p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.is_file())


def hand_numbers(root: Path) -> list[str]:
    problems: list[str] = []
    for f in _files(root):
        rel = f.relative_to(root).as_posix()
        if f.suffix not in TEXT_SUFFIXES or rel in SKIP_FILES or rel.startswith("static/fonts/"):
            continue
        check_version = not rel.startswith(VERSION_EXEMPT)
        for n, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            line = NORMALIZE.sub("", SPACES.sub(" ", raw))
            for pat in COUNT_PATTERNS:
                for m in pat.finditer(line):
                    problems.append(f"{rel}:{n}: hand-written count {m.group(0)!r}")
            if check_version:
                for m in VERSION_PATTERN.finditer(line):
                    problems.append(f"{rel}:{n}: hand-written version {m.group(0)!r}")
    return problems


# --- external origins ----------------------------------------------------------

# Elements whose URL makes the browser fetch something while rendering the page.
FETCHING = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "iframe": ("src",),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "track": ("src",),
    "input": ("src",),
    "image": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
    "feimage": ("href", "xlink:href"),
    "base": ("href",),
}
# <link> rels that fetch. canonical/alternate are navigation metadata, not fetches.
FETCHING_LINK_RELS = {
    "stylesheet",
    "preload",
    "modulepreload",
    "prefetch",
    "prerender",
    "preconnect",
    "dns-prefetch",
    "icon",
    "manifest",
    "apple-touch-icon",
    "mask-icon",
}
CSS_URL = re.compile(r"""(?:url|image-set|image)\(\s*['"]?([^'")\s,]+)""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*['"]?([^'")\s;]+)""", re.I)
TRACKERS = re.compile(
    r"googletagmanager|google-analytics|gtag\(|adsbygoogle|pagead2\.googlesyndication|plausible\.io|"
    r"cloudflareinsights|static\.hotjar|connect\.facebook\.net|clarity\.ms|umami",
    re.I,
)


def foreign(url: str) -> bool:
    """True when loading ``url`` would leave the site's own HTTPS origin."""
    # Browsers treat "\\" like "/" in URLs, so "/\\evil.example/x" is protocol-relative.
    url = url.strip().replace("\\", "/")
    if not url or url.startswith(("#", "data:", "mailto:", "tel:")):
        return False
    parts = urlsplit(url)
    if url.startswith("//") or parts.scheme in ("http", "https"):
        # Same host over plain http is mixed content — a different origin.
        return parts.hostname != SITE_HOST or parts.scheme == "http"
    return bool(parts.scheme) and parts.scheme not in ("data", "blob")


# A URL literal inside script code (fetch("https://…"), import("//…")).
SCRIPT_URL = re.compile(r"""["'`](?:https?:)?//[^"'`\s]+""", re.I)


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[int, str, str]] = []
        self.inline_css: list[tuple[int, str]] = []
        self.inline_js: list[tuple[int, str]] = []
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        for attr in FETCHING.get(tag, ()):
            for v in (a.get(attr) or "").split(","):
                if v.strip():
                    self.urls.append((line, f"<{tag} {attr}>", v.strip().split()[0]))
        if tag == "link":
            rels = set((a.get("rel") or "").lower().split())
            if rels & FETCHING_LINK_RELS and a.get("href"):
                self.urls.append((line, f"<link rel={a.get('rel')}>", a["href"]))
        if a.get("style"):
            self.inline_css.append((line, a["style"]))
        if tag in ("style", "script"):
            self._in = tag

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "style":
            self.inline_css.append((self.getpos()[0], data))
        elif self._in == "script":
            self.inline_js.append((self.getpos()[0], data))


def css_urls(text: str) -> list[str]:
    return CSS_URL.findall(text) + CSS_IMPORT.findall(text)


def origins(public: Path) -> list[str]:
    problems: list[str] = []
    if not public.is_dir():
        return [f"{public}: build output not found (run hugo first)"]
    if (public / "ads.txt").exists():
        problems.append("ads.txt: ad configuration must not ship")
    for f in sorted(public.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(public).as_posix()
        if f.suffix == ".html":
            text = f.read_text(encoding="utf-8")
            c = _Collector()
            c.feed(text)
            for line, where, url in c.urls:
                if foreign(url):
                    problems.append(f"{rel}:{line}: {where} loads {url}")
            for line, css in c.inline_css:
                for url in css_urls(css):
                    if foreign(url):
                        problems.append(f"{rel}:{line}: inline CSS loads {url}")
            for line, js in c.inline_js:
                for m in SCRIPT_URL.finditer(js):
                    if foreign(m.group(0)[1:]):
                        problems.append(f"{rel}:{line}: inline script references {m.group(0)[1:]}")
            for m in TRACKERS.finditer(text):
                problems.append(f"{rel}: tracker or ad code {m.group(0)!r}")
        elif f.suffix in (".css", ".svg"):
            text = f.read_text(encoding="utf-8")
            for url in css_urls(text):
                if foreign(url):
                    problems.append(f"{rel}: CSS loads {url}")
        elif f.suffix == ".js":
            text = f.read_text(encoding="utf-8")
            for m in SCRIPT_URL.finditer(text):
                if foreign(m.group(0)[1:]):
                    problems.append(f"{rel}: script references {m.group(0)[1:]}")
            for m in TRACKERS.finditer(text):
                problems.append(f"{rel}: tracker or ad code {m.group(0)!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hand-numbers")
    h.add_argument("--root", type=Path, default=Path("."))
    o = sub.add_parser("origins")
    o.add_argument("--public", type=Path, default=Path("public"))
    args = ap.parse_args(argv)

    problems = (
        hand_numbers(args.root) if args.cmd == "hand-numbers" else origins(args.public)
    )
    for p in problems:
        print(p)
    print(
        f"{args.cmd}: {'FAIL' if problems else 'ok'} ({len(problems)} problem{'s' if len(problems) != 1 else ''})"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
