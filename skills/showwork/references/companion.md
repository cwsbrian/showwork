# Browser companion: decide when needed, explain when done

Use this bundled companion for two distinct moments:

- **Decision:** you need a human visual choice. Render real alternatives before asking. Do not open a design-approval loop for a clear, simple task or an already decided choice.
- **Handoff:** after implementation and verification, explain the result with relevant visuals and evidence in the browser. No approval is requested. Keep a brief outcome summary in chat as well.

The companion uses Python 3.11+ with no third-party runtime dependencies. It works both in the plugin bundle and a copied Codex skill: resolve `../scripts/companion.py` relative to this guide (inside the `showwork` skill). Always pass the target project's absolute path with `--project`.

## Delegate presentation, retain evidence ownership

The primary implementation/review agent owns scenario selection, browser or simulator operation, screenshot capture, and expected-versus-observed judgments. For mobile, follow the adversarial review's simulator/emulator evidence requirements. A presentation agent must not operate the application, collect replacement evidence, change findings/severity, or turn unverified checks into passes.

Delegate report JSON and static HTML/SVG authoring to a lower-cost subagent when the runtime supports model selection. Prefer **Codex Luna** (`gpt-6-luna` only when exposed by the runtime) and **Claude Haiku** (`model: "haiku"` on the native Agent invocation). An explicit user preference, such as Terra or Sonnet, overrides this default; resolve the actual available model identifier rather than guessing an alias. Do not change the main model, global subagent defaults, or user configuration. If delegation/model selection is unavailable or fails, disclose that limitation and author the report with the current agent; never claim the preferred model ran. Do not silently escalate to a different paid model.

Give the renderer a bounded packet: finalized findings, changed names/relationships, source references, exact verification statuses and limitations, screenshot paths/provenance, page schema, and one output path under `.showwork/visual/`. Start with fresh context when supported (Codex model overrides may require `fork_turns: "none"`); do not pass the full review transcript. Limit ownership to that report artifact. No product edits, app control, additional agents, publishing, or commits. This delegation is only for presentation, not a second review.

The primary agent checks the returned facts against the packet, validates the JSON with the existing publisher, then inspects the rendered report for omissions, clipping, unreadable labels and image access before sharing it. Correct presentation defects without altering evidence. Record the requested/actually used renderer and any fallback in the handoff. Model selection is runtime-dependent instruction, not a guarantee enforced by the static server; do not claim measured savings without measurements.

