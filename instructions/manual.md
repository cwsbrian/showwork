## Showwork — commands only

Use Showwork only when the user explicitly invokes a Showwork command, such as
`$showwork` in Codex, `/showwork` in Claude user skills, or `/showwork:run` in the
Claude plugin. Ordinary coding requests and discussion about Showwork do not
activate it. Follow-ups belong to the invoked task only; do not carry activation
to unrelated later work. Do not automatically open a report after ordinary work.

For an invoked command, read the matching skill under `{{SKILLS_ROOT}}`:
- Result walkthrough: `{{SKILLS_ROOT}}/showwork/SKILL.md`.
- Planning: `{{SKILLS_ROOT}}/showwork-plan/SKILL.md`.
- Review: `{{SKILLS_ROOT}}/showwork-review/SKILL.md`.
- Verification: `{{SKILLS_ROOT}}/showwork-verify/SKILL.md`.
- Adversarial review: `{{SKILLS_ROOT}}/showwork-adverial-review/SKILL.md`.

Focus the result walkthrough on what changed, how it works now, what was actually
checked, and remaining problems. Explain briefly with everyday words; put technical
details behind expandable browser sections. Store reports, screenshots and one-off
scripts in `/tmp` using the companion guide, never in the project. Do not turn a
request to explain completed work into new implementation or a planning ceremony.
