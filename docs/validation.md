# Validation record

## 0.5.0 Result walkthrough only on explicit command

On 2026-10-08, 51 Python checks and two npm installation/update checks passed. We checked that older automatic guidance became command-only guidance for Codex and Claude while preserving user-written text. Reinstalling produced the same result. Four tests for the removed per-prompt hook were removed, and a test for updating older instructions was added.

All five skills installed from the actual npm package had Codex `allow_implicit_invocation: false` and Claude `disable-model-invocation: true`. Codex's real `skills/list` response also loaded all five without error. That response does not include the invocation policy, so appearing in the list alone does not prove automatic invocation is blocked at runtime. Claude strict plugin validation passed.

The old skill-creator quick format validator rejected Claude's official `disable-model-invocation` field. We kept that field because Claude requires it for manual invocation. We separately checked actual Codex loading and the packaged settings. We have not yet compared ordinary requests and direct commands in new Codex and Claude conversations. Open a new session after updating because an existing session may retain older instructions.

This change affected command settings and explanation guidance. Browser runtime code was unchanged, and no result report was opened automatically.

## 0.4.3 Temporary files outside the project

On 2026-10-08, 54 Python checks, two npm installation/update checks, and 17 Chromium checks passed. We verified that reports and check records appeared under `/tmp` without creating `.showwork` in the project. The same project resolves to the same temporary path; different projects use different paths. World-readable directories and deceptive linked directories are rejected. Writing new logs to old in-project records is also rejected.

The new path command ran from both Codex and Claude installations made from the actual package. We also checked that no Python cache files were written inside the skill. In the browser, choice saving, automatic updates, captured image display, original-image access, and narrow-screen checks passed. These captures were saved in `/tmp/showwork-visual-test-FGTHSw`. All five skill format checks and Claude plugin validation passed.

Older `.showwork` data in this repository was moved to a temporary directory after stopping the previous server. Data in other projects was not moved or deleted automatically. Windows was not checked. Temporary files may disappear when the OS cleans them.

## 0.4.2 Simple explanations

All five skills and automatic guidance were changed to use familiar words and short sentences in chat and browser reports. Detailed technical material remains expandable; important problems and unchecked points stay visible. Format checks for the five skills and two npm installation/update checks passed. Codex and Claude user installations were also updated. We have not verified that every future conversation reaches the same level of simplicity.

## 0.4.1 Original captures and report-writing responsibilities

On 2026-10-08, 50 Python checks, two npm integration checks, and 17 Chromium checks passed. We opened the original link for a tall image with the Enter key, verified that it decoded at original size in an authenticated new tab, and checked that `opener` was blocked. Image choice cards had no link and still selected on click. A 390px horizontal-overflow check also passed. Skill format checks and Claude strict plugin validation passed.

Shared instructions assign report authoring to Luna/Haiku while the main model remains responsible for app control, capture, judgments, and final inspection. This guidance uses model selection when the runtime supports it; neither the server nor installer forces a model change. Actual Haiku delegation, native mobile execution, and cost savings were not verified.

## 0.4.0 Adverial review command and mobile evidence guidance

On 2026-10-08, 50 Python checks and two npm integration checks passed. We verified the update that adds only the new review skill to an installation of the previous four, plus packaged installation and relative references on both Codex and Claude. Changed-skill format checks and Claude strict plugin validation passed; the local plugin list showed `showwork@inline` 0.4.0 enabled.

The 15 Chromium checks included copying a real browser capture into companion assets, decoding it, and displaying it. At first, temporary Playwright tools were unavailable, so the check could not run. It passed after installing development tools in a temporary path outside the project. No product runtime dependency was added.

An independent agent used the new skill to review a local diff in a separate React Native source example. It found a deletion-condition defect, reproduced four failing cases with the current handler and four passing baseline controls at HEAD, and published a localhost report with source locations, severity, a branch diagram, and runtime gaps. The report's actual browser capture was inspected. The example app source was not changed.

