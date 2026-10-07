## Automatic Showwork

Apply Showwork automatically to software work. The user does not
need to name Showwork or type a skill command. Decide the appropriate depth from
the request and affected code; ordinary conversation needs no workflow.

Read the relevant skill before starting the task:
- Implementation or bug fix: `{{SKILLS_ROOT}}/showwork/SKILL.md`.
- Planning only: `{{SKILLS_ROOT}}/showwork-plan/SKILL.md`.
- Review only: `{{SKILLS_ROOT}}/showwork-review/SKILL.md`.
- Verification only: `{{SKILLS_ROOT}}/showwork-verify/SKILL.md`.

At the start of a coding task, briefly say that Showwork is active and name the
chosen path in the user's language. Do this before implementation edits, not on
every follow-up. Choose proportionately:
- A trivial, local change: inspect, edit, check, explain. No unnecessary plan or question.
- A clear request, including a simple new UI: investigate and implement directly
  when the choices are routine or already decided. Do not force a preview or UI
  confirmation before building just because the task involves a screen.
- If you need the user's visual choice: read
  `{{SKILLS_ROOT}}/showwork/references/companion.md` and present actual rendered
  alternatives in the browser companion before asking. Use its decision mode;
  a text sketch alone does not substitute for showing the alternatives. Wait
  only for work dependent on that choice, and continue independent work.
- Consequential unresolved product, business, or architecture choices: explain
  the tradeoff and ask only the necessary question; continue independent work.

Carry forward existing decisions. After implementation and verification, use the
browser companion's handoff mode to explain the result with relevant visuals:
actual screenshots when available, before/after comparisons, a flow or diagram,
and verification evidence and gaps. Read the same companion guide. Keep the
visuals proportionate and distinguish observed output from explanatory mockups.
Cover every materially changed area, not just the visible UI or a test count.
For changed routing, include a request/navigation flow diagram and a route table;
for schema/migrations, include before/after tables, data migration and rollback
details, distinguishing authored migrations from ones actually executed;
for changed architecture, show component boundaries, dependencies and data flow.
Use concrete names from the diff, source locations, reasons and relevant evidence.
Put detailed explanations in the browser; a short chat summary must not make the
browser handoff equally sparse. Omit domains that did not change.
This is a walkthrough, not another approval gate. Share the browser URL and a
short summary in chat; if the browser is unavailable, provide the saved artifact
and state the limitation instead of pretending it was displayed.
Honor planning/review/verification-only scope and any explicit user request to
skip Showwork. Do not claim completion without evidence for required behavior;
report what remains unverified. Follow the project's other applicable instructions.
