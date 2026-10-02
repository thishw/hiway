---
title: "Harness Engineering in Practice: Hardening Git Isolation in a Parallel-Agent Toolkit with Two Adversarial Reviews"
date: 2026-07-02
lastmod: 2026-10-02
description: "A case study in applying 'Agent = Model + Harness' to a real Claude Code toolkit: fixing race conditions in parallel work, and how a second adversarial review caught a verification bypass the first one missed."
tags: ["harness engineering", "adversarial review", "git worktree", "race conditions", "verification gates"]
translationKey: harness-engineering-in-practice
aliases: ["/posts/2026-07-02-harness-engineering-in-practice/"]
alias_to_lang: ko
---

Harness engineering reads clearly on paper. The real test starts when you put those principles on top of a tool people actually run. This post records what happened when we applied the ideas from our [harness and loop engineering landscape](https://github.com/This-HW/hiway-kit/blob/main/docs/research/2026-07-harness-loop-engineering.md) to our own project, hiway-kit. It is also the story of how two rounds of adversarial review showed that a flaw we "knew" we had fixed was still there.

> **Key takeaways**
>
> Parallel agents are made safe not by how they *enter* isolation, but by the **protocol for merging back** and by atomic access to shared state.
>
> The textbook "worktree isolation + merge" is necessary, not sufficient. Isolation doesn't make conflicts go away; it **defers** them to merge time.
>
> And the most valuable lesson: **the author agent is compromised.** Self-review misses the holes it believes it has already closed. An independent review in a separate session is what caught them.

*This is a record of work done on July 2, 2026 (v2.8.0 at the time). Where the kit has changed since, the text says "at the time", and the changes are collected under "What changed since" at the end.*

## 1. Why parallelism is the harness's weak spot

The toolkit speeds work up by dispatching several specialist agents in parallel. Because they edit files at the same time, each one works in its own **git worktree**, and the results are merged back afterward.

That is exactly where the industry had converged, too. Every parallel-agent tool we looked at landed on the same design: **worktree (or container) isolation, a branch per task, merge after review.** But the same research came with a warning:

> Isolation is necessary, not sufficient. You also need runtime isolation, conflict prediction, and integration review.

Measured against that bar, our toolkit was missing precisely the "sufficient" part.

## 2. Diagnosis: a way in, but no way back

**First, there was no merge protocol.** We had a policy for sending agents *into* worktree isolation, but no norm for when and how they came *back* (merged) after passing verification. Isolation doesn't remove conflicts, it postpones them to merge time. Without rules for that moment, every postponed conflict lands at once.

**Second, three race conditions on unlocked shared state.** These were places where parallel sessions did read-modify-write on the same file with no lock.

| Shared state (at the time) | Problem | Consequence |
|---|---|---|
| Stop hook retry counter (shared under `/tmp`) | Scoped per repo, not per session | Parallel sessions overwrote each other's counters |
| Feedback ledger | Two parallel reviews wrote to it at once, unlocked | Lost update: one side's entry disappeared |
| Work ID allocation (`work.sh`) | Computing the number and creating the directory weren't atomic (TOCTOU) | Concurrent creation could hand out the same ID twice |

The nature of the problem was clear. This wasn't something a smarter agent would fix. It was a **structural flaw in the harness**: the kind of mistake harness engineering exists to seal off.

## 3. First implementation, first adversarial review

The fix followed the two axes the research laid out: **feedforward and feedback**.

- **Feedforward (steering up front):** we wrote a new rule file, `rules/parallel-worktree.md`, that spelled out the merge-back norms. At the time, it was injected into agents at session start. It said: merge back only after verification passes; split file ownership; and on a conflict, don't pick ours/theirs on your own — escalate to the git-workflow agent.
- **Feedback (observing afterward):** each of the three races got its own fix — per-session scoping, a file lock, and atomic ID claiming — sealed with regression tests. The ledger lock favors availability: if it can't be acquired within five seconds, it logs a warning and proceeds without the lock.

Then, following the principle that **the author agent is compromised**, we handed verification not to the session that wrote the code but to an **adversarial reviewer in a separate session**. The first review paid for itself immediately, with two High-severity findings:

1. **Session scope applied in the wrong order.** The code that scoped the counter per session ran *after* the reset path, which quietly neutralized the core fix. We had reintroduced the very bug we set out to remove.
2. **Predictable temp-file paths.** On a shared host, someone could plant a symlink and get an arbitrary file overwritten (CWE-59).

We fixed all ten findings and got an **ACCEPT** on re-review. Had we stopped there, the work would have looked complete.

## 4. What the second review found: the bypass we "knew" we'd closed

We didn't stop. We ran one more round, this time a **multi-agent review in which several agents dug in from different angles at once**. Reviewer agents each hunted for defects, and every finding was adversarially re-checked by an independent verifier. The 27 findings that survived verification collapsed into 10 root causes. One of them hurt.

When the auto-dev pipeline finishes verifying, it leaves a marker that says "this was just verified; the Stop hook shouldn't verify it twice," and writes a **fingerprint of the working-tree state** into it. The Stop hook skips verification only if that fingerprint still matches. In the first review we'd been told the fingerprint missed new files, so we added `git status --porcelain` and declared the gap closed. The second review asked: `porcelain` records the *path* of an untracked file, not its *contents*. So what happens if…

> …you **edit the contents of an already-untracked `.py` file after verification**? The fingerprint stays byte-for-byte identical. The marker is judged still valid, and the Stop hook skips verification entirely. Broken, unverified code slips silently through the safety net.

The exact bypass we had declared closed in round one was still open. It was invisible to the session that had just verified its own work. It is a working example of the principle that **a verifier doesn't have to be bigger, but it has to be different.**

### A root-cause redesign

Instead of patching, we changed what the fingerprint means. Rather than hashing `git status` output, it now **hashes the contents of the exact set of files the hook verifies**, so the thing being fingerprinted and the thing being verified are structurally the same. Content changes to untracked files now change the fingerprint, which **closes the bypass**. Changes to files outside verification scope (review write-ups and the like) leave it untouched, so the marker isn't needlessly invalidated either. The Stop hook (`hooks/stop-validator.py`) still fingerprints this way today.

The second review also caught a contradiction in the design. The merge rule said "the main session merges sequentially," while each agent was told (at the time) to "merge yourself back once verification passes." The main session had no way to serialize when sub-agents returned, so the rule was unenforceable. The fix was to move the rule onto a **lever the orchestrator actually controls**: not "sequential merge" (impossible) but **"sequential dispatch"** (possible). Parallel safety now comes from splitting files at dispatch time, not at merge time. The rule file still carries this principle, under the name "sequential delegation."

## 5. The lesson: a harness seals mistakes into the system

> *Every time an agent makes a mistake, engineer the system so it can never make that mistake again.* — Mitchell Hashimoto (paraphrased)

Every fix we made had this shape. Where a race was possible, we added locks and atomic operations. Where there was no norm, we wrote a rule. Where verification could be bypassed, we made the verification scope and the fingerprint match. And we left regression tests behind to keep each fix sealed.

```text
implement → adversarial review (separate session)
  ├ defect found → fix the root cause → seal with a regression test → back to review ↺
  └ no defect    → verified done
```

The single most valuable point: **one round of self-review cannot see the blind spots in its own logic.** Because we ran a review from a different angle even after round one said ACCEPT, we caught a real bypass before release. Verification isn't the claim "it passed." It's **what survives repeated attempts to disprove it, by different eyes.**

## FAQ

**Q. If the work is isolated in worktrees, why do conflicts still happen?**

Worktree isolation separates files *while* each agent works. It says nothing about the moment the work is *combined* into one branch. Without a merge-back protocol — when, in what order, and who gets a conflict — the deferred conflicts all go off at merge time.

**Q. We already had one review. Why another?**

Whoever wrote the code (or just verified it in round one) re-checks their own premises; they don't question them. In our case, a bypass that round one had marked "closed" was still open in round two. Blind spots only show up when the verifier comes from a different angle and a different session.

## Conclusion: we fixed the loop, not the model

We didn't wait for a stronger model. We **designed, verified, and refined the loop** so that the same model couldn't repeat the same mistakes. Races were sealed with locks, the missing norms with a rule, the verification bypass by aligning scope. And we put the whole thing past different eyes, twice, in adversarial review.

**Models are converging; harnesses are where the difference lies.** And a harness is only as good as how honestly it runs a verification loop that is willing to doubt even itself.

## References

- [Harness & Loop Engineering: the mid-2026 landscape](https://github.com/This-HW/hiway-kit/blob/main/docs/research/2026-07-harness-loop-engineering.md) — the conceptual groundwork for this post (research note, in Korean)
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — Anthropic Engineering
- [Harness engineering for coding agent users](https://martinfowler.com/articles/harness-engineering.html) — Birgitta Böckeler (the feedforward/feedback framing)
- [My AI Adoption Journey](https://mitchellh.com/writing/my-ai-adoption-journey) — Mitchell Hashimoto

## What changed since

*Updated 2026-10-02.*

- **The merge rule is no longer injected every session.** Since v5.0.0, [`rules/parallel-worktree.md`](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/rules/parallel-worktree.md) is a reference rule: a session only gets a one-line index entry telling it to read the file before parallel delegation or merging.
- **The rule no longer prescribes an isolation mechanism.** It states invariants only (disjoint file ownership, no arbitrary ours/theirs, no shared-state updates inside an isolated tree) and treats native worktree isolation as one option among several.
- **"Merge yourself back" became "return, then integrate."** Workers return verified artifacts; only a designated integrator merges. A worker's "green" report is not a gate. "Sequential dispatch" lives on as "sequential delegation."
- **Conflict escalation means reporting, not resolving.** Since v2.17.0 the git-workflow agent doesn't resolve conflicts itself; it backs out, reports what conflicted, and lets the user choose.
- **Work IDs and `work.sh` are gone.** v4.0.0 removed the whole Work system. A plan is now identified by its directory name (`docs/plans/<date>-<slug>/plan.md`), so there is no ID allocation to race on. The third race above is historical.
- **Stop hook state left the shared `/tmp` path.** The `/tmp` sharing in the table is the pre-fix state. The second-review fixes in the same piece of work moved the marker, retry counter, and ledger lock into a per-user directory (`$TMPDIR/claude-<uid>`, mode 0700). v3.34.2 tightened this further: if that directory is a symlink or has the wrong owner or permissions, the hook rejects it and falls back to a private temporary directory, never the shared one.
- **The feedback ledger tool moved.** v5.2.0 moved it from `hooks/` to [`plugins/common/tools/feedback_ledger.py`](https://github.com/This-HW/hiway-kit/blob/main/plugins/common/tools/feedback_ledger.py). The locking behavior (proceed unlocked after five seconds) is unchanged.
- **We dropped the reviewer head count from round two.** The original number of reviewer agents can't be confirmed from the surviving records, so it was removed. The 27 verified findings match the changelog.
