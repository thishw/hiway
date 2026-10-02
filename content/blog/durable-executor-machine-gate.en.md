---
title: "Done Is a Command's Output, Not a Claim: Designing a Durable Completion Gate for Long-Running Loop Agents"
date: 2026-07-03
lastmod: 2026-10-02
description: "Let a loop agent mark its own work as done and unverified code sails through. How the discovery that native Tasks are session-scoped killed our first design, and how we moved completion state into a single file judged by the raw exit code of a verify command."
tags: ["loop engineering", "completion gates", "adversarial review", "durable execution"]
translationKey: durable-executor-machine-gate
aliases: ["/posts/2026-07-03-durable-executor-machine-gate/"]
alias_to_lang: ko
---

The previous two posts mapped the landscape of harness and loop engineering ([research notes](https://github.com/This-HW/hiway-kit/blob/main/docs/research/2026-07-harness-loop-engineering.md)) and then [applied it to git isolation for parallel work](/blog/harness-engineering-in-practice/). This one is about the next question: when an agent runs a loop **across many sessions over a long time**, what decides that something is "done"?

> **Key takeaways**
>
> Hand a loop agent the authority to judge completion and it will mark unverified work as done. Completion has to be **the output of a command**, not **a claim made by the model**.
>
> For that, completion state has to survive session boundaries — it has to be durable. But native Tasks were session-scoped, and that one discovery threw out our first design entirely.
>
> The result: completion state lives in **a single file (`checklist.json`)**, and whether each item passes is decided only by the **raw exit code** of that item's `verify` command. The model cannot mark something as passed without actually running the check.

## 1. The problem: the longer the loop, the softer "done" gets

For one-off tasks, judging completion is easy. A human looks at the result and approves it. But in a loop that **autonomously drives an approved plan to the end** (the Ralph-loop family), nobody watches each iteration. At that point, the authority to declare completion has quietly passed to the model.

That's where a well-known failure mode shows up. Models are optimistic. Once the implementation *feels* finished, the model marks the checklist item `completed` and moves on — whether or not verification actually passed. The longer the loop and the more iterations it runs, the more items pile up that were **passed as done without ever being verified**. One line from our research captured the heart of it:

> No PASS without proof. Completion is not a judgment call; it is the output of a reproducible command.

The kit repo already had a gate built on that philosophy: `verify-done.sh`, the kit repo's own completion gate (it isn't shipped in the plugin). But it only checked the state of things *right now* — lint, tests, secrets, docs in sync. It couldn't answer **"has every planned item passed its own verification?"** And judging a loop's completion needs exactly that.

## 2. The first design, and the one fact that killed it

The first design (Option A) seemed obvious: "Reuse the native Task system. Attach acceptance criteria to each Task and use that as the durable checklist."

We handed it to three adversarial reviewers (fresh context, separate from the authoring session). What came back brought the whole design down.

> Native Tasks are stored under `~/.claude/tasks/<session-UUID>/`. **They are session-scoped.** When the session changes, the next executor can't read that Task store. So it can't serve as a "durable checklist" — and since `verify-done.sh` can't read that store either, the gate is a **paper gate**.

That single fact, as we confirmed it at the time, killed Option A. It also exposed the real requirement: completion state has to live **somewhere that survives session boundaries** — a file on disk, inside the repo. It's the same reason Anthropic's writing on harnesses for long-running agents stresses building a "durable project environment" up front (our research called this the Initializer-Executor pattern). A loop's state lives in the file system, not in the conversation.

> **Lesson**: Even when a native primitive looks reusable, check first that its **scope — its lifetime —** matches your requirement. "Session-scoped" versus "durable across sessions" was the difference between a design that lived and one that died.

## 3. The design: completion state in one file, passing decided by exit code

What was left after scrapping Option A is simple.

**(a) A single authority for completion state: `checklist.json`.** At the time it lived at `docs/works/<W>/checklist.json`, one per Work; today it sits next to `plan.md` in each plan directory, at `docs/plans/<date>-<slug>/checklist.json`. That one file owns completion state. The schema is minimal:

```json
[
  { "id": "R2", "description": "verify-done gate",
    "acceptance": "FAIL while the active checklist is incomplete",
    "verify": "bash scripts/verify-done.sh", "passes": false }
]
```

Items are derived from the plan (back then `planning-results.md`; today the completion-criteria section of `plan.md`, headed `## 완료 조건`), and `passes` is **always forced to false on creation** — a default-FAIL contract. Collapsing state down to one representation was deliberate too. At the time we stripped the status column out of `progress.md` and left it as narrative only, so completion state could never drift between two places. (`progress.md` has since gone away along with the Work system; today the only persistent state is `plan.md` and `checklist.json`.)

**(b) A command decides what passes, not the model.** The heart of it is the pass operation. The model saying "this is done" does not set `passes: true`. The checklist tool's `complete <id>` (called `pass` when this post was written) **actually runs** the item's `verify` command and flips it to passed only if the exit code is 0. Here's a trimmed version of the current [`checklist.py`](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/tools/checklist.py):

```python
def cmd_complete(plan_dir, item_id):
    # ... look up the item ...
    rc, tail = _run_verify(verify, plan_dir)  # from the repo root, 600s timeout
    if rc != 0:
        # A failed verify never flips — no pass without proof
        return 1
    target["passes"] = True
    target["evidence"] = f"verify exit 0: {verify}"
```

That one line — `if rc != 0: return 1` — is the crux of the whole design. Whether an item passes is decided by the raw exit code of its verify command, not by the model's sense that it's finished.

There is a limit worth stating honestly, though. What this layer prevents is *marking a pass without running verify*. It does not prevent *writing `true` as the verify command*. The design assumes the `verify` string is derived from the plan; a trivial verify the executor invents for itself (`true`, `echo ok`) has to be caught in **plan review**, not by this code. A gate is only as honest as its inputs — and that's exactly the point the fresh-context adversarial review of this design hit on (section 6 below). Also, `passes` is just a record that verify succeeded at the moment it flipped, so a regression after that point won't show up in a status check. The current tool has an opt-in `verify` command that reruns every item's check, but the automated gate doesn't run it.

**(c) `verify-done.sh` reads this file directly and judges deterministically.** If any `passes: false` remains in the `checklist.json` of an active Work (at the time) — today, of an active plan, meaning a `plan.md` whose `status` isn't `done` — the kit repo's completion gate FAILs. No checklist, no check (so nothing regresses). It's a machine gate, not a paper gate.

On top of that we added a test ratchet: if the number of tests or asserts in the diff goes down without a `TEST-RATCHET-ALLOW` marker, the gate FAILs. The workaround of "delete the test so the implementation passes" is blocked in code, not by prose discipline. This check also lives in the kit repo's `verify-done.sh`.

## 4. An honest statement of scope: what we didn't reinvent

The most important decision in the design was **what we chose not to build**.

The kit doesn't implement its own "fresh-context-per-iteration loop engine." Our reasoning at the time was that a plugin can't spawn new sessions programmatically (`/loop` and ultracode are user-triggered and interactive-only). So the loop engine is **delegated to native features**: in-session iteration uses a fresh subagent per Task, and cross-process iteration uses native features the user triggers. What the kit adds is only the **state and gate layer** of that pattern. Reimplementing something that already exists natively is technical debt, not a feature.

In the same spirit, we resisted the urge to write a new rule file. The discipline went into **a line or two in documents that already existed** — in the `loop-engineering` rule: "Re-read the original plan, not a summary" (conversation summaries degrade over long loops), and "Stop when there's no progress" (judged by an observable signal, not the model's claim that it's "still working"). Today that rule reads "re-check the original `plan.md`" and "if the same item ends twice in a row with no new commit and no checklist pass, escalate and stop." Protecting a single source of truth matters more than adding more rules.

## 5. Once again, the author is contaminated

After finishing the implementation — after `verify-done.sh` had gone green — I handed the code to **an adversarial reviewer with a fresh context**. That was the lesson of the [previous post](/blog/harness-engineering-in-practice/) put straight into practice. Passing a completion gate is not the same as being free of defects. Self-verification misses the holes you believe you've already closed.

We wrote the principle itself into the kit as well. The [`review-code` agent definition](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/agents/dev/review-code.md) states that "author ≠ verifier (fresh context, read-only)" is **met**, but honestly records that "self-preference bias in a reviewer from the same model family (judging its own family's output more leniently)" is still an **open gap**. Writing down what you've satisfied separately from what you haven't is the only kind of record the next person can actually trust.

## 6. What that review actually caught

Principles sound good, but verification speaks through results. The fresh-context reviewer found **two real blockers** in code that had already gone green.

**One: the completion path never worked in the first place.** I had computed the working directory for running verify as a fixed number of levels above `work_dir` (`parents[2]`). But the actual Work path at the time was `docs/works/active/<W>/`, and at that depth `parents[2]` was `docs/`, not the repo root. The result: perfectly normal verify commands like `pytest tests/...` or `./scripts/x.sh` all exited 1 with "file not found" → passes were rejected forever → the completion gate would **FAIL forever**. Code built to judge completion was making completion impossible. It was fail-safe (no false PASS), but the feature itself was dead. I fixed it to find the real root with `git rev-parse --show-toplevel` — which works no matter how deep the plan directory is, so it still holds now that the path convention has changed.

**Two: it missed the very bypass it was meant to block.** While building a safety net that pulls `.py` files written via Bash into verification (the `stop-validator` hook), I had only detected shell redirects (`>`, `tee`, `sed -i`). The reviewer pointed out that the exact codegen vector this defense was aimed at — `python -c "open('gen.py','w').write(...)"` — uses no shell write operator, so it **walked right through**. I extended detection to cover interpreter inline writes (`open(...'w')`, `write_text`, `.write(`).

On top of that, the reviewer caught section 3 of this very post asserting that "the party under test can't set the gate's inputs." Since the executor writes the `verify` strings itself when it `init`s the checklist, that claim only holds when verify is honest. So both this post and the code's docstring were fixed to state that limit (the current wording in section 3 is the result).

The lesson is the same as last time, only sharper. **My code was green.** It passed every machine gate. And still the completion path was dead and the defense had a hole in it. Neither is something self-verification would ever have found. The author is always contaminated.

---

**One side effect.** During the long session for this work, tool calls kept breaking and work kept stalling midway. I chased the cause from plugins to tunnels to the model, but what was left after ruling things out was **long-context degradation**: when a session stretches out over hours, generation of special tokens (function calls) is the first thing to become unstable. It was exactly the "context rot" we had just been researching. Compacting the context (`/compact`) fixed it immediately. A slightly embarrassing but honest footnote: we hit the very failure the theory predicted.

## What changed since

Updated 2026-10-02. The body stays a record of July 2026; where things differ today, the text says "at the time" or "today."

- **The Work system was removed (v4.0.0).** `docs/works/<W>/`, `planning-results.md`, and `progress.md` are gone, replaced by a single plan file (`docs/plans/<date>-<slug>/plan.md`). `checklist.json` still sits beside it, and each item's `verify` is derived from the plan's completion-criteria section.
- **`checklist pass` became `checklist complete` (v5.0.1).** Only the name changed; behavior (pass only on verify exit 0) is the same. The old `pass` name is accepted as an alias until 6.0.0.
- **The checklist tool moved (v5.2.0).** `checklist.py` moved from `plugins/common/hooks/` to `plugins/common/tools/`. `scripts/checklist.sh` is a wrapper that exists only in the kit repo; in a plugin install you call `tools/checklist.py` inside the plugin directly.
- **`verify-done.sh` is now explicitly a kit-repo-only gate.** The checklist completion check and the test ratchet live in the kit repo's gate and aren't shipped in the plugin. What it checks also changed from "active Work" to "active plan" (a `plan.md` whose `status` isn't `done`).
- **The `loop-engineering` rule was reworded.** Re-anchoring now points at the original `plan.md`, and "stop as idle after zero commits" became a no-progress guard: "if the same item ends twice in a row without progress, escalate and stop." The rule is now injected only when there's an active plan.
- **The kit was slimmed down (v5.0.0).** More than half the agents were cut, along with some skills and rules, but the `review-code` agent, the `loop-engineering` rule, and the `stop-validator` hook mentioned here all remain. Today, the `auto-dev` skill is what creates the checklist and passes items one at a time.
- **Terminology cleanup.** "Initializer-Executor" isn't a kit feature; it's the name our research gave to Anthropic's long-running harness pattern, and the wording in the body was adjusted to say so.
