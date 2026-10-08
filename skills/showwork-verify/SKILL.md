---
name: showwork-verify
description: Verify an existing software result against observable acceptance criteria using relevant checks, runtime exercises, and visual evidence. Use for Showwork verification requests and report what is proved, failing, or unverified.
---

# Showwork Verify

Determine what the current result demonstrably does. Use the user's criteria and actual affected flow. Verification alone does not authorize fixing production code or expanding scope; report failures unless fixes are also requested. Preserve local changes and avoid external side effects outside existing authorization.

Explain in the user's language with short sentences and everyday words a third-grade child could understand, while speaking respectfully to an adult. Lead with what changed and why it helps; explain unavoidable technical terms immediately, keep chat brief, and put code paths/commands and deeper detail behind optional browser details. Keep important risks, failures and unchecked behavior visible; simplify wording, not facts.

## Define the claims

Read the task, repository instructions, relevant change, and existing validation commands. Turn important requirements into observable criteria if needed, labeling assumptions. A behavior claim should name an input or action and its expected result, not an implementation detail such as “the function exists.”

Identify the current revision and local changes so evidence can be tied to the result being checked. Existing artifacts can help only when their provenance, tested state, and relevance are established. Do not treat a prior run as evidence for changed code without assessing what changed.

## Run the smallest adequate checks

- Reuse the project's existing test and build commands. Select focused checks according to the affected behavior, plus required repository checks. Do not invent a framework or install a tool merely to complete a standard checklist.
- For behavior changes, execute at the appropriate boundary: a focused test, request/response, CLI session, or UI interaction. Static inspection, lint, and successful compilation have narrower claims.
- For UI, inspect a real render at relevant screen sizes and states when possible. Exercise changed interaction and basic accessibility, such as keyboard operation, when relevant. A screenshot can demonstrate appearance; it cannot by itself establish that an action works.
- Challenge likely failures according to consequence: boundary input, missing state, a partial failure, retries, permissions, or concurrent updates when those paths matter. Prefer a small check that could fail for the real defect over a test that simply mirrors the implementation.
- Discover available runtime tools before concluding a check is impossible. If a dependency, credential, environment, or tool is missing, record that exact limitation and run any valid narrower check. Never invent successful checks, visual artifacts, or human observations.

Avoid broad repetition after adequate checks pass. If authorized fixes change the result, rerun the affected checks and mark superseded evidence as stale. Attribute unrelated pre-existing failures carefully; do not conceal them or expand the task to fix them automatically.

## Assess the evidence

For each important criterion, record the command or action, expected behavior, observed result, and an artifact link when useful. Choose the outcome based on the observation:

| Outcome | Meaning |
| --- | --- |
| Proved within stated scope | The observation directly demonstrates the criterion for the exercised conditions. |
| Failing | The observed result contradicts the criterion. |
| Unverified | The relevant check was not performed, was blocked or inconclusive, or the evidence does not establish the claim. |

A zero exit code means that command succeeded, not that every product requirement was met. A mock proves only the behavior within the mock's boundary. An attached screenshot or manual note needs interpretation and clear provenance; do not claim to have witnessed an action someone else reported. Describe limitations when a narrower check leaves part of a criterion open.

When a persistent evidence record is useful, follow project conventions or use a concise table. The optional Showwork [evidence helper](../../scripts/showwork.py), when present in the repository or plugin bundle, records runs under `.showwork/runs/`. Resolve the script relative to this file, run it with the target project as the working directory, and inspect `--help` before using it. Its recorded results and attachment presence do not establish semantic acceptance. The skill works without the helper.

## Report the result honestly

For a multi-layer change, use the companion guide's change-specific coverage table to connect routing, schema/migration and architecture explanations to their evidence. Separate authored migrations from migrations actually applied, and source-derived diagrams from runtime observations. Do not collapse verification of these areas into one aggregate test count.

Check that routing diagrams connect meaningful branches to their actual responses, and schema ERDs connect FK/PK fields with cardinalities supported by constraints. A table or linear badge row alone does not explain a branching route or table relationships. Preserve unknowns and distinguish illustrative examples from the inspected system.

Lead with the overall verified result and any blocking failure or gap. Include the relevant evidence, material limits, and the next concrete action needed for a failing or unverified criterion. Keep a trivial verification short. Do not claim completion while a required criterion remains failing or unverified, and do not silently start fixing after a verification-only request.

When presenting an implementation handoff, use the [browser companion](../showwork/references/companion.md) in handoff mode to connect result visuals and the verified/failed/unverified criteria. This explanation has no approval button. Preserve a short chat summary and distinguish observed screenshots from explanatory diagrams.
