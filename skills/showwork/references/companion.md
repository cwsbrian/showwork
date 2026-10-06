# Browser companion: decide when needed, explain when done

Use this bundled companion for two distinct moments:

- **Decision:** you need a human visual choice. Render real alternatives before asking. Do not open a design-approval loop for a clear, simple task or an already decided choice.
- **Handoff:** after implementation and verification, explain the result with relevant visuals and evidence in the browser. No approval is requested. Keep a brief outcome summary in chat as well.

The companion uses Python 3.11+ with no third-party runtime dependencies. It works both in the plugin bundle and a copied Codex skill: resolve `../scripts/companion.py` relative to this guide (inside the `showwork` skill). Always pass the target project's absolute path with `--project`.

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

Each check requires `text`, `status` (`verified`, `failed`, or `unverified`), and `evidence` (the observed command/result/artifact location, or the precise limitation). Preserve failures and missing evidence. These labels are authored by the agent; the companion does not validate product correctness.

A compact handoff might show the actual screen, a three-step “action → saved state → reload” diagram, and three acceptance checks. Choose visuals for the work actually done. Do not create placeholder screenshots or fake product observations to fill the layout.

## Limits

The page and events stay local under `.showwork/visual/`. The full session URL carries a private key. Browser choices do not run code or edit product files. There is no telemetry, external API, or image-generation service. If the local browser cannot be reached, preserve the JSON and images and explain the limitation in chat; don't count a generated page as a viewed result.
