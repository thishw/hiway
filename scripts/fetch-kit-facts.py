#!/usr/bin/env python3
"""Generate data/kit.json from the latest hiway-kit release tag.

The site never carries a hand-written count or version. Every number it shows —
agents, skills, rules, the plugin version, recent CHANGELOG entries and the
privacy policy text — comes from this file, and this file comes from one place:
the newest ``vX.Y.Z`` tag of ``This-HW/hiway-kit``.

Any failure (network, no tag, schema violation) exits non-zero so the build
stops. Shipping last week's numbers silently is the failure this script exists
to prevent.

Counting rules are identical to hiway-kit ``scripts/check_doc_counts.py::count_actuals``:
  agents = plugins/*/agents/**/*.md that contain a line starting with ``name:``
  skills = plugins/common/skills/**/SKILL.md
  rules  = plugins/common/rules/*.md

Usage:
  scripts/fetch-kit-facts.py                      # CI: latest release tag via GitHub
  scripts/fetch-kit-facts.py --from-path ../kit   # local development only
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

REPO = "This-HW/hiway-kit"
API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
SCHEMA = 1
CHANGELOG_ENTRIES = 5
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ROOT = Path(__file__).resolve().parent.parent


class FactsError(Exception):
    """Anything that must stop the build."""


HttpGet = Callable[[str], bytes]


def http_get(url: str) -> bytes:
    headers = {"User-Agent": "hiway-site-fetch-kit-facts"}
    if url.startswith(API):
        headers["Accept"] = "application/vnd.github+json"
        # Optional: the Actions token only raises the rate limit. The data is public.
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FactsError(f"GET {url} failed: {e}") from e


# --- release selection ---------------------------------------------------------


def latest_tag(tags: list[dict]) -> dict:
    """Highest ``vX.Y.Z`` tag. Pre-release and non-semver tags are ignored."""
    best = None
    for t in tags:
        m = TAG_RE.match(t.get("name", ""))
        if not m:
            continue
        key = tuple(int(x) for x in m.groups())
        if best is None or key > best[0]:
            best = (key, t)
    if best is None:
        raise FactsError("no release tag matching vX.Y.Z found")
    return best[1]


def list_tags(repo: str, get: HttpGet) -> list[dict]:
    tags: list[dict] = []
    for page in range(1, 11):
        try:
            batch = json.loads(get(f"{API}/repos/{repo}/tags?per_page=100&page={page}"))
        except json.JSONDecodeError as e:
            raise FactsError(f"tags response is not JSON: {e}") from e
        if not isinstance(batch, list):
            raise FactsError(f"unexpected tags response: {str(batch)[:200]}")
        tags.extend(batch)
        if len(batch) < 100:
            break
    return tags


def commit_date(repo: str, sha: str, get: HttpGet) -> str:
    try:
        data = json.loads(get(f"{API}/repos/{repo}/commits/{sha}"))
        return data["commit"]["committer"]["date"][:10]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise FactsError(f"cannot read commit date for {sha}: {e}") from e


def extract_tarball(blob: bytes, dest: Path, expect_sha: str) -> Path:
    """Unpack a codeload tarball and return its single top-level directory."""
    archive = dest / "kit.tar.gz"
    archive.write_bytes(blob)
    try:
        with tarfile.open(archive, "r:gz") as tf:
            comment = tf.pax_headers.get("comment")
            if comment != expect_sha:
                raise FactsError(f"tarball commit {comment} != tag commit {expect_sha}")
            members = tf.getmembers()
            for m in members:
                p = Path(m.name)
                if p.is_absolute() or ".." in p.parts:
                    continue
                if m.issym() or m.islnk():
                    if "plugins" in p.parts:
                        raise FactsError(f"link inside plugins/ would be skipped and skew counts: {m.name}")
                    continue
                if m.isdir() or m.isfile():
                    kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
                    tf.extract(m, dest / "src", set_attrs=False, **kw)
    except tarfile.TarError as e:
        raise FactsError(f"bad tarball: {e}") from e
    src = dest / "src"
    roots = [p for p in src.iterdir() if p.is_dir()] if src.is_dir() else []
    if len(roots) != 1:
        raise FactsError(f"tarball has {len(roots)} top-level directories, expected 1")
    return roots[0]


# --- facts from a kit tree -----------------------------------------------------


def count_actuals(root: Path) -> dict:
    """Same definitions as hiway-kit scripts/check_doc_counts.py::count_actuals."""
    agents = 0
    for f in root.glob("plugins/*/agents/**/*.md"):
        try:
            if re.search(r"^name:", f.read_text(encoding="utf-8"), re.MULTILINE):
                agents += 1
        except OSError:
            pass
    return {
        "agents": agents,
        "skills": len(list(root.glob("plugins/common/skills/**/SKILL.md"))),
        "rules": len(list(root.glob("plugins/common/rules/*.md"))),
    }


def plugin_version(root: Path) -> str:
    p = root / "plugins/common/.claude-plugin/plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["version"]
    except (OSError, json.JSONDecodeError, KeyError) as e:
        raise FactsError(f"cannot read version from {p}: {e}") from e


CHANGELOG_HEAD = re.compile(
    r"^## \[(\d+\.\d+\.\d+)\]\s*[—–-]\s*(\d{4}-\d{2}-\d{2})\s*$"
)


def parse_changelog(text: str, limit: int = CHANGELOG_ENTRIES) -> list[dict]:
    """Newest ``limit`` entries: version, date and their ``###`` headings."""
    entries: list[dict] = []
    current = None
    for line in text.splitlines():
        m = CHANGELOG_HEAD.match(line)
        if m:
            if len(entries) == limit:
                break
            current = {"version": m.group(1), "date": m.group(2), "headings": []}
            entries.append(current)
        elif current is not None and line.startswith("### "):
            current["headings"].append(line[4:].strip())
    return entries


