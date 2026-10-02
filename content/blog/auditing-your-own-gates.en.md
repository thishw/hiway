---
title: "Green Lights Lie: A Six-Way Adversarial Audit of the Completion Gates I Built"
date: 2026-07-03
lastmod: 2026-10-02
description: "My completion gate was green. Then I pointed six fresh-context adversarial reviewers at the whole project and found those very gates reporting failures as success. A record of verifying the verification machinery, and why 'the author is contaminated' hits hardest when you wrote the gate."
tags: ["adversarial review", "false-green", "completion gates", "security", "verification engineering"]
translationKey: auditing-your-own-gates
aliases: ["/posts/2026-07-03-auditing-your-own-gates/"]
alias_to_lang: ko
---

The three earlier pieces — [a map of harness and loop engineering](https://github.com/This-HW/hiway-kit/blob/main/docs/research/2026-07-harness-loop-engineering.md), [parallel git isolation in practice](/blog/harness-engineering-in-practice/), and [designing a durable completion gate](/blog/durable-executor-machine-gate/) — all converged on one direction: turn verification into a machine. This post is about the uncomfortable place that direction leads: **who verifies the verification machine?**

> **Key takeaways**
>
> A completion gate returning `exit 0` (green) is not the same thing as the code being right.
>
> When I let six independent adversarial reviewers loose on the whole project, the most serious defects weren't in feature code — they were in **the verification machinery itself**: **false-greens**, failures reported as success. The gates were lying.
>
> And I was the one who built them. "The author is contaminated" is never truer than when the author is writing the verification tools.

## 1. An audit that started on green

The previous release (v2.9.0) had passed every machine check. `verify-done.sh`, the kit repo's own completion gate, was green; every unit test was green; CI was green. Normally that's where you say "done."

Instead, I ran six fresh-context adversarial reviewers against the **entire** project in parallel. Each took a different dimension, and each started from the stance "this code is wrong — you just haven't found where yet":

1. Python hooks (security, races, bypasses)
2. Shell scripts (gate false-greens, portability)
3. Agent governance (consistency across every agent definition the kit had at the time)
4. Skill and rule coherence (dead references, single source of truth)
5. Docs and CI alignment (version drift, CI divergence)
6. A second, deeper re-review of the most recently merged code

What came back was everything the green light had been hiding.

## 2. The most dangerous class: false-green

Bugs come in classes. A crash is loud — at least it tells you it failed. The most dangerous kind is **quiet**: the failure that reports itself as success. In a completion gate, that's the worst case there is. The gate exists to catch failures; if it swallows them and shows green, nobody catches them.

The reviewers found five false-greens, and **several of them lived in the gates I had just built**.

**A corrupted checklist passes.** The heart of the durable completion gate was reading `checklist.json` and failing if any item was incomplete. But it treated a parse failure exactly like a missing file: "skip." One line — `echo '[]' > checklist.json` — emptying or mangling the file, and the gate passed silently. The way around the gate was to break the gate's own file. A design meant to stop the model from signing off its own work was defeated by truncating one file. After the fix, only a genuinely absent file is skipped; a file that exists but is empty, not a list, or unparseable fails.

**The test ratchet was blind on main.** The ratchet that blocks test deletion diffed against `git merge-base main HEAD`. But when HEAD *is* `main`, the merge base is HEAD itself, so the diff is empty — committed test deletions simply don't show up. Worse, if there was no `main` ref at all, it went quietly green. The ratchet failed at exactly the moment it was needed: a direct commit to main. The fix at the time was to fall back to `origin/main`, then `HEAD~1`. As it turned out, this ratchet had more holes (see the end of the post).

**Delete the helper, and the gate disappears.** If the checklist verification tool was missing, `verify-done.sh` skipped the whole check and showed green. Incomplete checklists could pile up and still pass, simply because the tool that would have checked them wasn't there. The safety mechanism failed open when one of its own parts went missing.

The shared lesson from these three: **never read absence, error, or corruption as "pass."** A gate should be green only when it is certain, and red when it doesn't know (fail-closed).

## 3. The door I locked had a twin left open

On the security side, the finding was more direct. There was a hook (`protect-sensitive`) that blocked edits to secret files — `.env`, SSH keys, and the like. Its matcher was a list of edit and read tool names, and `MultiEdit` and `NotebookEdit` weren't on it. Claude Code matches a list like that **by exact tool name** — `MultiEdit` does not match `Edit`.

So a single `MultiEdit(".env")` bypassed the secret block entirely. I'd locked the door and left an identical one right next to it unlocked. I added `MultiEdit|NotebookEdit` to the matcher and made the hook also check the path field notebooks use (`notebook_path`). I also corrected the docs, which claimed the hook "blocks secrets in commits." In reality it's path-based and doesn't touch Bash or commits — that's gitleaks' job. **A gap between what a tool actually does and what its docs promise** is a defect too.

## 4. A dead map, injected every session

The third family of defects was quiet but cumulative. At the time, the project injected its rules into context at the start of every session. Those always-injected rules contained **references to things that didn't exist**:

- Lines telling the model how to configure four agents that didn't exist (`schedule-task`, `notify-team`, and others).
- A line saying to run a nonexistent script (`./scripts/db-tunnel.sh`) "before writing."
- An instruction to "check the agent list in plugin.json" — there is no such list (agents are auto-discovered from the directory).
- The delegation-signal format of the day existed in two different versions across two rules (one with four types, one with three), and one of them declared itself the single source of truth.

None of this breaks code, but it hands the model **the wrong map** every session. The model tries to delegate to agents that aren't there and goes looking for scripts that don't exist. I removed every dead reference and aligned the delegation format on one canonical version. (The delegation signal itself was later retired outright in v2.16.0 — nothing anywhere actually parsed it deterministically.)

> **More important than fixing the defects: making a gate catch that whole class of defect.** Dead script references kept turning up, so I made `verify-done.sh` mechanically check that every `scripts/*.sh` path mentioned in the rules and agent docs actually exists. That check has since grown to cover the skill docs too, plus component paths that files in the shipped plugin use to point at each other. The next `db-tunnel.sh` gets caught by the gate, not by someone happening to notice.

In the same spirit, I closed a hole in CI. The test step read `pytest ... || echo "skip"` — so it went green **even when tests failed**. If all 25 tests added in the previous release had gone red, CI would still have passed. The verification pipeline itself was a false-green.

## 5. The author is contaminated — especially when writing gates

One claim keeps coming back in this series: "The author is contaminated. Self-verification misses the holes you believe you've already closed." This audit showed that claim in its sharpest form.

The defects I missed were in **the verification machinery itself**. I believed I'd designed a gate that wouldn't let the model sign off its own completion — and that gate was breached by a corrupted file, went blind on main, and fell open when a part was missing. My green light was real; every machine check passed. The gate was lying anyway.

I would never have found these by checking my own work, because I wrote that gate *believing* it was correct. That belief is the contamination. The only way to wash it out is to hand the work to eyes that didn't write it — a fresh context, a separate session, a reviewer who starts from "this is wrong."

## 6. What's left, and the honest limits

Every fix was verified end to end: does `MultiEdit(".env")` actually get blocked (exit 2), does a corrupted checklist actually fail the gate (exit 1), are all 169 tests and the completion gate still green. And does CI — now a CI that genuinely runs the tests — pass.

At first I left two items as "honest limits": checklist `passes` values aren't re-verified at gate time (F1), and a verify subprocess could leave grandchild processes behind on timeout (F6). Then someone told me, in effect, "don't leave it fuzzy — clean it up," and I went back and dealt with both.

- **F6 was just a bug.** I now launch verify in a new process group and kill the whole group on timeout (`killpg`). While I was there, I stopped holding the lock for the entire verify run: verification runs outside the lock, and only recording the result happens inside it. A re-audit later that same day flagged this as overstated too — a descendant that calls `setsid` or daemonizes leaves the group, and `killpg` can't reach it. So the docs now say **best-effort cleanup**, not "leaves no grandchildren."
- **F1 was a trade-off.** Automatically re-running every verify at gate time would create a bigger debt: recursion and side effects (think redeploys). So instead of "always re-verify automatically," I added an **opt-in `verify` command**. `status` stays a fast ledger lookup; when you want proof right now, `verify` re-runs every item and flips any `passes:true` that has regressed back to `false`. The automatic gate still reads only the ledger — the limit didn't vanish, but "can't" became "here's the command when you need it."

That adds one more lesson: **the label "honest limitation" is often a euphemism for "not fixed yet."** Separate the real trade-offs (F1) from bugs you simply deferred (F6), and finish the latter. That's the only way not to leave things fuzzy.

If I had to leave it at one line: **green means "it passed," not "it's right."** And if you built the machine that turns the light green, that machine is the first thing you should suspect.

## What changed since

*Updated 2026-10-02.* The post above is a record as of 2026-07-03. What has changed in the kit since:

- **The test ratchet had more holes.** In v2.16.0 it turned out that checking only the net change against the base let "add tests first, delete them later" slip through. The ratchet now also checks each commit, and the allow marker (`TEST-RATCHET-ALLOW`) is read from the commit message instead of anywhere in the diff. This post's lesson — having a gate doesn't guarantee a defense — applied to the same gate a second time.
- **The delegation signal is gone.** The delegation-signal block aligned in section 4 was removed, contract and all, in v2.16.0. No deterministic code ever parsed it.
- **Rules are no longer all injected every session.** Since v2.18.0, each rule declares a tier: `core` (always), `conditional` (only when a signal is present), or `reference` (a one-line index entry). `agent-system`, mentioned in section 4, is now a reference rule; `mcp-usage` is conditional.
- **The checklist moved next to the plan file.** When v4.0.0 removed the Work system, `checklist.json` moved under `docs/plans/<date>-<slug>/`, beside `plan.md`, and the checklist gate in `verify-done.sh` now checks only active plans.
- **The item-completion command was renamed.** In v5.0.1, `checklist pass` became `checklist complete` (the old name is still accepted as an alias). The `status` and `verify` commands and the `passes` field are unchanged.
- **The checklist tool moved.** In v5.2.0, `checklist.py` moved from `hooks/` to [`plugins/common/tools/`](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/tools/checklist.py). It still fails closed when the helper is missing.
- **The kit has far fewer agents.** v5.0.0 cut the kit's agents to less than half. The "every agent definition" that reviewer 3 covered was a much larger set than exists today.
- **`protect-sensitive` is described more precisely.** Its matcher is now [`Edit|MultiEdit|Write|NotebookEdit|Read`](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/hooks/hooks.json). Beyond path-based blocking, it does a best-effort content scan only on writes to env templates (`.env.example` and the like). The Codex distribution doesn't ship this hook, because in testing the block didn't actually stop the command.
- **`verify-done.sh` is the kit repo's own gate.** It isn't part of the shipped plugin. The gate fixes in this post protect the kit's own development; what ships to your project is the checklist tool and the hooks.
