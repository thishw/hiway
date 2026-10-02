---
title: "Getting started"
description: "Install the plugin, then let the size of the task decide how much process it gets."
weight: 1
---

## Before you install

You need the [Claude Code CLI](https://code.claude.com) (`claude --version`). The kit's hooks run on your machine's `python3`, version 3.9 or newer; the macOS system Python qualifies. On an older interpreter the hooks do nothing and the session warns you once.

## Install in Claude Code

The marketplace name is `hiway-kit`:

```text
/plugin marketplace add This-HW/hiway-kit
/plugin install hiway-kit@hiway-kit
```

To update later, refresh the marketplace and the new version is picked up:

```text
/plugin marketplace update hiway-kit
```

hiway-kit is not yet listed in Anthropic's community catalog. Until it is, the marketplace commands above are the only install path.

### Installing changes the whole machine

Plugins install at user scope. Installing, updating or removing one changes hook registration and rule injection for every session on the machine, including sessions that are already running: they keep the context they started with, but their hooks may stop resolving. Do it when no long task is in flight, or restart running sessions afterwards.

Don't run two kits that ship the same skills at the same time. There is no plugin aliasing, so both register.

## Your first task

At session start the kit injects its rules and a short workflow note. From there, the size of the task decides the path:

| Size | Path |
| --- | --- |
| Small, or a bug fix | Implement directly and verify with the completion command |
| Medium | `/plan-task`, then `/auto-dev` |
| Large new feature | `/brainstorming`, then `/plan-task`, then `/auto-dev` |

`plan-task` owns the size call. For Medium and Large work it writes `docs/plans/<date>-<slug>/plan.md`, and its `## 완료 조건` (completion conditions) section lists commands, not descriptions. `auto-dev` turns those commands into checklist items and marks an item as passed only when its command exits 0.

Questions that come up along the way are graded. Only P0 (data integrity, security, money, core business) stops the work and asks you; the rest gets a stated default.

Other skills you will reach for: `/review` for a lint, adversarial review and, when sensitive files changed, a security pass over your current changes; `/debug` with an error or traceback; `/test` to run the suite and fix failures. The [concepts page](/docs/concepts/) explains the ideas behind them.

## Codex {#codex}

The plugin root ships a native Codex manifest. Add a local clone as a plugin marketplace:

```bash
git clone https://github.com/This-HW/hiway-kit
codex plugin marketplace add ./hiway-kit
codex plugin add hiway-kit@hiway-kit-marketplace
codex plugin list   # shows hiway-kit@hiway-kit-marketplace
```

**Then trust the hooks once.** Codex skips a plugin's hooks in silence until you approve them, and nothing in the session tells you the rules were not injected. Start an interactive `codex` session in your project and approve the hook trust prompt. With non-interactive `codex exec` there is no prompt, so hooks stay skipped unless you pass `--dangerously-bypass-hook-trust`; use it only where you already trust the plugin.

Even without hooks, the rules still reach Codex through `AGENTS.md` (export them with `/harness-export`). Codex exposes no subagents, so skills that name an agent perform the same contract inside the session.

To remove:

```bash
codex plugin remove hiway-kit@hiway-kit-marketplace
codex plugin marketplace remove hiway-kit-marketplace
```

## Antigravity {#antigravity}

Validate first, then install from `plugins/common` of a local clone:

```bash
agy plugin validate /path/to/hiway-kit/plugins/common
agy plugin install /path/to/hiway-kit/plugins/common
agy plugin list   # shows hiway-kit
```

Antigravity recognizes the skills but not the `rules/` directory or the nested agents, so the rules reach it only through `AGENTS.md` or `GEMINI.md`. Google documents only local and workspace installation; no public registry is confirmed. Remove with `agy plugin uninstall hiway-kit`.
