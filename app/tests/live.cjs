const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require('playwright');

const app = path.resolve(__dirname, '..');
const companion = path.resolve(app, '../skills/showwork/scripts/companion.py');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'showwork-live-test-'));
const repo = path.join(tmp, 'repo');
const store = path.join(tmp, 'store');
fs.mkdirSync(repo);
spawnSync('git', ['init', '-q', repo], {stdio: 'ignore'});
const env = {...process.env, SHOWWORK_STORE: store, SHOWWORK_NO_APP: '1', SHOWWORK_BROWSER_ORIGINS: 'http://localhost:5179'};
const cli = (...args) => {
  const r = spawnSync('python3', [companion, ...args], {env, encoding: 'utf8', timeout: 30000});
  if (r.status !== 0) throw Error(r.stderr || r.stdout || `companion exited ${r.status}`);
  return JSON.parse(r.stdout);
};
const vite = spawn(path.join(app, 'node_modules/.bin/vite'), ['--port', '5179', '--strictPort'], {cwd: app, stdio: 'ignore'});
let browser;
const sessionIds = [];
let projectId;

async function waitFor(fn, ms = 15000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { const result = await fn(); if (result) return result; } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw Error('Timed out waiting for live browser');
}

(async () => {
  const run = cli('start', '--project', repo, '--type', 'result').run;
  const html = '<button style="position:absolute;left:40px;top:40px;width:100px;height:50px" onclick="document.title=\'clicked\'">Click me</button>';
  const opened = cli('browser', 'open', '--project', repo, '--url', `data:text/html,${encodeURIComponent(html)}`, '--title', 'Live page', '--width', '800', '--height', '600');
  sessionIds.push(opened.session);
  const files = fs.readdirSync(path.join(store, 'projects'));
  projectId = files[0];
  const raw = JSON.parse(fs.readFileSync(path.join(store, 'projects', projectId, 'sessions', `${opened.session}.json`), 'utf8'));
  const session = {id: raw.id, projectId: 'a', run, kind: 'browser', title: raw.title, url: raw.url, width: raw.width, height: raw.height, port: raw.port, ws: raw.ws, pid: raw.pid, startedAt: raw.started_at, endedAt: null, alive: true};
  await waitFor(async () => (await fetch('http://localhost:5179/')).ok);
  browser = await chromium.launch({headless: true, executablePath: process.env.SHOWWORK_CHROMIUM});
  const page = await browser.newPage({viewport: {width: 1280, height: 800}});
  await page.addInitScript(({runId, session}) => { window.__SHOWWORK_FIXTURE__ = {projects: [{id:'a',name:'alpha',displayName:'alpha',remote:null,lastActivity:null}],reports:{a:[]},pages:{},sessions:[session],running:{a:[{id:runId,projectId:'a',type:'result',title:null,branch:null,worktree:'/w',agent:'claude',startedAt:new Date().toISOString()}]}}; }, {runId: run, session});
  await page.goto('http://localhost:5179/');
  await page.locator(`.item.running[data-run-id="${run}"]`).click();
  await page.locator('.tab', {hasText:'Live page'}).click();
  await page.waitForFunction(() => document.querySelector('.session-frame')?.src.startsWith('data:image/jpeg'), undefined, {timeout: 15000});
  if (process.env.SHOWWORK_LIVE_SHOT) await page.screenshot({path: process.env.SHOWWORK_LIVE_SHOT});
  const pane = await page.locator('.session-body').boundingBox();
  const screen = await page.locator('.session-screen').boundingBox();
  assert.equal(screen.x, pane.x);
  assert.equal(screen.width, pane.width);
  const dimensions = await page.locator('.session-size').textContent();
  const m = dimensions.match(/(\d+)\s*×\s*(\d+)/);
  assert.ok(m, dimensions);
  const w = Number(m[1]), h = Number(m[2]);
  const box = await page.locator('.session-frame').boundingBox();
  const scale = Math.min(box.width / w, box.height / h);
  const x = box.x + (box.width - w * scale) / 2 + 80 * scale;
  const y = box.y + (box.height - h * scale) / 2 + 65 * scale;
  await page.mouse.click(x, y);
  await waitFor(async () => {
    const pages = await (await fetch(`http://127.0.0.1:${raw.port}/json/list`)).json();
    return pages.some((p) => p.title === 'clicked');
  });
  const nextUrl = `data:text/html,${encodeURIComponent('<title>navigated</title><h1>Navigated</h1>')}`;
  await page.locator('.session-address').fill(nextUrl);
  await page.locator('.session-address').press('Enter');
  await waitFor(async () => {
    const pages = await (await fetch(`http://127.0.0.1:${raw.port}/json/list`)).json();
    return pages.some((p) => p.title === 'navigated');
  });
  assert.equal(await page.locator('.session-address').inputValue(), 'text/html · inline page');
  await page.locator('.session-address').focus();
  assert.equal(await page.locator('.session-address').inputValue(), nextUrl);
  assert.equal(await page.evaluate(() => window.__showworkLiveCount), 1);
  const second = cli('browser', 'open', '--project', repo, '--url', 'about:blank', '--title', 'Second page', '--width', '800', '--height', '600');
  sessionIds.push(second.session);
  const raw2 = JSON.parse(fs.readFileSync(path.join(store, 'projects', projectId, 'sessions', `${second.session}.json`), 'utf8'));
  await page.evaluate((s) => window.__showworkMock.addSession(s), {id:raw2.id,projectId:'a',run,kind:'browser',title:raw2.title,url:raw2.url,width:raw2.width,height:raw2.height,port:raw2.port,ws:raw2.ws,pid:raw2.pid,startedAt:raw2.started_at,endedAt:null,alive:true});
  await page.locator('.tab', {hasText:'Split'}).click();
  await page.waitForFunction(() => document.querySelectorAll('.split-tile .session-frame[src^="data:image/jpeg"]').length === 2, undefined, {timeout:15000});
  assert.equal(await page.evaluate(() => window.__showworkLiveCount), 2);
  await page.evaluate((id) => window.__showworkMock.endSession(id), session.id);
  await page.locator('.tab', {hasText:'Live page · ended'}).click();
  await page.locator('.session-frame[src^="data:image/jpeg"]').waitFor();
  assert.equal(await page.locator('.session-frame').evaluate((img) => img.style.opacity), '0.55');
  await page.locator('.tab', {hasText:'Report'}).click();
  await page.waitForFunction(() => window.__showworkLiveCount === 0);
  await page.locator('.tab', {hasText:'Live page · ended'}).click();
  assert.ok((await page.locator('.session-frame').getAttribute('src')).startsWith('data:image/jpeg'));
  assert.equal(await page.locator('.session-frame').isVisible(), true);
  await page.evaluate(() => window.__showworkMock.arrive('a', {id:'done',projectId:'a',type:'result',mode:'handoff',title:'Done',branch:null,commit:null,worktree:'/w',agent:'claude',createdAt:new Date().toISOString(),version:'v',run:null,open:false,chosen:false}, {mode:'handoff',title:'Done',summary:'Done',sections:[],checks:[]}));
  await page.locator('.item[data-report-id="done"]').click();
  await page.waitForFunction(() => window.__showworkLiveCount === 0);
  console.log('live ok');
})().catch((e) => { console.error(e); process.exitCode = 1; }).finally(async () => {
  if (browser) await Promise.race([browser.close(), new Promise((r) => setTimeout(r, 3000))]);
  for (const sessionId of sessionIds) { try { cli('browser', 'close', '--project', repo, '--session', sessionId); } catch (e) { console.error(e); process.exitCode = 1; } }
  vite.kill('SIGTERM');
  fs.rmSync(tmp, {recursive: true, force: true});
  process.exit(process.exitCode || 0);
});
