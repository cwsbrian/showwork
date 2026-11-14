---
name: showwork-plan
description: Investigate a software change, resolve consequential choices with as many questions as the goal needs, and publish a visual, testable implementation plan. Use only when explicitly invoked for Showwork planning.
disable-model-invocation: true
---

# Showwork Plan

Use only for an explicitly invoked Showwork command. Ordinary requests and discussion about Showwork do not activate it. Planning is the deliverable: inspect code and run read-only checks, but do not modify production code or begin implementation unless the user also asked for it. Save a plan file only when requested or required by the project's workflow.

Start `companion.py start --project /absolute/project --type plan --agent <claude|codex> --require-app` using the [companion guide](../showwork/references/companion.md#show-that-work-started). This makes the work visible in the Showwork app. If the app cannot open, report that limit and stop the Showwork presentation path; do not open a separate browser or simulator. Append short, confirmed plan text with `progress` as it takes shape, then publish the final plan in the app.

## Investigate before asking

Read the request, repository instructions, relevant code, tests, and existing decisions. Trace current behavior and affected callers. When continuing an earlier plan, read its saved note, inline comments, and decision events; reconcile them with the latest chat instructions. Distinguish known behavior from assumptions. Find facts in the project or connected sources instead of asking the user to look them up.

Write down the intended user outcome, explicit constraints, and a concrete before/after example. Identify what would count as success and what could fail. Keep new features outside the requested scope in a deferred list; do not turn them into questions or tasks by default.

## Ask only questions that can change the plan

For each unresolved choice, identify its owner, consequence, and dependencies:

- **Owner:** Is this a product/business/irreversible choice for the user, or a routine reversible implementation choice the agent can make from the codebase?
- **Consequence:** Would different answers change the visible result, scope, data contract, safety/recovery, or substantial cost? If not, choose a sensible assumption and record it.
- **Dependency:** Can the user answer it now, or does it depend on another answer or research result?

Ask only user-owned, unsettled choices with a material consequence and no unanswered prerequisite. Make a recommendation with the tradeoff. A clear small task may need **zero** questions. A normal change often needs one or two; a complex change may need a few independent questions in one round. These are guides, not quotas. Recompute the unanswered frontier after each reply; stop when remaining choices are settled, safely inferred, or deferred without changing the requested outcome. Do not ask again about decisions the user already made or impose a universal approval gate.

Use a Showwork decision page when seeing realistic alternatives would help the user choose, especially for UI or workflow differences. Publish `mode: "decision"` with `--type plan --require-app`; label mockups as proposals. For nonvisual choices, ask directly in chat or an available question tool. Continue independent planning while waiting. A saved Showwork choice is automatically sent to the original agent session when connected; read its event for the exact version and honor later corrections in chat.

## Construct an executable plan

Choose the smallest credible implementation approach. For a meaningful alternative, compare two or three actual approaches against the goal, existing architecture, effort, and failure modes; explain why the chosen one fits. Do not manufacture alternatives for a trivial change.

Build the plan in this order, with detail proportional to impact:

1. **Outcome and acceptance:** observable behavior, important states, and explicit non-goals.
2. **Decisions and assumptions:** user choices, agent decisions, and unresolved items that truly block implementation.
3. **Design and boundaries:** affected components, files, callers, interfaces, data flow, compatibility, and recovery when relevant.
4. **Implementation sequence:** small tasks with clear ownership and dependencies. Each task says what changes and how completion can be checked; avoid a long file-by-file recipe for a simple change.
5. **Failure cases and checks:** realistic edge cases and the exact runtime, test, or rendered evidence that would expose them. Label checks as proposed until performed.

For UI, show concrete states in the Showwork in-app browser through `companion.py browser open --require-app`; for iOS, attach a booted simulator with `companion.py simulator open --require-app`. Follow the [in-app capture rules](../showwork/references/companion.md#capture-web-pages-in-the-app). A mockup is proposed behavior, never proof that production code works. For behavior or architecture, use a realistic input/output example or a small connected diagram when it helps.

Before publishing, trace every requested outcome and settled decision to a task and a proposed check. Check that tasks are ordered, interfaces agree across callers, failure handling is covered, and no work or approval beyond the user's scope slipped in. Fix missing coverage in the plan. Do not describe unrun checks as verified.

Publish with `companion.py publish --project /absolute/project --file <json> --type plan --agent <claude|codex> --require-app`. The report should make the outcome, visual/behavioral proposal, decisions, implementation path, and checks easy to judge. In chat, give a short summary and any genuinely unresolved decision; do not claim the feature was implemented.
