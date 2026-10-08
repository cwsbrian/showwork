---
name: showwork-review
description: Review a software change against its intended behavior, full diff, and evidence, with risk-proportional adversarial checks. Use for Showwork code or implementation reviews; report findings without applying unrequested fixes.
disable-model-invocation: true
---

# Showwork Review

Use only for an explicitly invoked Showwork command (or as supporting guidance for that command). Ordinary tasks and discussion about this package do not activate Showwork. Keep activation scoped to the invoked task.

Report actionable defects and evidence gaps in the requested change. Do not edit production code or apply fixes unless the user authorized fixes. Read repository instructions and preserve local changes. Use the user's language and the repository's review conventions when available.

Explain in the user's language with short sentences and everyday words a third-grade child could understand, while speaking respectfully to an adult. Lead with what changed and why it helps; explain unavoidable technical terms immediately, keep chat brief, and put code paths/commands and deeper detail behind optional browser details. Keep important risks, failures and unchecked behavior visible; simplify wording, not facts.

## Establish what is being reviewed

- Identify the intended behavior, acceptance criteria, target branch or base, and head or local state. Read the complete relevant diff and added files, then affected callers and existing tests.
- For a branch or PR review, use the appropriate common ancestor with the intended target when that is the comparison the user requested. Do not silently default to the last commit or compare against an unrelated branch.
- If the request includes current local changes, cover staged, unstaged, and relevant untracked files. Distinguish pre-existing work from the requested change. Inspect file names before opening unrelated or potentially sensitive generated artifacts.
- If the base cannot be reliably inferred, state the ambiguity and ask for the missing information while inspecting independent context. State any limits on review coverage.

## Challenge the behavior

Follow changed execution paths and compare them with the intended outcome. Scale depth to the impact: a copy change needs little scrutiny; permissions, data writes, shared contracts, concurrency, or migrations need concrete failure analysis.

Choose plausible failure cases, not a generic checklist. Examples include boundary input, missing or stale state, partial success, repeated actions, conflicting updates, incompatible callers, or a user unable to complete the UI flow. Look for the shared root cause when multiple callers are affected.

Run focused, safe checks with existing capabilities when they can confirm a concern. Verify the rendered result for visual claims when a runnable UI is available; distinguish a source-level suspicion from an observed visual defect. Do not create real external side effects simply to reproduce a finding without authorization.

Review is a challenge to the implementation's assumptions. Test passing alone is not proof of correctness. Check whether the evidence actually covers the criteria, relevant failure behavior, and the current version of the change.

## Report only useful findings

Lead with actionable findings, ordered by practical severity. Each should contain:

- A concise title and location, with the narrowest useful file/line reference.
- The concrete triggering condition and user or system impact.
- Evidence or a clear causal path, and a minimal direction for a fix when it helps.

Do not inflate style preferences, hypothetical risks without a credible path, or missing evidence into confirmed defects. Separate observed defects from unverified criteria or environment limitations. Avoid duplicate findings for the same root cause.

Then summarize the reviewed scope, checks actually performed, and important limitations. If no actionable defect was found, say that within the stated scope; do not equate it with proven acceptance. A blocking criterion lacking evidence belongs in the limitations even when no code defect can be established. Do not silently transition from review into implementation.
