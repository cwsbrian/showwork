---
name: showwork-adverial-review
description: Perform an explicitly requested adversarial review and show findings with evidence in a localhost browser. Use for Showwork adverial-review or adversarial-review requests; for mobile apps, run the reviewed build in a simulator/emulator and attach actual screenshots. Review only unless fixes are authorized.
disable-model-invocation: true
---

# Showwork Adversarial Review

Use only for an explicitly invoked Showwork command (or as supporting guidance for that command). Ordinary tasks and discussion about this package do not activate Showwork. Keep activation scoped to the invoked task.

Keep the public command spelling `adverial-review`. Use the user's language. This is a focused review with a visual report, not an implementation or approval workflow.

Explain in the user's language with short sentences and everyday words a third-grade child could understand, while speaking respectfully to an adult. Lead with what changed and why it helps; explain unavoidable technical terms immediately, keep chat brief, and put code paths/commands and deeper detail behind optional browser details. Keep important risks, failures and unchecked behavior visible; simplify wording, not facts.

## Establish scope and challenge assumptions

Read [Showwork Review](../showwork-review/SKILL.md) and follow its scope, full-diff, severity and evidence rules. Reuse the user's stated branch/PR/local scope. When no scope is given, inspect the working tree and branch context; ask only if the review target/base cannot be inferred. Do not silently review only HEAD. Record base, head and local changes so findings and captures identify the reviewed state.

Trace affected callers, contracts, data writes and failure paths. Choose adversarial cases from the actual change: unauthorized access, stale state, repeated/concurrent actions, partial failure, boundary input, incompatible callers or migrations. Attempt focused reproductions using safe local/test data. Keep confirmed causal defects separate from suspicions, missing evidence and pre-existing unrelated defects. Do not invent a finding quota or treat style preferences as defects. Do not fix production code unless requested.

For each actionable finding, retain a stable ID, practical priority (P0 urgent, P1 high, P2 normal, P3 low), narrow source location, trigger/reproduction steps, expected versus actual behavior, impact, evidence and a minimal fix direction. Distinguish runtime reproduction from a source-derived causal path. A source-confirmed defect need not be mislabeled unverified just because no UI reproduction is possible; its runtime scenario may still be unverified.

## Run the affected experience

Identify the target from repository manifests and build/run documentation, not just the presence of a small-screen screenshot.

- Web: run the project through its existing development/test setup, exercise affected flows and capture relevant states with available browser tools.
- Mobile (native, Flutter, React Native, etc.): read [mobile runtime evidence](references/mobile.md). Build/install the reviewed app, boot or reuse a suitable simulator/emulator, launch it, exercise the affected flow and capture actual screens. Do this for the targeted platforms; do not silently substitute Android for iOS or a desktop viewport for either. If scope does not specify platforms, derive them from affected code and state coverage. Missing tools/runtime/build credentials must produce an explicit gap, not a fabricated screenshot or a clean mobile verdict.
- API/CLI/library: exercise the relevant interface; use observed outputs and connected diagrams. Do not add unrelated UI work.

Use project-provided test accounts/data. A review does not authorize real purchases, production writes or deletion of unrelated simulator/user data. Starting an available local simulator and running an authorized test build needs no extra approval. Continue source review and other safe checks when one runtime step is blocked.

## Publish the review on localhost

Read the shared [browser companion guide](../showwork/references/companion.md). Reuse `../showwork/scripts/companion.py`, resolved from this skill directory. Run `companion.py path --project /absolute/project` first and write handoff JSON, captures and one-off scripts inside that returned temporary directory, never in the project; start `serve --project /absolute/project` in a persistent tool session, then `publish --project /absolute/project --file /absolute/report.json`. Use `mode: "handoff"`, never decision mode. Open the full returned localhost URL and include it in the final response. If the server/browser is unavailable, retain the artifacts and report the precise limitation.

Build the page around the findings, not a generic feature tour:

1. **Review verdict and scope:** actionable findings by severity, reviewed revision/local state, important coverage gaps. With zero findings, say “no actionable defects found in the reviewed scope”; do not imply untested behavior passed.
2. **Finding walkthroughs:** explain the trigger → failing branch → impact with a connected diagram, or the affected screen with its actual capture. Keep full path/line and reproduction details below the visual. Use the existing routing/ERD/architecture guidance for affected domains; tables supplement diagrams.
3. **Runtime captures:** for mobile, attach screenshots from the simulator/emulator as `kind: "observed"` sections with `image` paths, device/OS, app/build identity, scenario/actions, capture time and what the image actually shows. Connect them to finding IDs or the exercised acceptance criterion. Keep hypothetical fixes/mockups separate and labeled `proposal` or `explanation`.
4. **Evidence and gaps:** list concrete checks, outcomes and remaining work. In `checks`, use `failed` for an observed mismatch, `verified` for behavior actually demonstrated, and `unverified` for unrun/inconclusive runtime criteria. Severity is separate from check status. Include mobile launch/interaction/capture gaps even when source review found no defects.

Inspect the rendered report, including attached images, before claiming it was shown. An image path or server exit code does not prove a capture rendered. Give a brief chat summary of findings, the browser URL and important limits. Keep fixes as recommendations unless separately authorized.
