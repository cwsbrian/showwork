# Showwork Key Code Snippets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show several short, source-backed code excerpts per file, each followed by why it matters, in future Showwork result reports and a revised Android Emulator report.

**Architecture:** A `files[].snippets[]` source format names exact line ranges in one project file. Publishing snapshots each excerpt and its original line number; the shared report renderer groups excerpt cards inside one file accordion. The legacy single-code and diff formats continue rendering unchanged.

**Tech Stack:** Python 3.11+ standard library, plain JavaScript/CSS shared by browser and Tauri, Playwright browser tests, Tauri 2/Vite.

**Spec:** `docs/superpowers/specs/2026-11-08-showwork-key-code-snippets-design.md`

## Global Constraints

- New `files[].snippets[]` contains 1–4 entries per file; each `lines: [first, last]` covers 1–20 actual source lines. Each entry needs nonempty `title` and `why`; the file retains nonempty `path` and `why`.
- A file with `snippets` cannot also carry top-level `code`, `lines`, `start_line`, or `diff`. Published snippets hold `code` and `start_line` instead of `lines`.
- Keep existing path protections: reject paths outside the project, `.git`/`.env*`, non-UTF-8 files, files over 512 KiB, and a report with more than 1.5 MiB of embedded code. Keep the 2 MiB page JSON source limit.
- The publisher reads each selected project file once and snapshots real code at publish time. No renderer-side guess about important lines and no source reread when viewing an old report.
- Existing full-file, one-range, and diff reports remain readable without migration. The selected layout is vertical: title and source line range, highlighted code with its own Copy button, then the excerpt's reason; only code scrolls horizontally in a narrow window.
- The Android revision is a new result report; keep the earlier report and its evidence. Preserve its 8 sections, 7 checks, 5 separate ADB captures, and the installed-native Android/Split verification limitation.
- Do not use desktop GUI input automation. Never stage, commit, or push code, documents, plans, or tests unless the user explicitly asks for a commit in this current task; leave implementation uncommitted.

## Review Focus

1. An excerpt points through a symlink, `..`, `.GIT`, or `.Env.local`: Task 1 must reject it before saving a report, just like legacy files.
2. A malformed excerpt has an empty reason, missing line, reversed range, more than 20 lines, or a fifth excerpt: Task 1 must reject it without silently truncating.
3. A file mixes `snippets` with legacy code/diff fields: Task 1 must reject the ambiguous form; old reports without `snippets` must still publish and render.
4. One excerpt contains HTML-looking text or a long code line: Task 2 must render text without executing HTML, keep the page within a narrow viewport, and scroll only the code.
5. Two excerpts from one file have distinct line numbers, reasons, and Copy actions: Task 2 must keep them separate inside one file accordion; Task 3 must confirm the revised Android report shows this and retains its checks/images.

---

## File structure

- `skills/showwork/scripts/companion.py` — validate `snippets` and snapshot their code in `validate(page, report_type="result")` and `attach_code(project, files)`.
- `tests/test_companion.py` — publisher acceptance, invalid input, safety and legacy-format tests.
- `skills/showwork/assets/report-view.js` — render multiple excerpt cards and reuse the existing syntax-highlighted code editor per card.
- `skills/showwork/assets/report-view.css` — vertical spacing, reason placement and narrow-window code scrolling.
- `tests/browser_companion.cjs` — real browser checks for multiple excerpts, line numbers, copying, narrow layout and old formats.
- `skills/showwork/SKILL.md`, `skills/showwork/references/companion.md` — tell future result authors how to choose and explain short excerpts; document JSON syntax.
- No new product module or Tauri API is needed: `app/vite.config.ts` already imports the shared renderer assets. Task 3 rebuilds and installs the app and updates the local skill copies with `scripts/install_codex.py`.
- Temporary revised report JSON, copied images, verification screenshots and any one-off scripts live under `companion.py path --project /Users/brianchoi/work/personal/showwork-android`, not in the repository.

### Task 1: Publish source-backed excerpts

**Files:** Modify `skills/showwork/scripts/companion.py:62-157`; test `tests/test_companion.py:210-250`.

**Interfaces:** `validate(page, report_type="result") -> dict` accepts source `files[].snippets[]` with `{title: str, why: str, lines: [int, int]}`. `attach_code(project, files) -> None` replaces each snippet's `lines` with `code: str` and `start_line: int`, while preserving the legacy file shape. Task 2 consumes the published shape.

