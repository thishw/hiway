#!/usr/bin/env python3
"""Site checks that CI runs on every pull request (and you can run locally).

  check_site.py hand-numbers [--root .]     no hand-written counts or versions in sources
  check_site.py origins [--public public]   built pages load nothing from another origin,
                                            and carry no analytics or ad code
  check_site.py overflow [--public public]  no built page scrolls sideways at 390x844
                                            (needs Chrome: $CHROME, or google-chrome/chromium on PATH)
  check_site.py kit-links [--root .] [--tag vX.Y.Z | --from-path ../hiway-kit]
                                            every hiway-kit blob/tree link in content/ names a
                                            path that exists in the kit, and every #anchor on a
                                            kit Markdown file is one of its headings (default:
                                            the newest release tag, fetched like fetch-kit-facts)

Exit 0 = clean, 1 = violations (each printed as file:line, or page for overflow), 2 = the
check could not run (no browser, or the kit could not be fetched). Internal links are checked separately by htmltest
(.htmltest.yml).
"""

from __future__ import annotations

import argparse
import contextlib
import html
import http.server
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


# --- sideways overflow on a phone ------------------------------------------------
#
# Every built page is opened in headless Chrome at 390x844 and must not be wider than the
# window. Pages are served from a throwaway local server that appends a measuring script to
# each HTML response (nothing in public/ is touched); the script writes the result into
# <title>, which --dump-dom prints. The title is "ovf|<scrollWidth>|<clientWidth>|<culprits>".
PHONE_WIDTH, PHONE_HEIGHT = 390, 844
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
MEASURE = (
    "<script>addEventListener('load',function(){var d=document.documentElement,w=d.clientWidth,"
    "c=function(e){for(e=e.parentElement;e;e=e.parentElement)if(getComputedStyle(e).overflowX!='visible')return 1},"
    "o=[].filter.call(document.body.querySelectorAll('*'),function(e){"
    "var r=e.getBoundingClientRect();return r.width>0&&r.right>w+1&&!c(e)}).slice(0,4).map(function(e){"
    "return e.tagName.toLowerCase()+(typeof e.className=='string'&&e.className?'.'+e.className.split(' ')[0]:'')});"
    "document.title='ovf|'+d.scrollWidth+'|'+w+'|'+o.join(';')})</script>"
)
REDIRECT = re.compile(r"http-equiv=[\"']?refresh", re.I)
MEASURED = re.compile(r"<title>ovf\|(\d+)\|(\d+)\|([^<]*)</title>")


def find_chrome() -> str | None:
    env = os.environ.get("CHROME")
    if env:
        return env if Path(env).is_file() else None
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return None