Model selection references: [Codex subagent configuration](https://learn.chatgpt.com/docs/config-file/config-reference) and [Claude subagent model selection](https://code.claude.com/docs/en/sub-agents#choose-a-model). Runtime capabilities take precedence over example identifiers.

## Start the browser

Run through the environment's persistent shell/session mechanism:

```bash
python3 /absolute/path/to/showwork/scripts/companion.py serve --project /absolute/project
```

Here `showwork` means the **skill folder**, e.g. `<project>/.agents/skills/showwork`, not the plugin root. The server stays in the foreground; keep the tool session alive rather than detaching a process the host may reap. It prints JSON containing `url`, `pid`, and `project`; connection info also lives at `<project>/.showwork/visual/server.json`. Check that the server responds before reusing old info. Restarting gives a new URL/key. Stop the owning terminal process with Ctrl-C when the walkthrough is no longer needed.

Open the full `url` using an available browser-opening tool such as `open_in_codex`, and include that clickable URL in chat. In a local desktop environment, `serve --open` can open the system browser instead. Do not require another permission question to show a visual already needed for the authorized task. This server binds only to `127.0.0.1`; a remote user's browser may need the environment's existing port forwarding. Do not pretend a local URL is reachable from another machine.

## Publish a page

Author a JSON file, then run:

```bash
python3 /absolute/skill/showwork/scripts/companion.py publish \
  --project /absolute/project --file /absolute/project/.showwork/visual/handoff-source.json
```

The open browser updates automatically. Every publish creates a new version. Keep source files and screenshots under `.showwork/visual/` so project source remains separate. The helper copies referenced raster images into its own assets folder and serves only those files, not the project directory.

### Decision page

```json
{
  "mode": "decision",
  "title": "Choose the task layout",
  "summary": "The features stay the same; the choice affects how you scan tasks.",
  "question": "Which layout fits how you work?",
  "options": [
    {"id": "list", "title": "One list", "body": "Fast scanning in a compact space.", "html": "<div style='padding:20px;background:#eef4f1;border-radius:12px'><h2>Today</h2><p>☐ Buy groceries</p><p>☑ Read a chapter</p></div>"},
    {"id": "columns", "title": "Separate states", "body": "A clearer split between pending and done.", "html": "<div style='display:flex;gap:16px'><section><h2>To do</h2><p>Buy groceries</p></section><section><h2>Done</h2><p>Read a chapter</p></section></div>"}
  ]
}
```

Use the user's language and faithfully represent each alternative. These are mockups, not proof of running behavior. The browser lets the user choose an option and submit it. Read current-version selections with:

```bash
python3 /absolute/skill/showwork/scripts/companion.py events --project /absolute/project
```

Do not busy-poll. Wait for the user to reply, or use a supported bounded wait while continuing independent work, then read the events. A saved click does not itself wake an idle agent; tell the user to continue in chat if necessary. Combine the latest submitted selection with the user's chat feedback; an explicit correction in chat takes precedence. Old versions' selections cannot decide new alternatives. The choice applies only to the displayed question, not permission to deploy or expand scope.

### Handoff page

Use `mode: "handoff"`, `title`, `summary`, `sections`, and `checks`. It has no options or approval control.

Each section requires `title`, `body`, one visual (`html` or `image`), and `kind`:
- `observed`: an actual captured result, with provenance and what it demonstrates.
- `explanation`: an explanatory flow, architecture diagram, before/after account, or annotated code example.
- `proposal`: a proposed follow-up, explicitly not implemented.

Use inline SVG/HTML for diagrams, or `image` for an existing PNG/JPEG/WebP/GIF path relative to the JSON source. HTML renders in a sandboxed frame without scripts or external network resources. It is a visual aid, not a full running-app embed. Capture the real app separately when validating interactions. Never label a recreated mockup as an observed screenshot.

Image sections keep a compact preview and an accessible original-image link that opens a new tab. Use browser-native image zoom to read tall captures; verify the original loads through the companion's authenticated asset route. Decision option images remain selection targets.

Each check requires `text`, `status` (`verified`, `failed`, or `unverified`), and `evidence` (the observed command/result/artifact location, or the precise limitation). Preserve failures and missing evidence. These labels are authored by the agent; the companion does not validate product correctness.

### Explain the changed system, not just the finished screen

Read the complete relevant diff and list materially affected areas before authoring the handoff. Use the following coverage for areas that actually changed. Combine related areas when that improves understanding; do not force a fixed number of cards or cap a substantive change at three bullets.

| Changed area | What the browser should explain |
| --- | --- |
| Router, navigation, API endpoints | Lead with a connected flow/sequence diagram with concrete paths and handlers, changed middleware/auth checks, labeled decision branches, responses and redirects. A linear row of badges/arrows cannot stand in for a branching flow. Follow with a route table: method/path or UI route, before → after behavior, inputs/outputs or status, affected callers and source location. |
| Database schema, tables or migrations | Lead with a before/after ERD of affected tables and their relationship context, even when only a column changes. Show PK/FK fields, endpoint cardinalities/optionality and added/removed/changed elements. Follow with a comparison of changed columns, types, defaults, nullability, constraints and indexes. Name migration files and explain execution order, existing-row backfill, compatibility/deploy ordering, locking or data-loss risks where applicable, rollback procedure and whether rollback loses data. Clearly label authored, locally applied, and production-applied states; do not infer execution from the existence of a migration file. |
| System architecture, services, modules or integrations | A component/data-flow diagram marking changed boundaries and unaffected context. Show concrete components, direction/protocol, dependencies, persistence, relevant failure/retry paths, and before/after responsibilities. Explain why the change was made and the practical tradeoff. Distinguish source-derived structure from runtime-observed behavior. |
| UI or user workflow | Actual screen/state captures when available, the changed interaction flow, relevant empty/error/loading/mobile behavior and accessibility checks. A recreated diagram is an explanation, not an observed screenshot. |
| Configuration, deployment or installation | Scope and path/setting changes, selection/routing behavior, upgrade/migration steps, compatibility and recovery behavior. Separate changes delivered in the code from actions actually performed in an environment. |

Start with the outcome and a scope map, then the relevant domain diagrams/tables, then verification and remaining actions. Explain **what changed, why, how it behaves, and what evidence supports it**. Keep each section's opening short so the diagram is visible first; put long traces, source locations and contracts in supporting tables or expandable details below it. Where no baseline is available, say so rather than inventing a before state. For each important behavior, connect the actual command/request, observed result, and relevant limitation. Test counts alone are insufficient. Do not expose credentials or private payloads.

The companion renders static inline HTML/SVG: draw diagrams with labeled nodes/arrows and render tables with `<table>`, `<thead>`, and `<th>`. Do not paste raw Mermaid expecting it to render, or load external scripts. Use native `<details><summary>` for optional long command output or SQL; keep important findings and risks visible. Wrap wide tables in an overflow container for small screens. Handoff sections use the full page width and expand with their content; section links help navigate a long explanation.

### Draw connections, not a paragraph disguised as boxes

For routing or schema changes, inspect and adapt [the rendered SVG examples](../assets/diagram-examples.html). They are fictional teaching examples, not evidence about the user's application. Replace their names, branches, fields, statuses and relationships from the inspected code. The HTML works without scripts; its two labeled `<section>` blocks can be used separately as handoff `html` with the shared style. No new renderer is required.

- **Routing:** separate caller/UI, API/authorization and handler/data boundaries. Connect nodes with arrowheads. Put conditions on outgoing edges (allowed/denied, found/missing, confirmed/cancelled) and connect each relevant branch to its actual status, redirect or resulting screen. Use swimlanes/sequence diagrams for cross-service calls; split busy diagrams by user action. Show only failures and transaction/cleanup/retry guarantees established by the source; identify unknown behavior instead of guessing it.
- **ERD:** use table-shaped nodes listing relevant fields with PK/FK and nullability. Draw FK edges to the referenced PK row, labeled with both endpoint cardinalities (`1`, `0..1`, `0..N`, `1..N`, or crow's feet with a legend); derive them from actual constraints, including UNIQUE and nullable FKs. Name meaningful cascade/restrict/set-null actions. Distinguish enforced FKs from application-only associations with a labeled dashed edge. Show join tables for many-to-many relationships. Mark additions, removals and changes with text or line style as well as color. Compare before/after or clearly overlay changes with a legend. Include unchanged related tables as muted context; if no relationships exist, show the isolated entity and state that fact. If the baseline or constraints are unavailable, mark them unknown rather than fabricate an ERD.
- **Readability:** keep edge labels off nodes and connectors, avoid crossings, and include an accessible SVG title/description and a short text equivalent. Use readable labels at normal desktop size. On narrow screens, use a labeled, keyboard-focusable horizontal scroll region with a minimum diagram width rather than shrinking text to illegibility. Put source citations and detailed route/schema tables below the drawing, optionally in native `details`; keep important migration state and data-loss warnings visible.

If only a label changed, explain that label change briefly; do not invent database or architecture changes to fill sections.

## Limits

The page and events stay local under `.showwork/visual/`. The full session URL carries a private key. Browser choices do not run code or edit product files. There is no telemetry, external API, or image-generation service. If the local browser cannot be reached, preserve the JSON and images and explain the limitation in chat; don't count a generated page as a viewed result.