That example lacked a runnable native project, dependencies, and artifacts. Android/iOS commands failed because `react-native` was missing. Without an Android emulator/AVD or iOS Xcode, real mobile launch, interaction, and capture were reported as unverified. Node handler reproduction and a browser report capture are not evidence of native app execution. A complete success path in a real iOS/Android app, all agent response quality, and Windows execution were outside this validation scope.

## 0.3.1 Connected routing diagrams and ERDs

On 2026-10-07, 49 Python checks and two npm integration checks passed. We checked the format of two changed skills and inclusion of SVG examples in the npm package. In real Chromium, we checked routing and ERD SVG rendering, accessible names, expandable supporting tables, no horizontal page overflow at 390px, and keyboard horizontal scrolling. A desktop capture led us to split a long node label across two lines.

The guidance and examples specify per-branch responses, FK-to-PK links, cardinalities, and before/after markings. The examples use fictional APIs and schemas; they do not prove routing in a user app or an executed database migration. Whether the model chooses this form for every task remains unverified.

## 0.3.0 Detailed result explanation and Claude user installation

On 2026-10-07 in Linux, 49 Python tests, two npm integration checks, and 14 real Chromium checks passed. Python checks covered custom Claude configuration paths, preservation of existing `CLAUDE.md` and `settings.json`, update backups and rollback on failure, and preflight checks before installing either tool. npm checks covered installing both tools by default, selecting only Claude, and updating both skills to a new Git commit using the same cache.

In the browser, we checked the existing choice/verification flow, full-width explanations, tables taller than 760px, height changes when details expand, contents navigation, and mobile width and height. Real desktop and mobile captures were saved to the local `.showwork/visual-test/` path at the time. The detailed table was a rendering fixture, not evidence of a migration applied to a real app.

Guidance for changed areas includes routing, schema/migrations, and architecture. It distinguishes source-derived explanations from runtime observations and authored migrations from executed ones. Better guidance and rendering tests alone do not prove the quality of all agent explanations. Windows execution and long-term use across products were not verified.

## 0.2.3 Updates with the same command

On 2026-10-06 in Linux, 46 Python tests and two npm integration checks passed. The installer backs up changed skills before replacement, including user edits and files removed from the distribution. Additional checks covered applying a new version, repeating identical installation, lock and backup path protection, and rollback after failures during preparation, replacement, or instruction writing. Interruptions immediately after moving files and immediately after atomic instruction writing were also reproduced to verify restoration.

The npm check installed a first commit from a temporary Git repository, made a second commit, then used **the same npx command and cache** again. The new commit's skills were installed and removed files disappeared even though the package version string was unchanged. This checked updates without a new package URL or cache deletion. Windows execution and automatic recovery after forced OS shutdown were not verified.

## 0.2.2 User installation by default

On 2026-10-06 in Linux, 43 Python tests and an npm package installation check passed. New checks isolated the user home and covered installation under `~/.agents/skills`, preservation of global instructions, reruns, protection of modified skills, custom `CODEX_HOME` and active overrides, and rejection of malformed instructions or symlinks. Existing project installation was checked with explicit `--target`, which is rejected when combined with `--user`. Windows execution and every project-specific response from a real model were outside this scope.

## 0.2.1 npx installation

On 2026-10-06 in Linux, 40 Python tests and the `npm test` package installation integration check passed. The integration check ran an actual `npm pack` result from npm cache and covered default project installation, a path with spaces from another working directory, reinstallation, preservation of user changes, rejection of invalid arguments, and guidance when Python is missing. The package contained the installer, four skills, and browser companion, with no external npm dependencies. Windows execution was unverified.

## 0.2.0 Conditional visual choices and browser result walkthrough

On 2026-10-06 in Linux, 40 Python tests passed, including existing tests and new companion checks. Thirteen browser-server checks made real HTTP requests for page delivery, choice recording, stale-page rejection, session authentication, file boundaries, and multiple-session cookies. Skill and plugin format checks also passed.