class _Measuring(http.server.SimpleHTTPRequestHandler):
    """Serves public/ and appends MEASURE to every HTML page."""

    def do_GET(self):  # noqa: N802 (stdlib name)
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        if path.suffix != ".html" or not path.is_file():
            return super().do_GET()
        body = (path.read_text(encoding="utf-8") + MEASURE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def measure_page(chrome: str, url: str) -> tuple[int, int, str] | None:
    cmd = [
        chrome, "--headless", "--no-sandbox", "--disable-gpu",
        f"--window-size={PHONE_WIDTH},{PHONE_HEIGHT}", "--virtual-time-budget=5000",
        "--dump-dom", url,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return None
    m = MEASURED.search(out)
    return (int(m.group(1)), int(m.group(2)), html.unescape(m.group(3))) if m else None


def overflow(public: Path, chrome: str) -> list[str]:
    pages = sorted(public.rglob("*.html")) if public.is_dir() else []
    if not pages:
        return [f"{public}: no HTML pages (run hugo first)"]
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_Measuring, directory=str(public))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    problems: list[str] = []
    try:
        for f in pages:
            rel = f.relative_to(public).as_posix()
            if REDIRECT.search(f.read_text(encoding="utf-8")):
                continue  # an alias page: it renders nothing and sends the browser elsewhere
            got = measure_page(chrome, f"http://127.0.0.1:{server.server_port}/{rel}")
            if got is None:
                problems.append(f"{rel}: could not be measured (no result from Chrome)")
                continue
            scroll, client, culprits = got
            if scroll > client:
                problems.append(
                    f"{rel}: {scroll}px wide in a {client}px window"
                    + (f" (wider than the window: {culprits})" if culprits else "")
                )
    finally:
        server.shutdown()
    return problems


# --- links into the kit repository ---------------------------------------------
#
# The site points at files in hiway-kit two ways: the home page's "where" entries
# (front matter ``path: "blob/<path>"`` or ``"tree/<path>"``, rendered against the release
# tag in data/kit.json) and full GitHub URLs in Markdown (``…/hiway-kit/blob/<ref>/<path>``).
# Every one must name a file (blob) or directory (tree) that exists in the kit tree, and a
# ``#fragment`` on a Markdown file must be an anchor GitHub generates from one of its
# headings (or an explicit ``<a id|name>``).
#
# Which kit tree: by default the newest vX.Y.Z tag, fetched exactly the way
# scripts/fetch-kit-facts.py fetches it, so the gate sees what the built site links to.
# ``--tag`` pins another release tag; ``--from-path`` reads a local checkout as it is
# (development only, e.g. a release candidate). A URL that names its own ref (blog posts
# use ``main``) is still checked against that one tree: what users install is the release,
# and a link that resolves only on main points at something not yet released.
KIT_REPO = "This-HW/hiway-kit"
KIT_SCAN = ("content",)
KIT_URL = re.compile(
    r"https?://github\.com/This-HW/hiway-kit/(blob|tree)/([^/\s)\"'<>#]+)/([^\s)\"'<>#?]*)(?:#([^\s)\"'<>]*))?",
    re.I,
)
WHERE_PATH = re.compile(
    r"""^\s*path:\s*["']?(blob|tree)/([^"'\s#]*)(?:#([^"'\s]*))?["']?\s*$"""
)
MD_SUFFIXES = {".md", ".markdown"}
ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HTML_ANCHOR = re.compile(r"""<a\s[^>]*?\b(?:id|name)\s*=\s*["']([^"']+)["']""", re.I)


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading: rendered text, lower-cased, punctuation dropped."""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # links and images → text
    text = re.sub(r"<[^>]+>", "", text).replace("`", "").lower()
    # GitHub keeps \p{Word} (letters, marks, decimal digits, connectors), hyphen and space.
    kept = (
        ch
        for ch in text
        if ch in " -"
        or unicodedata.category(ch)[0] in "LM"
        or unicodedata.category(ch) in ("Nd", "Pc")
    )
    return "".join(kept).replace(" ", "-")


def md_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    fence: str | None = None
    for line in text.splitlines():
        f = FENCE.match(line)
        if fence:
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence):
                fence = None
            continue
        if f:
            fence = f.group(1)
            continue
        h = ATX_HEADING.match(line)
        if h and h.group(1):
            slug = github_slug(h.group(1))
            n = seen.get(slug, 0)
            anchors.add(slug if n == 0 else f"{slug}-{n}")
            seen[slug] = n + 1
        anchors.update(HTML_ANCHOR.findall(line))
    return anchors


def _kit_target(
    kit: Path, kind: str, path: str, fragment: str | None, cache: dict
) -> str | None:
    """Why ``kind/path#fragment`` does not resolve in ``kit`` (resolved root), or None."""
    rel = unquote(path).strip("/")
    target = (kit / rel).resolve()  # resolved once; must stay inside the checkout
    if target != kit and not target.is_relative_to(kit):
        return "leaves the kit checkout"
    if kind == "blob" and not target.is_file():
        return (
            "is a directory, link it with tree/" if target.is_dir() else "no such file"
        )
    if kind == "tree" and not target.is_dir():
        return (
            "is a file, link it with blob/" if target.is_file() else "no such directory"
        )
    if fragment and target.suffix.lower() in MD_SUFFIXES:
        if target not in cache:
            cache[target] = md_anchors(target.read_text(encoding="utf-8"))
        if unquote(fragment) not in cache[target]:
            return f"no heading in {rel} makes anchor #{unquote(fragment)}"
    return None


def kit_links(root: Path, kit: Path, label: str = "kit") -> tuple[int, list[str]]:
    """(number of links checked, problems) for every kit link under ``root``'s content."""
    kit = kit.resolve()
    problems: list[str] = []
    cache: dict[Path, set[str]] = {}
    checked = 0
    for entry in KIT_SCAN:
        base = root / entry
        files = sorted(base.rglob("*.md")) if base.is_dir() else []
        for f in files:
            rel = f.relative_to(root).as_posix()
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                links = [
                    (m.group(1), m.group(2), m.group(3))
                    for m in [WHERE_PATH.match(line)]
                    if m
                ]
                links += [
                    (m.group(1), m.group(3), m.group(4)) for m in KIT_URL.finditer(line)
                ]
                for kind, path, fragment in links:
                    checked += 1
                    why = _kit_target(kit, kind.lower(), path, fragment, cache)
                    if why:
                        shown = f"{kind}/{path}" + (f"#{fragment}" if fragment else "")
                        problems.append(f"{rel}:{n}: {shown} at {label}: {why}")
    return checked, problems


def _load_fetch_kit_facts():
    spec = importlib.util.spec_from_file_location(
        "fetch_kit_facts", Path(__file__).resolve().with_name("fetch-kit-facts.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def kit_tree(from_path: Path | None, tag: str | None, repo: str = KIT_REPO):
    """Yield (kit root, label) — a local checkout, or a release tag's tarball."""
    if from_path is not None:
        if not from_path.is_dir():
            raise RuntimeError(f"--from-path {from_path} is not a directory")
        r = subprocess.run(
            ["git", "-C", str(from_path), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
        )
        yield from_path, f"{from_path} ({r.stdout.strip() or 'not a git checkout'})"
        return
    fkf = _load_fetch_kit_facts()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            t = fkf.release_tag(repo, fkf.http_get, tag)
            yield fkf.download_tag(repo, t, Path(tmp), fkf.http_get), t["name"]
    except fkf.FactsError as e:
        raise RuntimeError(str(e)) from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hand-numbers")
    h.add_argument("--root", type=Path, default=Path("."))
    o = sub.add_parser("origins")
    o.add_argument("--public", type=Path, default=Path("public"))
    v = sub.add_parser("overflow")
    v.add_argument("--public", type=Path, default=Path("public"))
    k = sub.add_parser("kit-links")
    k.add_argument("--root", type=Path, default=Path("."))
    which = k.add_mutually_exclusive_group()
    which.add_argument("--tag", help="release tag to check against (default: the newest vX.Y.Z)")
    which.add_argument("--from-path", type=Path, help="local hiway-kit checkout, as it is (development only)")
    args = ap.parse_args(argv)

    if args.cmd == "overflow":
        chrome = find_chrome()
        if not chrome:
            print("overflow: no Chrome found (set CHROME=/path/to/chrome)", file=sys.stderr)
            return 2
        problems = overflow(args.public, chrome)
    elif args.cmd == "hand-numbers":
        problems = hand_numbers(args.root)
    elif args.cmd == "kit-links":
        try:
            with kit_tree(args.from_path, args.tag) as (kit, label):
                checked, problems = kit_links(args.root, kit, label)
        except RuntimeError as e:
            print(f"kit-links: cannot read the kit: {e}", file=sys.stderr)
            return 2
        print(f"kit-links: {checked} link{'s' if checked != 1 else ''} checked against {label}")
    else:
        problems = origins(args.public)
    for p in problems:
        print(p)
    print(
        f"{args.cmd}: {'FAIL' if problems else 'ok'} ({len(problems)} problem{'s' if len(problems) != 1 else ''})"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
