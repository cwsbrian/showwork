# Live sessions in the Showwork app — design

Status: agreed in conversation on 2026-11-06. Part 1 (this spec) covers the tab shell and the
web browser session. iOS simulator and Android emulator sessions are a later spec that plugs into
the same tabs.

## Why

Captures are one of Showwork's most important outputs. Today an agent opens an external browser
or the Simulator app on the user's screen to take them. The user wants that work to happen inside
the Showwork app instead: nothing pops up on their desktop, and they can watch (and step in) from
the app.

## What the user sees

- Every Showwork task already shows as an item in the report list: a spinner while it runs, the
  report once published. Each task owns a set of **tabs** in the right pane.
- Tab 1 is always **Report**. For a task still running it says the report will appear here.
- Each live browser the agent opens for that task adds a **session tab** (one tab per browser).
  Several can run at once.
- A session tab shows the browser's screen live. The user can click, scroll and type in it to
  take over.
- With two or more sessions a **Split** tab shows every session at once as small previews. A
  preview is the real screen scaled down (the browser keeps its own size, e.g. 1280×800); it is
  not a narrower, re-laid-out page. Previews cannot be operated; clicking one opens its tab.
- When a task ends (published or stopped) its browsers close. Their tabs stay, marked ended,
  until the user closes them.
- Tabs follow the selected task. Selecting another task (or project) shows that task's tabs.
  The project switcher's spinner already says which projects have work running.

## Decisions

- No external windows: the browser is the system Chrome in headless mode, started by the
  companion, with a private temporary profile.
- The agent drives it with Playwright over CDP (`connectOverCDP`) and takes screenshots there.
- The app mirrors it with CDP `Page.startScreencast` straight from the webview and forwards the
  user's input with `Input.dispatch*Event`.
- The app never starts or stops browsers; the companion does. The app only reads the store.
- A task is identified by a unique run id (one per `companion.py start`). A published report
  records the run id so its tabs survive publishing.

## Non-goals (this part)

Simulators/emulators, browser chrome (back/forward/address bar editing), recording video,
multiple pages inside one session, sessions that outlive their task.
