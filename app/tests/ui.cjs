// UI check with the mock API only: SHOWWORK_CHROMIUM=... NODE_PATH=/path/to/node_modules node tests/ui.cjs
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require('playwright');

const appDir = path.resolve(__dirname, '..');
const PORT = 5179;
const URL_BASE = `http://localhost:${PORT}/`;
const vite = spawn('npx', ['vite', '--port', String(PORT), '--strictPort'], {cwd: appDir, stdio: ['ignore', 'pipe', 'pipe']});
let viteLog = ''; vite.stdout.on('data', c => viteLog += c); vite.stderr.on('data', c => viteLog += c);
let browser;
const stop = () => { try { vite.kill('SIGTERM'); } catch {} };
process.on('exit', stop);

const meta = (id, type, branch, createdAt, extra = {}) => ({id, projectId: 'a', type, mode: 'handoff', title: id + ' title', branch, commit: 'abcdef1234', worktree: '/w', agent: 'claude', createdAt, version: 'v-' + id, open: false, chosen: false, ...extra});
const handoff = (title, withFiles) => ({mode: 'handoff', title, summary: 'Summary of ' + title, sections: [{kind: 'explanation', title: 'Section', body: 'Body'}], files: withFiles ? [{path: 'src/a.ts', why: 'Core change', language: 'ts', code: 'const a = 1;\n'}] : [], checks: []});
const decisionPage = {mode: 'decision', title: 'Pick a layout', summary: 'Choose one', question: 'Which layout?', options: [{id: 'x', title: 'Option X', body: 'X body'}, {id: 'y', title: 'Option Y', body: 'Y body'}]};
const fixture = {
  projects: [
    {id: 'a', name: 'alpha', displayName: 'alpha', remote: null, lastActivity: '2026-01-06T00:00:00Z'},
    {id: 'b', name: 'beta', displayName: 'beta', remote: null, lastActivity: '2026-01-01T00:00:00Z'},
  ],
  reports: {
    a: [
      meta('a-plan1', 'plan', 'feat', '2026-01-01T00:00:00Z'),
      meta('b-review1', 'review', 'feat', '2026-01-02T00:00:00Z'),
      meta('c-result1', 'result', 'feat', '2026-01-03T00:00:00Z'),
      meta('d-plan2', 'plan', 'main', '2026-01-04T00:00:00Z'),
      meta('e-decide1', 'plan', 'main', '2026-01-05T00:00:00Z', {mode: 'decision', open: true}),
    ],
    b: [
      meta('closed1', 'plan', null, '2025-12-31T00:00:00Z', {projectId: 'b', mode: 'decision', open: false}),
      meta('other1', 'result', null, '2026-01-01T00:00:00Z', {projectId: 'b'}),
    ],
  },
  pages: {'a-plan1': handoff('Plan one', false), 'b-review1': handoff('Review one', false), 'c-result1': handoff('Result one', true), 'd-plan2': handoff('Plan two', false), 'e-decide1': decisionPage, closed1: {...decisionPage, title: 'Old layout question'}, other1: handoff('Other one', false)},
  unread: ['d-plan2', 'e-decide1', 'other1'],
};

async function waitServer() {
  const end = Date.now() + 30000;
  while (Date.now() < end) {
    try { if ((await fetch(URL_BASE)).ok) return; } catch {}
    await new Promise(r => setTimeout(r, 200));
  }
  throw Error('vite did not start\n' + viteLog);
}

