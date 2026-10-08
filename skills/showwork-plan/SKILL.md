---
name: showwork-plan
description: Plan a software change through code investigation, concrete examples or previews, consequential decisions, and testable acceptance criteria. Use for Showwork planning requests without implementing the change.
---

# Showwork Plan

Make the proposed change understandable and buildable. Planning is the deliverable: do not modify production code, install dependencies, or begin implementation unless the user also requested it. Inspect files and use existing read-only capabilities as needed. Save a plan file only when requested or required by the project's workflow.

Explain in the user's language with short sentences and everyday words a third-grade child could understand, while speaking respectfully to an adult. Lead with what changed and why it helps; explain unavoidable technical terms immediately, keep chat brief, and put code paths/commands and deeper detail behind optional browser details. Keep important risks, failures and unchecked behavior visible; simplify wording, not facts.

## Understand the actual change

- Read the request, repository instructions, and relevant existing code. Trace the current behavior and affected callers; distinguish observations from assumptions.
- Describe the intended user outcome and a concrete before/after example. Define observable success, including important failure states and constraints.
- Choose detail according to consequence. A trivial change can be a few sentences. A shared contract or migration needs an account of compatibility, ownership, failure handling, and recovery where relevant.

## Make the proposal visible

Use a representation that helps a human judge the result:

- For UI, show concrete layout, content, and relevant states using an existing preview, a sketch, or a disposable prototype. Label mock data and proposed behavior. Keep any requested prototype isolated from production code.
- For behavior, show realistic input/output or an example user flow.
- For architecture, use a small diagram if relationships or data boundaries are otherwise unclear.

Do not produce decorative artifacts. Use available tools; a missing preview tool calls for an honest, clearly labeled substitute, not a fabricated rendered result.

If a visual choice needs the user's input, use the [browser companion](../showwork/references/companion.md) in decision mode with rendered alternatives. A text-only sketch is not sufficient for that interaction. Do not invent a UI confirmation step when the choice is routine or already settled. Keep the prototype separate from product code; planning-only scope still applies.

## Resolve only decisions that matter

Honor choices and authorization already given. Identify product, business, architecture, or irreversible decisions whose consequences need human judgment. When a missing answer materially changes the plan, explain the tradeoff and recommend an option. Continue planning unaffected parts while awaiting the answer.

Infer routine reversible implementation choices from the codebase. Do not block planning on a universal approval gate or repeatedly request confirmation of established choices.

## Produce a proportionate plan

Include only details useful for implementation or review:

1. The observable outcome and acceptance criteria.
2. The concrete proposed behavior or visual, and consequential decisions or explicit assumptions.
3. The smallest implementation path, reusing current components and patterns, with affected areas and dependencies between steps.
4. The credible failure modes that deserve challenge and the checks that would expose them.
5. How each important criterion will be demonstrated, including runtime evidence for behavior and rendered evidence for UI. Note environment requirements that have actually been established.

Keep proposed checks separate from performed checks. Do not present an unrun command, prototype, or future screenshot as proof. End with the plan and any unresolved decision, without claiming the feature is implemented or moving into a build automatically.
