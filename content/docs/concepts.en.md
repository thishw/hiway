---
title: "Concepts"
description: "The ideas the kit is built on, and where each one lives in the plugin."
weight: 2
---

The current release ships {{< kit "agents" >}} agents, {{< kit "skills" >}} skills and {{< kit "rules" >}} rules. This page explains what they are for. Paths are relative to `plugins/common/` in the [hiway-kit repository](https://github.com/This-HW/hiway-kit).

## Native first

Claude Code already has agents, skills, hooks, workflows, telemetry and memory, and they change almost weekly. The largest source of debt in a kit like this is re-implementing what the harness already does. So hiway-kit leaves infrastructure (observability, delegation, hook execution) to the harness and adds only an opinionated layer on top: agents, skills and discipline. When a native feature makes a component redundant, the component is removed.

## Where the ideas come from

The kit combines four lines of thought:

| Source | What it takes | Where it shows up |
| --- | --- | --- |
| Claude Code itself | Agents, skills, hooks, dynamic workflows, telemetry, memory | The primitives everything else is built on: manifest dependencies, exec-form hooks, a Stop hook that blocks and gets the problem fixed |
| Development-method discipline | Brainstorm, plan, execute; phase gates; TDD; verification before completion | The `brainstorming → plan-task → auto-dev` chain and the definition of done |
| Hermes | "The memory and feedback loop is the core" | Validation findings go into a ledger and come back as context for the next piece of work |
| Plan-file conventions | Tracking progress in files | `docs/plans/<date>-<slug>/plan.md` and `checklist.json` |

## Gates and loops

Two complementary ideas shape how the kit runs.

**Harness engineering** is about *where and with what* an agent acts: context injected at session start, a curated tool list per agent, guard-rail hooks (`protect-sensitive`, `stop-validator`), and plan files on disk. The hooks ship only with the repository-marketplace install; the [getting-started guide](/docs/getting-started/) explains why.

**Loop engineering** is about *how long and how persistently* it acts. A gate is a deliberate stop where a person approves the design (`brainstorming`, `plan-task`). A loop is execution: `auto-dev` runs an approved plan without asking at every step, until it reaches a P0 question, the end of the plan, or a guard. A loop never skips a gate.

Where: `rules/loop-engineering.md`, `skills/auto-dev/`.

## Planning protocol

Assumptions the spec does not confirm are graded before anything else:

| Grade | Covers | What happens |
| --- | --- | --- |
| P0 | Data integrity, security, money, core business | Stop and ask |
| P1 | UX branches, business details | Apply a default, then confirm |
| P2 | UI details, edge cases | Record a TODO |
| P3 | Technical choices | Decide autonomously |

Both "unsure, so stop" and "minor, so proceed" skip the grading step, and the rule says so. A plan is ready for development only when its completion conditions are runnable commands.

Where: `rules/planning-protocol.md`, `skills/plan-task/`.

## Definition of done

"Done", "finished" and "passing" are not judgments. They are the output of a command. Before claiming completion the agent runs the verification command fresh, reads all of its output, and reports the real state with evidence if anything failed. Until then it says "implemented and self-validated, open: …".

Two ways an exit code gets lost are called out explicitly: a verdict printed only to stdout while the command exits 0, and a pipe that swallows it (`gate | tail` returns `tail`'s exit code). The fix is `pipefail`, and never chaining verification and a state change such as push or deploy in one call.

In `auto-dev`, each checklist item carries a `verify` command taken from the plan, and `checklist.json` flips an item to passed only when that command actually runs and exits 0.

Where: `rules/definition-of-done.md`, `tools/checklist.py`.

## Boundaries as completion conditions

When a plan sets or changes a module boundary, and the project already has a boundary checker (import-linter, Tach, dependency-cruiser, ESLint import rules, golangci-lint depguard), `plan-task` writes the checker's command into the plan's completion conditions. The boundary is then enforced by the same exit-code gate as everything else. The kit does not install a checker for you: when there is none, the plan records that, and adopting one is your decision. Loosening a boundary configuration to make a check pass is treated as a stop, not a fix.

Where: `skills/plan-task/references/boundary-check.md`.

## Adversarial review

The agent that wrote the code is a poor judge of it. `review-code` reviews a finished diff in a separate context and reads it as four personas: the hacker, Murphy's law, your future self and the picky user. Its verdict is REJECT, CONDITIONAL or ACCEPT, with findings by severity. `security-scan` covers secrets, injection, auth and vulnerable dependencies. For designs rather than diffs, `multi-perspective-review` runs up to ten viewpoints over three rounds, and `devils-advocate` looks for failure paths before a decision is made.

Where: `agents/review-code.md`, `skills/multi-perspective-review/`.

## Feedback learning loop

Findings from review and validation are normalized and written to a feedback ledger under your repository's `.git/kit/`. The ledger has a cap, removes duplicates and lets old entries decay. At the next session start, a digest of recurring findings is injected as `=== LESSONS ===`, so the same mistake is caught before it is made again.

Inside a session there is a shorter loop. When a session that changed Python files tries to stop, the Stop hook runs ruff and the tests that session edited; on a failure it blocks the stop, and the agent has to fix the problem first. Both the LESSONS injection and the Stop hook are hooks, so they run with the repository-marketplace install only.

Where: `rules/feedback-loop.md`, `tools/feedback_ledger.py`, `hooks/stop-validator.py`.

## Orchestration that fits the scale

The split is by how many chunks can run in parallel, not by the size of the task. A handful of chunks runs as flat, skill-driven dispatch from the main session. When dozens of independent chunks are ready at once, `auto-dev` splits them up and suggests running them as a native Claude Code dynamic workflow (`ultracode`) instead, so the main session's context does not become the bottleneck. That workflow is opt-in: you start it yourself, the skill never does.

## Specialized agents

The agents are split into planning, development and meta roles, and each sets its model in frontmatter. The planning agents, `plan-implementation`, `review-code` and `devils-advocate` use Opus; implementation, fixes, tests, external research and the security scan use Sonnet; quick, low-effort jobs such as `verify-code`, `git-workflow`, `analyze-dependencies` and `sync-docs` use Haiku. Agents that modify files (`implement-code`, `fix-bugs`, `write-tests`, `sync-docs`) run in an isolated git worktree so parallel work does not collide, and the merge-back rules live in `rules/parallel-worktree.md`.

Model and effort settings apply in Claude Code. Codex and Antigravity do not expose the agents as subagents; there the skills perform the same contracts in the session.

## Untrusted text

Web results, third-party documents, recalled memory and other sessions' logs are treated as data, never as instructions. They are quoted, framed before the payload, and any instruction inside them is reported instead of followed. This matters most when the text is about to be stored, because a poisoned ledger or memory persists across sessions.

Where: `rules/untrusted-text.md`.

## Working with your MCP servers

The kit assumes no particular MCP server. It uses whatever the session has:

- **Search and documentation servers.** The rules tell the agent to prefer an installed server and to fall back to the built-in tools when there is none or it fails. Nothing has to be installed.
- **Memory servers** (any server with `recall`, `search` or `remember`-style tools). The design goal is to recall before planning and remember after finishing. No skill calls them yet, so today this is a goal, not a behavior. What a memory tool returns is treated as untrusted text.
- **No conflicts.** The kit's agents do not hard-code MCP tools in their allow-lists, so any combination of servers works. The same goes for other plugins: the kit neither assumes nor conflicts with them, and it works on its own.

Where: `rules/mcp-usage.md`.
