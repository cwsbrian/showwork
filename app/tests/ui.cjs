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
  const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => m.type() === 'error' && errors.push(m.text()));
  const requested = []; page.on('request', r => requested.push(r.url()));
  await page.goto(URL_BASE);

  const badge = id => page.locator(`.project[data-project-id="${id}"] .badge`);
  const item = id => page.locator(`.item[data-report-id="${id}"]`);
  await badge('a').waitFor();
  assert.equal(await badge('a').textContent(), '2');
  assert.equal(await badge('b').textContent(), '1');
  assert.equal(await page.locator('#projects h2').textContent(), 'Projects');

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
  await page.waitForFunction(() => document.querySelector('.project[data-project-id="b"] .badge')?.textContent === '2');
  assert.equal(await page.locator('#report h1').textContent(), before);
  assert.equal(await item('c-result1').getAttribute('aria-current'), 'true');

  // filters
  await page.getByLabel('Branch').selectOption('feat');
  assert.equal(await page.locator('.item').count(), 3);
  await page.getByLabel('Type').selectOption('review');
  assert.equal(await page.locator('.item').count(), 1);
  await page.getByLabel('Branch').selectOption('');
  await page.getByLabel('Type').selectOption('');
  assert.equal(await page.locator('.item').count(), 5);

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
  assert.equal(await page.locator('.project[data-project-id="b"]').getAttribute('aria-current'), 'true');

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
  await page.getByLabel('Branch').selectOption('x');
  assert.equal(await page.locator('.item').count(), 1);
  await item('new1').click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete report'}).click();
  await page.getByRole('menuitem', {name: 'Click again to delete report'}).click();
  await page.waitForFunction(() => !document.querySelector('.item[data-report-id="new1"]'));
  assert.equal(await page.getByLabel('Branch').inputValue(), '');
  assert.equal(await page.locator('.item').count(), 1);
  const projectB = page.locator('.project[data-project-id="b"]');
  await projectB.click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete history'}).click();
  assert.equal(await projectB.count(), 1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.ctx-menu').count(), 0);
  await projectB.click({button: 'right'});
  await page.getByRole('menuitem', {name: 'Delete history'}).click();
  await page.getByRole('menuitem', {name: 'Click again to delete history'}).click();
  await page.waitForFunction(() => !document.querySelector('.project[data-project-id="b"]'));

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
  assert.equal(await launched.locator('.project[data-project-id="b"]').getAttribute('aria-current'), 'true');
  assert.equal(await launched.locator('.item[data-report-id="other1"]').getAttribute('aria-current'), 'true');
  await launch.close();

  assert.deepEqual(errors, []);
  const outside = requested.filter(u => !/^(http:\/\/localhost[:/]|data:|blob:|about:)/.test(u));
  assert.deepEqual(outside, []);
  console.log('ui ok');
})().then(async () => { await browser?.close(); stop(); }).catch(async e => { console.error(e); await browser?.close(); stop(); process.exit(1); });
