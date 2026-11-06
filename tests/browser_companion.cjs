// Optional real-browser check: NODE_PATH=/path/to/node_modules node tests/browser_companion.cjs
// Requires Playwright + Chromium in the test environment, not in the plugin runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn, spawnSync} = require('node:child_process');
const {chromium} = require('playwright');

const root = path.resolve(__dirname, '..');
const script = path.join(root, 'skills/showwork/scripts/companion.py');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'showwork-browser-'));
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'showwork-visual-test-'));
const python = process.env.PYTHON || 'python3';
const storeDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'showwork-store-'));
const testEnv = {...process.env, SHOWWORK_STORE: storeDirectory, SHOWWORK_NO_APP: '1'};
const server = spawn(python, [script, 'serve', '--project', temporary], {env: testEnv});
let browser, runtimeDirectory;
function publish(document) {
  const source = path.join(temporary, 'source.json'); fs.writeFileSync(source, JSON.stringify(document));
  const result = spawnSync(python, [script, 'publish', '--project', temporary, '--file', source], {encoding:'utf8',env:testEnv});
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout).published;
}
async function waitFor(check) { const end=Date.now()+5000; while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,50));}throw Error('Timed out'); }

(async()=>{
  const info = await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.includes('\n'))resolve(JSON.parse(buffer.split('\n')[0]));});server.once('error',reject);server.once('exit',code=>reject(Error('Server exited '+code)));setTimeout(()=>reject(Error('Server did not start')),5000).unref();});
  runtimeDirectory=info.directory;
  assert.equal(fs.existsSync(path.join(temporary,'.showwork')),false);
  const decision={mode:'decision',title:'Which task layout works better for you?',summary:'This tests the choice feature. It does not request approval for a real product.',question:'Compare only how tasks are displayed.',options:[
    {id:'list',title:'Compact list',body:'Scan tasks quickly, one per line.',html:'<div style="background:#eef4f1;padding:24px;border-radius:12px"><h2>Tasks for today</h2><p>☐ Buy groceries</p><p>☑ Exercise</p><p style="color:#647">+ Add task</p></div>'},
    {id:'board',title:'Status board',body:'View pending and completed tasks separately.',html:'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><section style="background:#eef4f1;border-radius:12px;padding:18px"><h3>To do</h3><p>Buy groceries</p></section><section style="background:#e9eff8;border-radius:12px;padding:18px"><h3>Done</h3><p>Exercise</p></section></div><script>parent.__unsafe=true</script>'}
  ]};
  const oldVersion=publish(decision);
  browser=await chromium.launch({headless:true,executablePath:process.env.SHOWWORK_CHROMIUM});
  const page=await browser.newPage({viewport:{width:1280,height:960}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const requested=[];page.on('request',request=>requested.push(request.url()));
  await page.goto(info.url);await page.getByRole('heading',{name:decision.title}).waitFor();
  assert.equal(await page.evaluate(()=>window.__unsafe),undefined,'Embedded scripts must not execute');
  await page.screenshot({path:path.join(output,'decision.png'),fullPage:true});
  await page.getByRole('radio',{name:'Compact list'}).focus();await page.keyboard.press('ArrowRight');
  assert.equal(await page.getByRole('radio',{name:'Status board'}).getAttribute('aria-checked'),'true');
  await page.getByRole('button',{name:'Choose this option'}).click();
  await page.getByText('Choice saved. You can continue in chat.').waitFor();
  // A failed poll and then a successful one must keep the saved state, so the same choice is not sent again.
  let posts=0;page.on('request',request=>{if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/choice')posts++;});
  await page.route('**/api/view',route=>route.abort());
  await page.getByText('Disconnected · Last page').waitFor();
  await page.unroute('**/api/view');
  await page.getByText('● Connected').waitFor();
  assert.equal(await page.locator('#selection-status').textContent(),'Choice saved. You can continue in chat.','Saved state survives a reconnect');
  assert.ok(await page.getByRole('button',{name:'Choose this option'}).isDisabled(),'No second submit after a reconnect');
  await page.evaluate(()=>document.getElementById('submit').click());await new Promise(r=>setTimeout(r,200));
  assert.equal(posts,0,'The saved choice is not posted twice');
  const events=JSON.parse(spawnSync(python,[script,'events','--project',temporary],{encoding:'utf8',env:testEnv}).stdout);
  assert.equal(events.events.filter(event=>event.choice).length,1,'One choice event');
  assert.equal(events.events.at(-1).choice,'board');
  const imageDecision={...decision,title:'Image choice check',options:decision.options.map(({html,...item})=>({...item,image:path.join(output,'decision.png')}))};
  publish(imageDecision);await page.getByRole('heading',{name:imageDecision.title}).waitFor();
  assert.equal(await page.locator('#options a').count(),0,'Images must not hijack decision selection');
  await page.getByRole('radio',{name:'Compact list'}).click();
  assert.equal(await page.getByRole('radio',{name:'Compact list'}).getAttribute('aria-checked'),'true');
  // A choice answered after a newer page replaced the view must not touch the new page.
  let answered;const late=new Promise(resolve=>answered=resolve);
  await page.route('**/api/choice',async route=>{const response=await route.fetch();await new Promise(r=>setTimeout(r,800));await route.fulfill({response});answered();});
  await page.getByRole('button',{name:'Choose this option'}).click();
  const followUp={...decision,title:'Follow-up question'};publish(followUp);
  await page.getByRole('heading',{name:followUp.title}).waitFor();await late;await new Promise(r=>setTimeout(r,200));
  assert.equal(await page.locator('#selection-status').textContent(),'Choose an option, then press the button.','Late answer ignored');
  assert.ok(await page.getByRole('button',{name:'Choose this option'}).isDisabled(),'Nothing selected on the new page');
  await page.unroute('**/api/choice');
  // While a choice is saving the status says so; picking another option meanwhile still saves only the first, says which, and lets the user send the second.
  let release;const held=new Promise(resolve=>release=resolve);const sent=[];
  await page.route('**/api/choice',async route=>{sent.push(JSON.parse(route.request().postData()).choice);if(sent.length===1)await held;await route.continue();});
  await page.getByRole('radio',{name:'Compact list'}).click();
  await page.getByRole('button',{name:'Choose this option'}).click();
  await page.locator('#selection-status',{hasText:'Saving…'}).waitFor();
  await page.getByRole('radio',{name:'Status board'}).click();
  assert.equal(await page.locator('#selection-status').textContent(),'Saving…','Still saving after switching options');
  assert.ok(await page.getByRole('button',{name:'Choose this option'}).isDisabled(),'No second send while one is in flight');
  release();
  await page.getByText('Saved: Compact list. Press the button to change it to Status board.').waitFor();
  assert.deepEqual(sent,['list'],'Only the first choice was sent');
  await page.getByRole('button',{name:'Choose this option'}).click();
  await page.getByText('Choice saved. You can continue in chat.').waitFor();
  assert.deepEqual(sent,['list','board'],'The second choice is sent after the first lands');
  await page.unroute('**/api/choice');
  const handoff={mode:'handoff',title:'Review what changed',summary:'Choices show comparisons; finished work shows results and evidence.',sections:[{kind:'explanation',title:'From request to result',body:'Proceed with clear tasks. Show alternatives only when a choice is needed.',html:'<div style="display:grid;gap:12px"><div style="background:#eef4f1;padding:16px;border-radius:10px">Request → visual choice when needed</div><div style="text-align:center">↓</div><div style="background:#e9eff8;padding:16px;border-radius:10px">Implementation · verification → result</div></div>'}],checks:[{status:'verified',text:'Keyboard selection and saved choice',evidence:'Selected with arrow keys in Chromium, submitted, and confirmed the board event.'},{status:'unverified',text:'Visual quality of a real user app',evidence:'This checks the companion feature; no separate app was evaluated.'}]};
  handoff.sections.push({kind:'explanation',title:'Routing and schema explanation example',body:'Rendering example only; it does not represent a real app change or applied migration.',html:'<h2>Changed field comparison</h2><table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>'+Array.from({length:25},(_,i)=>`<tr><th>column_${i}</th><td>nullable</td><td>NOT NULL · Example explanation</td></tr>`).join('')+'</tbody></table><details><summary>Check command details</summary><div style="height:400px">Additional check results</div></details>'});
  handoff.sections.push({kind:'observed',title:'Review capture attachment check',body:'Companion screen captured in Chromium for this check; not a mobile simulator capture.',image:path.join(output,'decision.png')});
  fs.writeFileSync(path.join(temporary,'store.ts'),Array.from({length:30},(_,i)=>i===11?'export async function saveTask(task: Task): Promise<void> { // keep order\n  const key = "tasks"; return storage.set(key, JSON.stringify([task, 42, null]));\n}':`const line${i} = ${i};`).join('\n'));
  handoff.sections.push({kind:'explanation',title:'Full-height mock',body:'A screen sized to the viewport must not grow its frame forever.',html:'<div style="min-height:100vh;background:#eef4f1">Phone screen</div>'});
  handoff.sections.push({kind:'explanation',title:'Growing chart',body:'Content that really grows, in steps or smoothly, gets its full height.',html:'<style>@keyframes r{from{max-height:0}to{max-height:3000px}}@keyframes g{from{height:0}to{height:1500px}}.s{overflow:hidden;animation:r .3s steps(3,end) forwards}.l{animation:g .6s linear forwards}</style><div class=s><div style="height:1200px;background:#fc9"></div></div><div class=l style="background:#9cf"></div><p>end</p>'});
  handoff.sections.push({kind:'explanation',title:'Transition on everything',body:'A transition on a viewport-sized screen must not grow its frame forever.',html:'<style>*{transition:all .3s}</style><div style="min-height:100vh;background:#eef4f1">Phone screen</div>'});
  handoff.sections.push({kind:'explanation',title:'Transitioned hero',body:'A hero whose height transitions must settle too.',html:'<style>.hero{height:100vh;transition:height .2s ease;background:#9cf}</style><div class=hero>Hero</div>'});
  const multi='diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n a\n-b\n+c\ndiff --git a/y.py b/y.py\nindex 111..222 100644\n--- a/y.py\n+++ b/y.py\n@@ -10,1 +10,1 @@\n-q\n+r\n';
  handoff.files=[
    {path:'store.ts',why:'Saving tasks now keeps their order.',lines:[12,14]},
    {path:'api/routes.py',why:'The new route checks the owner before saving.',diff:true,code:'@@ -10,3 +10,4 @@ def save(request):\n     task = load(request)\n-    return store(task)\n+    if task.owner != request.user:  # refuse others\n+        raise Forbidden("not yours")\n     return store(task)\n'},
    {path:'two-files.diff',why:'Two files in one diff.',diff:true,code:multi},
    {path:'web/unclosed.js',why:'An unclosed quote with many escaped quotes stays fast.',code:'"'+'\\"'.repeat(150000)},
    {path:'package-lock.json',why:'A very long diff still opens.',diff:true,code:'@@ -1,0 +1,70000 @@\n'+Array.from({length:70000},(_,i)=>'+ v'+i).join('\n')},
  ];
  publish(handoff);await page.getByRole('heading',{name:handoff.title}).waitFor();
  const files=page.locator('#files details.file');
  assert.equal(await files.count(),5);
  assert.equal(await page.locator('#files .editor').count(),0,'Code stays folded until opened');
  const openMs=await page.evaluate(()=>{const item=document.getElementById('file-3');const start=performance.now();item.open=true;item.dispatchEvent(new Event('toggle'));return performance.now()-start;});
  assert.ok(openMs<1000,'Unclosed quotes highlight in linear time ('+Math.round(openMs)+' ms)');
  await page.locator('#file-3 summary').click();
  await page.locator('#file-0 summary').click();
  const first=page.locator('#file-0 .code');await first.waitFor();
  assert.equal(await first.locator('.line').count(),3);
  assert.equal((await first.locator('.line .no').first().textContent()).trim(),'12');
  assert.ok((await first.innerText()).includes('saveTask'),'Code is read from the project file');
  for(const [cls,value] of [['kw','export'],['fn','saveTask'],['ty','Promise'],['str','"tasks"'],['num','42'],['lit','null'],['com','// keep order']])
    assert.equal(await first.locator('.tk-'+cls,{hasText:value}).count()>0,true,`${cls} token for ${value}`);
  await page.getByRole('button',{name:'Expand all'}).click();
  await page.getByRole('button',{name:'Collapse all'}).waitFor();
  const diff=page.locator('#file-1 .code');
  assert.equal(await diff.locator('.line.add').count(),2);assert.equal(await diff.locator('.line.del').count(),1);
  assert.equal((await diff.locator('.line.add .no').first().textContent()).trim(),'11',"Added lines use the new file's numbers");
  assert.equal(await diff.locator('.tk-com',{hasText:'# refuse others'}).count(),1);
  const two=page.locator('#file-2 .code');
  assert.deepEqual(await two.locator('.line.meta').allTextContents().then(rows=>rows.map(row=>row.trim())),['diff --git a/x.py b/x.py','--- a/x.py','+++ b/x.py','diff --git a/y.py b/y.py','index 111..222 100644','--- a/y.py','+++ b/y.py'],'Every file header is a header');
  assert.equal(await two.locator('.line.add').count(),2);assert.equal(await two.locator('.line.del').count(),2);
  assert.equal((await two.locator('.line.del .no').last().textContent()).trim(),'10');
  assert.equal(await page.locator('#file-4 .code .line.add').count(),70000,'A long diff renders');
  assert.equal(await page.locator('#contents a',{hasText:'Files worth reviewing'}).count(),1);
  await page.locator('#files').screenshot({path:path.join(output,'files.png')});
  await page.getByRole('button',{name:'Collapse all'}).click();
  await page.locator('#file-0 summary').click();
  const detailed=page.locator('#section-1 iframe');
  await waitFor(async()=>await detailed.evaluate(frame=>frame.clientHeight>760));
  assert.equal(await page.locator('#contents a').count(),8);
  const fullHeight=page.locator('#section-3 iframe');
  await new Promise(r=>setTimeout(r,400));const settled=await fullHeight.evaluate(frame=>frame.clientHeight);
  await new Promise(r=>setTimeout(r,600));
  assert.equal(await fullHeight.evaluate(frame=>frame.clientHeight),settled,'A 100vh visual settles');
  assert.ok(settled<1200,'A 100vh visual stays near one screen ('+settled+')');
  for(const index of [5,6]){
    const transitioned=page.locator('#section-'+index+' iframe');
    await new Promise(r=>setTimeout(r,800));const first=await transitioned.evaluate(frame=>frame.clientHeight);
    await new Promise(r=>setTimeout(r,1200));const later=await transitioned.evaluate(frame=>frame.clientHeight);
    assert.equal(later,first,'A transitioned 100vh visual settles ('+first+' then '+later+')');
    assert.ok(later<1200,'A transitioned 100vh visual stays near one screen ('+later+')');
    assert.ok(await transitioned.evaluate(frame=>!frame.style.paddingBottom&&!frame.contentDocument.documentElement.style.overflow&&![...frame.contentDocument.querySelectorAll('style')].some(style=>style.textContent.includes('transition:none'))),'Measurement styles are removed');
  }
  // A frame that navigates to a document with no body (an SVG file) keeps its size and has no measurement styles left on it.
  await page.route('**/no-body.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600"><rect width="800" height="600" fill="#9cf"/></svg>'}));
  const navigated=page.locator('#section-6 iframe');const sizeBefore=await navigated.evaluate(frame=>frame.offsetHeight);
  await navigated.evaluate(frame=>new Promise(resolve=>{frame.addEventListener('load',()=>setTimeout(resolve,300),{once:true});frame.contentWindow.location.href='/no-body.svg';}));
  assert.deepEqual(await navigated.evaluate(frame=>[frame.offsetHeight,frame.style.paddingBottom,frame.style.minHeight,frame.contentDocument.body===null,frame.contentDocument.documentElement.style.overflow]),[sizeBefore,'','',true,''],'Navigating to a document without a body leaves no measurement styles');
  await page.unroute('**/no-body.svg');
  const growing=page.locator('#section-4 iframe');
  await waitFor(()=>growing.evaluate(frame=>frame.contentDocument.body.getBoundingClientRect().height>2700));
  await new Promise(r=>setTimeout(r,300));
  assert.ok(await growing.evaluate(frame=>{const d=frame.contentDocument.documentElement;return d.scrollHeight<=d.clientHeight+1;}),'A growing visual is not clipped');
  const capture=page.locator('#section-2 img');
  await waitFor(()=>capture.evaluate(img=>img.complete&&img.naturalWidth===1280));
  assert.ok((await capture.getAttribute('src')).startsWith('/assets/'));
  assert.ok(requested.some(url=>new URL(url).pathname==='/report-view.js'&&new URL(url).origin===new URL(info.url).origin),'Renderer module is loaded from the same origin');
  assert.deepEqual([...new Set(requested.filter(url=>/^https?:/.test(url)).map(url=>new URL(url).hostname))],['127.0.0.1'],'No request leaves 127.0.0.1');
  assert.equal(await page.evaluate(()=>typeof window.renderReport),'undefined','Module does not leak globals');
  const original=page.getByRole('link',{name:'Review capture attachment check · Open original image (new tab)'});
  assert.equal(await original.getAttribute('rel'),'noopener');
  assert.ok(await capture.evaluate(img=>img.naturalHeight>560),'Fixture exercises a tall capture');
  await original.focus();
  const popupPromise=page.waitForEvent('popup');await page.keyboard.press('Enter');const popup=await popupPromise;
  await popup.waitForLoadState();
  assert.equal(new URL(popup.url()).pathname,await capture.getAttribute('src'));
  await waitFor(()=>popup.locator('img').evaluate(img=>img.complete&&img.naturalWidth===1280));
  assert.deepEqual(await popup.locator('img').evaluate(img=>[img.naturalWidth,img.naturalHeight]),await capture.evaluate(img=>[img.naturalWidth,img.naturalHeight]));
  assert.equal(await popup.evaluate(()=>window.opener===null),true);
  await popup.close();
  const gridWidth=await page.locator('#sections').evaluate(e=>e.clientWidth);
  assert.ok((await detailed.boundingBox()).width>gridWidth-4,'Handoff diagrams use full width');
  const heightBefore=(await detailed.boundingBox()).height;
  await page.frameLocator('#section-1 iframe').getByText('Check command details').click();
  await waitFor(async()=>(await detailed.boundingBox()).height>heightBefore+300);
  await page.getByRole('link',{name:'Routing and schema explanation example'}).click();
  assert.ok(page.url().endsWith('#section-1'));
  assert.equal(await page.getByRole('button',{name:'Choose this option'}).isVisible(),false);
  assert.equal(await page.getByRole('radio').count(),0);
  const stale=await page.evaluate(async version=>(await fetch('/api/choice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({version,choice:'list'})})).status,oldVersion);
  assert.equal(stale,409);
  await page.screenshot({path:path.join(output,'handoff.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'No horizontal overflow');
  await waitFor(async()=>await detailed.evaluate(frame=>frame.clientHeight>=frame.contentDocument.body.getBoundingClientRect().height));
  await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
  await page.reload();await page.getByRole('heading',{name:handoff.title}).waitFor();
  assert.deepEqual(errors,[]);
  server.kill('SIGINT');await waitFor(()=>server.exitCode!==null);
  await page.getByText('Disconnected · Last page').waitFor();
  const result={passed:true,checks:['rendered alternatives','sandboxed HTML','keyboard selection','persisted choice','image decision selection without navigation','live handoff update','no approval on handoff','stale-choice rejection','mobile width','reload cookie','disconnection indicator','full-width detailed handoff','long table without height cap','expandable details resize','section navigation','actual captured image served and decoded','keyboard original image access with authenticated full-resolution popup','file accordions with code read from the project, line numbers, highlighting and diffs','renderer module served same-origin','late choice ignored after page change','multi-file diff headers','linear highlighting of unclosed quotes','70k-line diff','100vh visual settles','transitioned 100vh visuals settle','no measurement styles left after navigating to a document without a body','growing visual reaches full height','saving status and the saved option named after switching mid-send','saved choice survives a reconnect without a second post','no request leaves 127.0.0.1','no global renderer leak'],screenshots:['decision.png','handoff.png','mobile.png']};
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,output},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server.exitCode===null)server.kill('SIGINT');await waitFor(()=>server.exitCode!==null).catch(()=>server.kill('SIGKILL'));if(runtimeDirectory)fs.rmSync(path.dirname(runtimeDirectory),{recursive:true,force:true});fs.rmSync(temporary,{recursive:true,force:true});fs.rmSync(storeDirectory,{recursive:true,force:true});});