(async () => {
  await waitServer();
  browser = await chromium.launch({headless: true, executablePath: process.env.SHOWWORK_CHROMIUM});
  const context = await browser.newContext({viewport: {width: 1280, height: 800}});
  await context.addInitScript(f => { window.__SHOWWORK_FIXTURE__ = f; }, fixture);
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => m.type() === 'error' && !m.text().includes('ws://127.0.0.1:1/x') && errors.push(m.text()));
  const requested = []; page.on('request', r => requested.push(r.url()));
  await page.goto(URL_BASE);

  const badge = id => page.locator(`.project[data-project-id="${id}"] .badge`);
  const item = id => page.locator(`.item[data-report-id="${id}"]`);
  const trigger = page.locator('.switcher-trigger');
  const openSwitcher = async () => { if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click(); await page.locator('.switcher-pop').waitFor(); };
  await page.locator('.switcher-name', {hasText: 'alpha'}).waitFor();
  // the closed switcher shows the current project and counts unread reports elsewhere
  assert.equal(await page.locator('.switcher-pop').count(), 0);
  assert.equal(await page.locator('.others-unread').textContent(), '1');
  await openSwitcher();
  assert.equal(await badge('a').textContent(), '2');
  assert.equal(await badge('b').textContent(), '1');
  assert.equal(await page.locator('.project[aria-current="true"]').getAttribute('data-project-id'), 'a');
  // Escape closes the list and returns focus to the switcher
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.switcher-pop').count(), 0);
  assert.ok(await trigger.evaluate(el => el === document.activeElement));
  // clicking outside closes it too
  await openSwitcher();
  await page.locator('#report').click();
  assert.equal(await page.locator('.switcher-pop').count(), 0);

  // unread reports carry a dot and a bold title; read ones do not
  const unreadIds = await page.locator('.item.unread').evaluateAll(els => els.map(e => e.dataset.reportId));
  assert.deepEqual(unreadIds, ['e-decide1', 'd-plan2']);
  assert.equal(await page.locator('.item .unread-dot').count(), 2);
  await item('d-plan2').click();
  await page.waitForFunction(() => !document.querySelector('.item[data-report-id="d-plan2"]').classList.contains('unread'));
  assert.equal(await item('d-plan2').locator('.unread-dot').count(), 0);
  await openSwitcher();
  await page.waitForFunction(() => document.querySelector('.project[data-project-id="a"] .badge')?.textContent === '1');
  await page.keyboard.press('Escape');

  // select a report: title and files accordion
  await item('c-result1').click();
  await page.getByRole('heading', {name: 'Result one'}).waitFor();
  assert.ok(await page.getByRole('heading', {name: 'Files worth reviewing'}).isVisible());
  assert.equal(await page.locator('#report details.file').count(), 1);
  assert.equal(await item('c-result1').getAttribute('aria-current'), 'true');

  // list -> flow keeps selection
  await page.getByRole('button', {name: 'Flow'}).click();
  await page.locator('.view-flow').waitFor();
  assert.equal(await item('c-result1').getAttribute('aria-current'), 'true');
  const heads = await page.locator('.flow-branch h3').allTextContents();
  assert.deepEqual(heads, ['main', 'feat']);
  const feat = await page.locator('.flow-branch').nth(1).locator('.item').evaluateAll(els => els.map(e => e.dataset.reportId));
  assert.deepEqual(feat, ['a-plan1', 'b-review1', 'c-result1']);
  await page.getByRole('button', {name: 'List'}).click();
  assert.equal(await item('c-result1').getAttribute('aria-current'), 'true');

  // view persists across reload
  await page.getByRole('button', {name: 'Flow'}).click();
  await page.reload(); await page.locator('.view-flow').waitFor();
  await page.getByRole('button', {name: 'List'}).click(); await page.locator('.view-list').waitFor();
  await item('c-result1').click(); await page.getByRole('heading', {name: 'Result one'}).waitFor();

  // arrival raises badge but does not touch the right pane
  const before = await page.locator('#report h1').textContent();
  await page.evaluate(() => window.__showworkMock.arrive('b', {id: 'new1', projectId: 'b', type: 'review', mode: 'handoff', title: 'new1 title', branch: 'x', commit: null, worktree: '/w', agent: 'claude', createdAt: '2026-02-01T00:00:00Z', version: 'v', open: false, chosen: false}, {mode: 'handoff', title: 'Brand new', summary: 's', sections: [], files: [], checks: []}));
  await page.waitForFunction(() => document.querySelector('.others-unread')?.textContent === '2');
  assert.equal(await page.locator('#report h1').textContent(), before);
  assert.equal(await item('c-result1').getAttribute('aria-current'), 'true');

  // a started report shows as a working item with a spinner until it is published
  await page.evaluate(() => window.__showworkMock.start({id: 'run1', projectId: 'a', type: 'review', title: null, branch: 'feat', worktree: '/w', agent: 'claude', startedAt: '2026-02-02T10:05:00Z'}));
  const working = page.locator('.item.running[data-run-id="run1"]');
  await working.waitFor();
  assert.equal(await working.locator('.item-title').textContent(), 'Working on the review…');
  assert.ok((await working.locator('.item-sub').textContent()).startsWith('In progress · started '));
  assert.equal(await working.locator('.spinner').count(), 1);
  assert.equal(await page.locator('.middle-body > .working-list:first-child').count(), 1); // above the reports
  await openSwitcher();
  assert.equal(await page.locator('.project[data-project-id="a"] .spinner').count(), 1);
  await page.keyboard.press('Escape');
  await working.click();
  assert.equal(await working.getAttribute('aria-current'), 'true');
  await page.getByText('Working on it. The report appears here when it is ready.').waitFor();
  assert.deepEqual(await page.locator('.tab').allTextContents(), ['Report']);
  const session = (id, title) => ({id, projectId: 'a', run: 'run1', kind: 'browser', title, url: 'http://localhost:3000/', width: 1280, height: 800, port: 1, ws: 'ws://127.0.0.1:1/x', pid: 1, startedAt: `2026-02-02T10:05:0${id.slice(-1)}Z`, endedAt: null, alive: true});
  await page.evaluate(s => window.__showworkMock.addSession(s), session('s1', 'Login page'));
  await page.locator('.tab', {hasText: 'Login page'}).waitFor();
  assert.equal(await page.locator('.tab', {hasText: 'Split'}).count(), 0);
  await page.evaluate(s => window.__showworkMock.addSession(s), session('s2', null));
  await page.locator('.tab', {hasText: 'Split'}).click();
  assert.equal(await page.locator('.split-tile').count(), 2);
  assert.equal(await page.locator('.split-tile').nth(1).locator('.split-label').textContent(), 'localhost:3000');
  await page.locator('.split-tile').first().click();
  assert.equal(await page.locator('.tab[aria-selected="true"] span').first().textContent(), 'Login page');
  await page.evaluate(() => window.__showworkMock.endSession('s1'));
  await page.locator('.tab', {hasText: 'Login page · ended'}).waitFor();
  await page.getByRole('button', {name: 'Close Login page'}).click();
  await page.waitForFunction(() => ![...document.querySelectorAll('.tab')].some(t => t.textContent.includes('Login page')));
  await page.evaluate(() => window.__showworkMock.endSession('s2'));
  await page.evaluate(() => window.__showworkMock.finish('a', 'run1'));
  await page.waitForFunction(() => !document.querySelector('.item.running'));
  await page.locator('.tab', {hasText: 'localhost:3000 · ended'}).waitFor();
  await page.locator('.tab', {hasText: 'Report'}).click();
  await page.getByText('This task ended without a report.').waitFor();
  await page.locator('.item.stopped[data-run-id="run1"]').waitFor();
  await item('c-result1').click();
  await page.locator('.item.stopped[data-run-id="run1"]').click();
  await page.locator('.tab', {hasText: 'localhost:3000 · ended'}).waitFor();
  await page.locator('.tab', {hasText: 'Report'}).click();
  await page.getByRole('button', {name: 'Close localhost:3000'}).click();
  await page.waitForFunction(() => !document.querySelector('.item.stopped'));
  // right-click removes a leftover working item
  await page.evaluate(() => window.__showworkMock.start({id: 'run2', projectId: 'a', type: 'plan', title: 'Login plan', branch: null, worktree: '/w', agent: 'codex', startedAt: 'x'}));
  await page.locator('.item.running[data-run-id="run2"]').waitFor();
  assert.equal(await page.locator('.item.running .item-sub').textContent(), 'In progress · codex');
  await page.locator('.item.running').click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Remove from list'}).click();
  await page.waitForFunction(() => !document.querySelector('.item.running'));

  // filters live in a popover behind the funnel button
  const filterBtn = page.locator('.filter-btn');
  const openFilters = async () => { if (await filterBtn.getAttribute('aria-expanded') !== 'true') await filterBtn.click(); await page.locator('.filter-pop').waitFor(); };
  assert.equal(await page.locator('.toolbar select').count(), 0, 'filters are hidden until the button is pressed');
  await openFilters();
  assert.ok(await page.getByLabel('Branch').evaluate(el => el === document.activeElement), 'focus moves into the popover');
  await page.getByLabel('Branch').selectOption('feat');
  assert.equal(await page.locator('.item').count(), 3);
  assert.ok(await page.locator('.filter-pop').isVisible(), 'the popover stays open while choosing');
  await page.getByLabel('Type').selectOption('review');
  assert.equal(await page.locator('.item').count(), 1);
  assert.equal(await page.locator('.filter-count').textContent(), '2');
  assert.equal(await filterBtn.getAttribute('aria-label'), 'Filters (2 on)');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.filter-pop').count(), 0);
  assert.equal(await page.locator('.item').count(), 1, 'closing keeps the filters on');
  await openFilters();
  await page.getByRole('button', {name: 'Clear filters'}).click();
  assert.equal(await page.locator('.item').count(), 5);
  assert.equal(await page.locator('.filter-count').count(), 0);
  await page.locator('#report').click(); // clicking outside closes it
  assert.equal(await page.locator('.filter-pop').count(), 0);

  // decision: tag, submit, saved state
  await item('e-decide1').click();
  await page.getByRole('heading', {name: 'Pick a layout'}).waitFor();
  assert.ok(await page.locator('.pane-head .needs-choice').isVisible());
  assert.equal(await page.locator('.pane-head .needs-choice').textContent(), 'Needs your choice');
  await page.getByRole('radio', {name: 'Option Y'}).click();
  // a rejected submit (Tauri rejects with a plain string) shows its message
  await page.evaluate(() => { window.__showworkMock.failNext = 'This decision is closed'; });
  await page.getByRole('button', {name: 'Choose this option'}).click();
  await page.getByText('This decision is closed').waitFor();
  await page.getByRole('button', {name: 'Choose this option'}).click();
  await page.getByText('Choice saved. You can continue in chat.').waitFor();
  const calls = await page.evaluate(() => window.__showworkMock.calls);
  assert.deepEqual(calls.at(-1), {fn: 'submitChoice', projectId: 'a', reportId: 'e-decide1', version: 'v-e-decide1', choice: 'y'});
  assert.equal(await page.locator('.pane-head .needs-choice').count(), 0);
  // the list item drops its tag too
  await page.waitForFunction(() => !document.querySelector('.item[data-report-id="e-decide1"] .needs-choice'));

  // external open is the only thing that moves selection
  await page.evaluate(() => window.__showworkMock.open('b', 'other1'));
  await page.getByRole('heading', {name: 'Other one'}).waitFor();
  assert.equal(await page.locator('.switcher-name').textContent(), 'beta');

  // a closed decision shows its options but cannot be chosen
  await item('closed1').click();
  await page.getByRole('heading', {name: 'Old layout question'}).waitFor();
  assert.equal(await page.locator('.pane-head .needs-choice').count(), 0);
  assert.equal(await page.getByRole('radio', {name: 'Option Y'}).getAttribute('aria-disabled'), 'true');
  assert.equal(await page.locator('#pane0-selection-status').textContent(), 'This question is closed. A newer report replaced it.');
  await page.getByRole('radio', {name: 'Option Y'}).click({force: true});
  assert.equal(await page.getByRole('radio', {name: 'Option Y'}).getAttribute('aria-checked'), 'false');
  assert.ok(await page.getByRole('button', {name: 'Choose this option'}).isDisabled());

  // deleting a report or a project's history needs a second click
  await item('other1').click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete report'}).click();
  assert.equal(await item('other1').count(), 1);
  await page.getByRole('menuitem', {name: 'Click again to delete report'}).click();
  await page.waitForFunction(() => !document.querySelector('.item[data-report-id="other1"]'));

  // a failed delete keeps the item and says why in the error line
  await page.evaluate(() => { window.__showworkMock.fail.deleteReport = 'Permission denied'; });
  await item('new1').click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete report'}).click();
  await page.getByRole('menuitem', {name: 'Click again to delete report'}).click();
  await page.locator('#error-line', {hasText: 'Could not delete the report: Permission denied'}).waitFor();
  assert.equal(await item('new1').count(), 1);
  await page.locator('#error-line').click();
  assert.ok(await page.locator('#error-line').isHidden());

  // deleting the last report of the filtered branch resets the filter instead of showing an empty list
  await openFilters();
  await page.getByLabel('Branch').selectOption('x');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.item').count(), 1);
  await item('new1').click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete report'}).click();
  await page.getByRole('menuitem', {name: 'Click again to delete report'}).click();
  await page.waitForFunction(() => !document.querySelector('.item[data-report-id="new1"]'));
  await openFilters();
  assert.equal(await page.getByLabel('Branch').inputValue(), '');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.item').count(), 1);
  const projectB = page.locator('.project[data-project-id="b"]');
  await openSwitcher();
  await projectB.click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete history'}).click();
  assert.equal(await projectB.count(), 1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.ctx-menu').count(), 0);
  await projectB.click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete history'}).click();
  await page.getByRole('menuitem', {name: 'Click again to delete history'}).click();
  await page.waitForFunction(() => !document.querySelector('.project[data-project-id="b"]'));
  assert.equal(await page.locator('.switcher-name').textContent(), 'Select a project');
  // picking a project from the list switches to it and closes the list
  await page.locator('.project[data-project-id="a"]').click();
  assert.equal(await page.locator('.switcher-pop').count(), 0);
  await page.locator('.switcher-name', {hasText: 'alpha'}).waitFor();
  await item('c-result1').waitFor();

  await page.screenshot({path: process.env.SHOWWORK_UI_SHOT || path.join(require('node:os').tmpdir(), 'showwork-ui.png')});

  // mobile width: no horizontal overflow
  await page.setViewportSize({width: 390, height: 800});
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 0, 'horizontal overflow ' + overflow);

  // an open-report event that arrives during startup wins over the default (first) project
  const launch = await browser.newContext({viewport: {width: 1280, height: 800}});
  await launch.addInitScript(f => { window.__SHOWWORK_FIXTURE__ = f; window.__SHOWWORK_OPEN__ = {projectId: 'b', reportId: 'other1'}; }, fixture);
  const launched = await launch.newPage();
  launched.on('pageerror', e => errors.push(e.message));
  await launched.goto(URL_BASE);
  await launched.getByRole('heading', {name: 'Other one'}).waitFor();
  assert.equal(await launched.locator('.switcher-name').textContent(), 'beta');
  assert.equal(await launched.locator('.item[data-report-id="other1"]').getAttribute('aria-current'), 'true');
  await launch.close();

  assert.deepEqual(errors, []);
  const outside = requested.filter(u => !/^(http:\/\/localhost[:/]|data:|blob:|about:)/.test(u));
  assert.deepEqual(outside, []);
  console.log('ui ok');
})().then(async () => { await browser?.close(); stop(); }).catch(async e => { console.error(e); await browser?.close(); stop(); process.exit(1); });