Running `tests/browser_companion.cjs` with Playwright and Chromium checked ten items: actual page rendering, isolation of embedded HTML scripts, keyboard choice, saved choice, automatic result-page update, no approval button on the result page, stale-page choice rejection, no mobile horizontal overflow, authentication after reload, and connection state after server shutdown. Desktop and mobile captures were inspected. At the time, captures and machine-readable results were saved in local `.showwork/visual-test/`.

The browser check is an optional development check, not a plugin runtime dependency. Run it where Playwright and Chromium are available.

```bash
NODE_PATH=/path/to/node_modules node tests/browser_companion.cjs
```

You can point `SHOWWORK_CHROMIUM=/absolute/path/to/chrome` to an existing Chromium. The first attempt lacked the browser revision expected by the installed Playwright, so this environment used an existing Chromium executable for validation.

These checks establish companion behavior. They do not prove that agents always choose correctly whether to ask for a decision, or that a separate user task app was completed. Browser clicks are recorded but do not automatically invoke a waiting agent. Remote port forwarding and Windows browser execution were not checked.

## 0.1.1 Automatic invocation connection

Codex project instructions and a Claude `UserPromptSubmit` hook were added so skills were read on ordinary requests. On 2026-10-06, all 27 tests passed with `python3 -m unittest discover -s tests -v`. Codex bundle manifest and Claude strict manifest checks also passed. The original 0.1.0 checks remain below.

Additional checks covered whether the hook supplied guidance on an ordinary Korean-language request, whether the registered hook ran from an installation path with spaces, whether Codex installation preserved existing instructions and used overrides, and whether it added automatic guidance to a former skills-only installation. These checks verified the connection, not that every real model response obeyed the guidance.

## Initial 0.1.0 record

Validation on 2026-10-06 used Linux and Python 3.12.3. Codex CLI was 0.153.4 and Claude Code was 2.1.290.

## Runtime checks

- `python3 -m unittest discover -s tests -v`: 15 evidence handling checks and one installation check; 16 passed in total.
- `.codex-plugin/plugin.json` passed the official bundle validator from Codex plugin-creator.
- Four shared skills passed skill-creator's `quick_validate.py` format check.
- `claude plugin validate . --strict --json` passed without errors or warnings.
- `claude --plugin-dir <absolute path to showwork> plugin list --json` showed `showwork@inline` version `0.1.0`, `scope=session`, and `enabled=true`.
- After installing Codex skills into a temporary project, reinstalling made no changes and conflicts preserved existing files.

Automated tests covered real subprocess success, failure, and timeout; saved output; command argument preservation; copied attachments; changed or missing files; concurrent recording; and SIGTERM cleanup. Installation tests checked other user files and symlink boundaries.

## Skill behavior review

An independent agent used the skill text and a temporary repository to review how these requests would be handled.

| Request | Observed handling |
| --- | --- |
| Fix a footer typo | Brief investigation, edit, and check |
| Add subscription cancellation without a cancellation policy | Ask only for the policy decision that affects the result |
| Review two commits and local changes | Include both commits, staged and unstaged changes, and relevant untracked files |
| Verify mobile payment without a browser | Mark screen and interaction unverified despite passing tests |
| Implement a feature already agreed to cancel at period end | Proceed without asking for the same approval again |

This was a simulated review of skill behavior, not an evaluation comparing full Claude and Codex sessions in real customer apps.

The review found that concurrent evidence writes could lose data and that child processes could remain after SIGTERM. The recorder was changed to merge the latest record under a lock and clean up process groups, with regression tests for both issues.

## Validation scope

The initial version checked manifests, local loading, installation, and the recorder. Codex native marketplace installation, Windows behavior, and long-term use in real apps were outside that validation. Skills guide model behavior; they do not act as a policy engine that always forces the same execution or block.

Current-version logs and captures are stored under `/tmp`. Paths under `.showwork/` in older entries describe where validation artifacts were kept at that time. Review the contents before sharing results.
