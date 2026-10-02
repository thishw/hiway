---
title: "hiway-kit"
description: "hiway-kit is a plugin of agents, skills and rules for coding agents. It plans before it builds, reviews adversarially, and treats done as the output of a command."

hero:
  headline: "Done is an exit code, not a claim."
  lede: "hiway-kit is a plugin of agents, skills and rules for Claude Code, Codex and Antigravity. Larger work goes through a plan before any code, and a task counts as finished only when the command that checks it exits 0."
  primary: "Install for Claude Code"
  secondary: "Read the getting-started guide"

problem:
  heading: "An agent without a plan finishes early."
  body: |
    Ask a coding agent for a feature and it starts typing at once. An hour later it reports that everything is done. Often a requirement nobody pinned down was guessed, the test it mentions never ran, or a module boundary the design relied on quietly broke.

    The agent isn't lying. It has nothing to check its work against except its own judgment. **hiway-kit gives it something else to check against:** a plan whose completion conditions are written as commands, and a gate that reads exit codes instead of sentences.

how:
  heading: "How it works"
  intro: "Two gates and a loop between them. People decide at the gates; the loop runs on its own until it finishes, hits a guard, or meets a question only you can answer."
  svg:
    alt: "Work passes a planning gate, runs through a build loop, then reaches a verification gate. A verify command that exits 0 leads to done; any other exit code sends the work back into the loop."
    gate1: "Planning gate"
    gate1_sub: "plan-task"
    loop: "Build loop"
    loop_sub: "auto-dev"
    gate2: "Verification gate"
    gate2_sub: "verify → exit 0"
    done: "done"
    fail: "exit ≠ 0: back into the loop"
    fail_short: "exit ≠ 0"
  stations:
    - title: "Planning gate"
      body: "Large features start with `brainstorming`; Medium and Large work is written up by `plan-task` into `docs/plans/<date>-<slug>/plan.md`. Each completion condition is a command you can run. Small fixes skip the ceremony."
    - title: "Build loop"
      body: "`auto-dev` works through the approved plan batch by batch. It keeps going on its own and stops for a P0 question, a guard, or the end of the plan."
    - title: "Verification gate"
      body: "A checklist item turns green only when its `verify` command runs and exits 0. Review and a security scan look at the change before it is merged back."

features:
  heading: "What the kit actually does"
  items:
    - title: "A planning gate"
      body: "Open questions are graded P0 to P3. Only P0 — data integrity, security, money, core business — stops the work and asks you. The rest gets a stated default and a note."
      where:
        label: "skills/plan-task"
        path: "tree/plugins/common/skills/plan-task"
    - title: "Adversarial review"
      body: "`review-code` reads a finished diff in a context separate from the author's, as four personas: a hacker, Murphy, your future self and a picky user. `multi-perspective-review` takes a design through up to ten viewpoints."
      where:
        label: "agents/dev/review-code.md"
        path: "blob/plugins/common/agents/dev/review-code.md"
    - title: "Done is decided by a command"
      body: "“Done” is not a judgment. Until the verification command has been run fresh and its output read, the agent reports “implemented, not yet verified” and lists what is left."
      where:
        label: "rules/definition-of-done.md"
        path: "blob/plugins/common/rules/definition-of-done.md"
    - title: "Learning from failures"
      body: "Review and validation findings go into a feedback ledger under `.git/kit/`, capped, de-duplicated and decaying. The next session starts with the recurring ones as lessons."
      where:
        label: "tools/feedback_ledger.py"
        path: "blob/plugins/common/tools/feedback_ledger.py"
    - title: "Boundaries checked by your own tools"
      body: "If your project already runs a boundary checker such as import-linter or dependency-cruiser, `plan-task` writes its command into the plan's completion conditions. If there is none, the plan says so; adopting one stays your call."
      where:
        label: "plan-task/references/boundary-check.md"
        path: "blob/plugins/common/skills/plan-task/references/boundary-check.md"
    - title: "More than one harness"
      body: "Rules and skills work in Claude Code, Codex and Antigravity. Dedicated subagents and hooks that block a tool call are Claude Code features; elsewhere the same discipline arrives as instructions."
      where:
        label: "README: Other Harnesses"
        path: "blob/README.md#other-harnesses-codex--antigravity"

harnesses:
  heading: "Where it runs"
  intro: "What each harness gets was measured against the real CLIs, not assumed. Rules and skills travel everywhere; what changes is how they arrive."
  columns: ["Rules", "Skills", "Subagents", "Blocking hooks"]
  rows:
    - name: "Claude Code"
      cells:
        - { state: "yes", text: "Injected at session start" }
        - { state: "yes", text: "Native" }
        - { state: "yes", text: "Yes" }
        - { state: "yes", text: "Yes" }
    - name: "Codex"
      cells:
        - { state: "yes", text: "Injected once you trust the hooks; AGENTS.md as fallback" }
        - { state: "yes", text: "All recognized" }
        - { state: "no", text: "No — skills run in the session" }
        - { state: "no", text: "No" }
    - name: "Antigravity"
      cells:
        - { state: "part", text: "Only through AGENTS.md or GEMINI.md" }
        - { state: "yes", text: "Recognized" }
        - { state: "no", text: "No" }
        - { state: "no", text: "No" }
  note: "Codex skips plugin hooks in silence until you approve them once. The [getting-started guide](/docs/getting-started/#codex) shows how."

install:
  heading: "Install"
  claude:
    title: "Claude Code"
    body: "Add the marketplace, then install the plugin. The hooks run on your machine's `python3` (3.9 or newer)."
    after: "Plugins install at user scope, so this changes every session on the machine, including ones already running. Install when no long task is in flight. To update later: `/plugin marketplace update hiway-kit`."
  others:
    - title: "Codex"
      body: "Clone the repository, add it as a plugin marketplace, then approve hook trust once. [Steps](/docs/getting-started/#codex)."
    - title: "Antigravity"
      body: "Validate and install from `plugins/common` of a local clone. Only local installation is documented. [Steps](/docs/getting-started/#antigravity)."

closing:
  label: "Get started"
  line: "Start with a plan. Finish with an exit code."
  primary: "Get started"
  secondary: "Source on GitHub"
---