- [ ] **Step 1: Write the failing happy-path test.** In `test_files_to_review_read_multiple_snippets_from_one_file`, publish one `src/store.ts` file with lines `one\ntwo\nthree\nfour\n`, and snippets `[2, 2]` and `[4, 4]` with distinct titles/reasons. Assert one published file, snippets `[("two", 2), ("four", 4)]`, and no remaining `lines` keys.

  ```python
  self.assertEqual(len(files), 1)
  self.assertEqual([(s["code"], s["start_line"]) for s in files[0]["snippets"]], [("two", 2), ("four", 4)])
  self.assertTrue(all("lines" not in s for s in files[0]["snippets"]))
  ```
- [ ] **Step 2: Run the focused test and see RED.** Run `TMPDIR=/private/tmp python3 -m unittest tests.test_companion.CompanionTest.test_files_to_review_read_multiple_snippets_from_one_file -v`; expect the old publisher to include the full file or reject/mishandle `snippets`.
- [ ] **Step 3: Add invalid-input tests.** In `test_file_snippets_reject_invalid_shapes`, create a 25-line source file and use `subTest` plus `assertRaises(ValueError)` for zero/five snippets, `[0, 1]`, `[3, 2]`, `[1, 21]`, range past EOF, blank `title`/`why`, and mixed `snippets` with each of top-level `code`, `lines`, `start_line`, `diff`. Extend `test_files_to_review_stay_inside_the_project` with a valid-looking snippet for `../outside`, `.GIT/config`, `.Env.local`, and a symlink outside; assert no report appears after each rejection.

  ```python
  project_id = COMPANION.store.project_identity(self.project)["id"]
  before_reports = COMPANION.store.list_reports(project_id)
  with self.subTest(case=name), self.assertRaises(ValueError):
      self.publish(page)
  self.assertEqual(COMPANION.store.list_reports(project_id), before_reports)
  ```
- [ ] **Step 4: Run the new rejection tests and see RED.** Run `TMPDIR=/private/tmp python3 -m unittest tests.test_companion.CompanionTest.test_file_snippets_reject_invalid_shapes tests.test_companion.CompanionTest.test_files_to_review_stay_inside_the_project -v`; expect at least one rejected case to publish under the old code.
- [ ] **Step 5: Implement the publisher extension.** Keep the current `validate(page, report_type="result")` and `attach_code(project, files)` signatures. Validate source `snippets` as 1–4 dictionaries with required text and valid 1–20-line ranges; reject the four incompatible top-level fields. Reuse the same resolved-path and UTF-8 checks, read one file once, slice each range, and add all snippet bytes to `MAX_CODE`; preserve the existing legacy branch.
- [ ] **Step 6: Run GREEN and legacy regressions.** Run `TMPDIR=/private/tmp python3 -m unittest tests.test_companion -v`; expect all tests to pass, including existing full-file/range/diff and safety tests.
- [ ] **Step 7: Review this task's uncommitted diff.** Run `git diff --check` and `git diff -- skills/showwork/scripts/companion.py tests/test_companion.py`; confirm no staging or commit.

### Task 2: Render excerpts beneath one file

**Files:** Modify `skills/showwork/assets/report-view.js:91-105,194-207`, `skills/showwork/assets/report-view.css:18-38`; test `tests/browser_companion.cjs:105-145`.

**Interfaces:** Consume Task 1's published `file.snippets: Array<{title, why, code, start_line}>` while retaining `file.path` and file-level `why`. `renderReport(root, page, hooks)` still accepts existing pages. Reuse `codeRows(file)` and `editor(file)` on each snippet with the parent path, so syntax colors, line numbers and copying remain consistent.

- [ ] **Step 1: Write a failing browser case.** Add a handoff file with two source-backed snippets at nonadjacent line numbers. Assert the page has one file accordion, two excerpt cards in order, each title/reason as text, first rendered numbers matching each `start_line`, and two Copy buttons whose clipboard values are the respective snippets. Include `<script>bad()</script>` in one reason and assert no script runs.

  ```js
  assert.equal(await page.locator('#files details.file').count(), 1);
  assert.equal(await page.locator('#file-0 .snippet-card').count(), 2);
  assert.deepEqual(await page.locator('#file-0 .snippet-why').allTextContents(), ['First reason', '<script>bad()</script>']);
  assert.equal(await page.evaluate(() => window.bad), undefined);
  // Grant clipboard-read/write in the test context; compare each Copy result to its own source excerpt.
  ```
