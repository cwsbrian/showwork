---
name: showwork-review
description: Review a coding session and its change together: user requests, decisions, agent claims, full diff, adversarial cases, and runtime evidence. Publish one prioritized Showwork review only when explicitly invoked.
disable-model-invocation: true
---

# Showwork Review

Use only for an explicitly invoked Showwork review command. Ordinary requests and discussion about this package do not activate it. This single review covers the coding session and its resulting change, including adversarial checks. Do not edit production code or apply fixes unless the user asked. Preserve local changes and the user's authorization boundaries.

Start `companion.py start --project /absolute/project --type review --agent <claude|codex> --require-app` through the [companion guide](../showwork/references/companion.md#show-that-work-started). This is the one public Showwork review workflow. If the Showwork app cannot open, report that limit rather than moving the walkthrough into a separate browser or simulator. Append short, confirmed findings with `progress` as they are validated, and publish one review in the app.

## Establish the session, change, and rules

Identify the requested session and change. For an active session, use the conversation and tool results already available. For an earlier or linked session, use its explicit session ID/link and the host's supported read-only history or terminal tools; confirm the session belongs to the intended project/worktree. Do not search unrelated private sessions or pretend a report's stored session ID contains a transcript. If the session record is inaccessible, ask for that record or mark the session part unverified while reviewing the available change. If the session produced no code change, review its requested outcome and evidence, and mark code review not applicable rather than inventing a diff.

Read the user's original request, later corrections and choices, the agent's commitments, claimed checks, tool results and final handoff. Build a short list of the outcomes the user actually authorized. Resolve apparent conflicts by the latest explicit user direction. A later code change is not automatically proof that an earlier request was handled; trace the request to the implemented behavior and evidence. Keep session observations tied to a message, action or result, not a vague impression of the agent.

Identify the intended behavior, acceptance criteria, target base and reviewed head/local state. For a branch or PR, compare against the appropriate merge base; for local work, include staged, unstaged and relevant untracked files. Read the complete relevant diff, added files, affected callers, contracts and existing tests. Distinguish work in scope from pre-existing defects. If the base or goal cannot be inferred, inspect independent context first, then ask for the missing fact and state the resulting coverage limit.

Read applicable `AGENTS.md`, team review rules and human reviewer lessons. When `review-lessons` is installed or the repository requires it, run its `check` mode and perform its concrete checks; do not merely cite a lessons file. Prefer a few scoped invariants tied to affected paths or contracts over generic style rules. Check an apparent rule violation against valid exceptions and unrelated code so the report stays low-noise.

## Trace, challenge, and validate

Check the session against the delivered result: missed or only partly implemented requests; unsupported completion or test claims; a user correction that was acknowledged but not applied; unauthorized scope expansion or external side effects; and an important failure hidden by the handoff. Judge these by their effect on the user's outcome. Do not report ordinary exploration, harmless wording or a reasonable implementation choice as a session defect. Separate a wrong claim from a code defect even when both share a root cause.

Follow each changed execution path from entry point through writes, side effects and response. Scale depth to consequence. For high-risk changes, use distinct passes for (1) session intent and repository rules, (2) ordinary bugs and affected callers, and (3) credible adversarial cases such as unauthorized access, stale state, repeated/concurrent actions, partial failure, boundary input, migration/compatibility and recovery. Use independent reviewers only when available and useful for a large or risky change; do not treat multiple opinions as proof.

For every suspected defect, identify a concrete trigger and causal path. Run a focused safe reproduction when practical; check the current source, test result and visual state before reporting it. Confirm that the issue was introduced by the reviewed change or clearly label it as pre-existing. Remove duplicates, style-only comments and speculative concerns without a plausible path. Test success alone does not establish correctness; compare the session's claims and observed evidence against the acceptance criteria and uncovered failure behavior.

Run the affected experience through the Showwork app:

- **Web:** start the project with its existing dev/test setup, then open and operate the page via `companion.py browser open --project ... --url ... --require-app`. Connect Playwright to that command's CDP endpoint for interactions and screenshots. Do not launch a separate visible or headless browser for the reviewed flow.
- **iOS:** follow [mobile runtime evidence](references/mobile.md). Build/install the reviewed app on a selected Simulator, attach it with `companion.py simulator open --project ... --udid ... --require-app`, and operate and capture that same device. Do not open Simulator.app as a separate viewing window.
- **Android:** the current Showwork app has no Android emulator tab. Review source and safe tests, and mark the Android runtime scenario unverified rather than substituting an external emulator window or mobile web viewport.
- **API/CLI/library:** exercise the affected interface with safe data and record observed outputs; do not invent UI work.

Do not make real purchases, production writes or destructive changes merely to reproduce a finding. If an in-app session or runtime cannot be established, continue source review and other safe checks, then name the exact gap. A screenshot proves only what is visible at capture time; pair it with the steps, logs or tests needed for a behavioral claim.

## Report findings first

Order actionable findings by practical severity: P0 urgent, P1 high, P2 normal, P3 low. Give each a stable ID and label its evidence as **session**, **code**, or **both**. For code, give the narrowest useful file/line, trigger, expected versus actual behavior, impact, evidence and minimal fix direction. For a session finding, identify the relevant request/decision and the contradictory action, result or claim with a turn, timestamp or artifact when available; state the practical impact and what remains to be done. Say which claims were reproduced at runtime and which follow from inspected code or transcript. A source-confirmed defect can be actionable even when runtime reproduction is unavailable; do not relabel its cause as unverified merely for lack of a screenshot.

After findings, summarize the reviewed session and revision, requested outcomes covered, checks actually run, relevant coverage gaps and remaining uncertainty. If no actionable defect was found, say so **within the reviewed scope**; do not imply an unavailable transcript or untested criterion passed. Keep blocking criteria without evidence visible as limitations, separate from confirmed defects. Explain in the user's language with clear everyday words, while preserving exact paths, values and technical evidence where needed.

Publish a single `mode: "handoff"` report with `companion.py publish --project /absolute/project --file <json> --type review --agent <claude|codex> --require-app`. Lead with combined findings; show a compact request-to-result coverage section, session evidence, runtime checks and relevant code in `files`. Do not publish separate session and adversarial reports. Use `failed` for an observed mismatch, `verified` only for demonstrated behavior, and `unverified` for unrun or inconclusive checks; severity is separate. Inspect the rendered report and attachments in Showwork before saying it was shown. Give a brief chat summary and location, without silently switching to implementation.