def parse_privacy(text: str) -> dict:
    """Policy body without its H1 (the page supplies the title) and its update date."""
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    updated = None
    body = []
    for line in lines:
        m = re.match(r"^_Last updated: (\d{4}-\d{2}-\d{2})_\s*$", line)
        if m and updated is None:
            updated = m.group(1)
            continue
        body.append(line)
    return {"updated": updated, "markdown": "\n".join(body).strip() + "\n"}


def read_text(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except OSError as e:
        raise FactsError(f"missing {rel} in kit tree: {e}") from e


def collect(root: Path, source: dict) -> dict:
    return {
        "schema": SCHEMA,
        "source": source,
        "version": plugin_version(root),
        "counts": count_actuals(root),
        "changelog": parse_changelog(read_text(root, "CHANGELOG.md")),
        "privacy": parse_privacy(read_text(root, "PRIVACY.md")),
    }


# --- schema --------------------------------------------------------------------


def validate(facts: dict) -> None:
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    need(facts.get("schema") == SCHEMA, f"schema must be {SCHEMA}")
    src = facts.get("source") or {}
    need(src.get("mode") in ("tag", "local"), "source.mode must be tag|local")
    need(isinstance(src.get("tag"), str) and src["tag"] != "", "source.tag required")
    if src.get("mode") == "tag":
        need(bool(re.fullmatch(r"[0-9a-f]{40}", str(src.get("commit", "")))), "source.commit must be a 40-hex sha")
    need(
        isinstance(src.get("date"), str) and bool(DATE_RE.match(src.get("date", ""))),
        "source.date must be YYYY-MM-DD",
    )
    version = facts.get("version")
    need(
        isinstance(version, str) and bool(SEMVER_RE.match(version or "")),
        "version must be X.Y.Z",
    )
    if src.get("mode") == "tag" and isinstance(version, str):
        need(
            src.get("tag") == f"v{version}",
            f"tag {src.get('tag')} does not match plugin version {version}",
        )
    counts = facts.get("counts") or {}
    for k in ("agents", "skills", "rules"):
        v = counts.get(k)
        need(
            type(v) is int and v > 0,
            f"counts.{k} must be a positive integer (got {v!r})",
        )
    cl = facts.get("changelog")
    need(isinstance(cl, list) and len(cl) > 0, "changelog must have at least one entry")
    for e in cl or []:
        need(
            isinstance(e.get("headings"), list) and all(isinstance(h, str) for h in e["headings"]),
            f"changelog headings must be a list of strings ({e.get('version')!r})",
        )
        need(
            bool(SEMVER_RE.match(e.get("version", ""))),
            f"changelog version invalid: {e.get('version')!r}",
        )
        need(
            bool(DATE_RE.match(e.get("date", ""))),
            f"changelog date invalid: {e.get('date')!r}",
        )
    if isinstance(cl, list) and cl and isinstance(version, str):
        need(
            cl[0].get("version") == version,
            f"newest CHANGELOG entry {cl[0].get('version')} != version {version}",
        )
    pv = facts.get("privacy") or {}
    need(
        isinstance(pv.get("markdown"), str) and len(pv["markdown"].strip()) > 200,
        "privacy.markdown missing or too short",
    )
    need(
        isinstance(pv.get("updated"), str)
        and bool(DATE_RE.match(pv.get("updated") or "")),
        "privacy.updated must be YYYY-MM-DD",
    )
    if errs:
        raise FactsError("schema violation:\n  - " + "\n  - ".join(errs))


# --- modes ---------------------------------------------------------------------


def from_tag(repo: str, get: HttpGet | None = None) -> dict:
    get = get or http_get
    tag = latest_tag(list_tags(repo, get))
    name, sha = tag["name"], tag["commit"]["sha"]
    date = commit_date(repo, sha, get)
    blob = get(f"{CODELOAD}/{repo}/tar.gz/refs/tags/{name}")
    with tempfile.TemporaryDirectory() as tmp:
        root = extract_tarball(blob, Path(tmp), sha)
        return collect(
            root,
            {"repo": repo, "mode": "tag", "tag": name, "commit": sha, "date": date},
        )


def from_path(path: Path, repo: str = REPO) -> dict:
    if not path.is_dir():
        raise FactsError(f"--from-path {path} is not a directory")

    def git(*args: str) -> str:
        r = subprocess.run(
            ["git", "-C", str(path), *args], capture_output=True, text=True
        )
        return r.stdout.strip() if r.returncode == 0 else ""

    sha = git("rev-parse", "HEAD")
    tag = git("describe", "--tags", "--exact-match", "HEAD") or "local"
    if git("status", "--porcelain"):
        tag = f"{tag}-dirty"  # counted files are not exactly the tagged release
    date = git("log", "-1", "--format=%cs") or dt.date.today().isoformat()
    return collect(
        path, {"repo": repo, "mode": "local", "tag": tag, "commit": sha, "date": date}
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=REPO)
    ap.add_argument(
        "--from-path",
        type=Path,
        help="local hiway-kit checkout (development only; CI uses the tag)",
    )
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "kit.json")
    args = ap.parse_args(argv)
    try:
        facts = (
            from_path(args.from_path, args.repo)
            if args.from_path
            else from_tag(args.repo)
        )
        validate(facts)
    except Exception as e:  # noqa: BLE001 — every failure must stop the build
        # Never leave last run's facts behind: a later `hugo` would build with them.
        args.out.unlink(missing_ok=True)
        print(f"fetch-kit-facts: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_name(args.out.name + ".tmp")
    tmp.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, args.out)
    c = facts["counts"]
    print(
        f"fetch-kit-facts: {facts['source']['mode']} {facts['source']['tag']} → {args.out} "
        f"(version {facts['version']}, agents {c['agents']}, skills {c['skills']}, rules {c['rules']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