- [ ] **Step 2: Run the browser check and see RED.** Run `NODE_PATH=/Users/brianchoi/personal/handeye/node_modules SHOWWORK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/browser_companion.cjs`; expect an exception from `file.code` access or missing excerpt cards.
- [ ] **Step 3: Implement rendering and CSS.** In `renderFiles`, show `N excerpts` in a new-format file summary, lazily append a vertical `snippet-list` of cards on open, and put each card's title/range above `editor({...snippet, path:file.path, language:file.language})` with the reason below. Keep the legacy `editor(file)` path. Add `.snippet-list`, `.snippet-card`, `.snippet-title`, `.snippet-why` rules; ensure code regions alone scroll horizontally and focus remains visible.
- [ ] **Step 4: Add narrow-window and legacy assertions.** At 390px viewport, assert the file/card stays within the viewport while a long code line has a scrollable `.code` region. Keep existing assertions for a one-range file, a diff file, and keyboard open/Copy behavior. Render reason text with DOM `textContent`.

  ```js
  assert.ok(await page.locator('#file-0 .code').first().evaluate(el => el.scrollWidth > el.clientWidth));
  assert.ok(await page.locator('#file-0').evaluate(el => el.getBoundingClientRect().right <= innerWidth));
  ```
- [ ] **Step 5: Run GREEN.** Run the same browser test; expect its final `passed:true` output.
- [ ] **Step 6: Build the frontend.** Run `npm run build` in `app/`; expect TypeScript/Vite success.
- [ ] **Step 7: Review this task's uncommitted diff.** Run `git diff --check` and inspect `git diff -- skills/showwork/assets/report-view.js skills/showwork/assets/report-view.css tests/browser_companion.cjs` without staging.

### Task 3: Authoring guidance, installed app and revised Android report

**Files:** Modify `skills/showwork/SKILL.md`, `skills/showwork/references/companion.md`; no permanent report file. Use the existing `scripts/install_codex.py` and `app/` build commands.

**Interfaces:** Source authors provide `files[].snippets[]` from Task 1; the installed app renders them via Task 2. Existing Android report: `~/Library/Application Support/Showwork/projects/d80ee688e7c77180/reports/20261108-151203-835722-9b77`; its report JSON and assets are evidence, not source instructions.

- [ ] **Step 1: Update result-authoring guidance.** In the two listed docs, replace the default broad `lines` example with a file holding two named 1–20-line `snippets`, each with a concrete `why`. Tell authors to select the source lines that explain behavior, use file-level `why` for the file's role, and keep legacy single-code/diff support documented. Do not change other Showwork command scopes.
- [ ] **Step 2: Check the new authoring example.** Read the changed guidance and confirm it names `title`, `lines`, and per-snippet `why`, without weakening result evidence or changing other command scopes.
- [ ] **Step 3: Update local installations.** After source tests pass, run `python3 scripts/install_codex.py --user --runtime both` and compare installed `showwork` skill and `report-view.js`/`.css` with repository sources. A new Codex/Claude session is needed to load edited skill instructions.
- [ ] **Step 4: Build the native app.** Run `npm run tauri build` in `app/`; expect a successful release app bundle.
- [ ] **Step 5: Install and verify the native app.** Preserve `/Applications/Showwork.app` under the companion temp directory, replace it with `app/src-tauri/target/release/bundle/macos/Showwork.app`, and verify built/installed executable hashes plus embedded new renderer assets. Do not use desktop GUI input automation.
- [ ] **Step 6: Prepare the revised Android report source.** Copy the previous report's 8 sections, 7 checks and 5 images from its `page.json`/`assets` (or the original JSON in the companion temp directory) to a new JSON source under `companion.py path`. Replace its file list with these decisive excerpts, each with a specific reason: `companion.py` 408–413; `android_emulator.py` 103–118 and 147–159; `android_relay.py` 20–33, 132–139, 156–170 and 179–194; `device_relay.py` 45–55, 69–76 and 78–90; `store.rs` 216–217 and 257–263; `deviceSessionView.ts` 29–44, 92–104 and 108–116; `tabs.ts` 91–105 and 112–118. Check current line numbers, retain the native-tab `unverified` check and existing ResourceWarnings, and keep the old report untouched.
- [ ] **Step 7: Publish the revised Android result.** Run `companion.py publish --project /Users/brianchoi/work/personal/showwork-android --file <temp>/android-snippets.json --type result --agent codex`; expect a new report ID and no deletion of the earlier report.
- [ ] **Step 8: Inspect the actual page.** Use the companion browser server or a read-only app screenshot to check that `store.rs` opens as two short excerpts with two reasons, all seven selected files are grouped once each, five images load, and seven checks preserve their statuses. Record the new report ID and any unverified installed-native behavior; do not label a browser screenshot as native-app proof.
- [ ] **Step 9: Final verification and status.** Run `TMPDIR=/private/tmp python3 -m unittest tests.test_companion -v`, the focused browser test, and `git diff --check`; inspect `git status --short` and `git diff` including the plan/spec files. Report changed sources, installed copies, app bundle, new report, tests and limitations. Leave the working tree uncommitted and unstaged.
