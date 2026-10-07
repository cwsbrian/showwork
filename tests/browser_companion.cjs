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
const output = path.join(root, '.showwork/visual-test');
fs.mkdirSync(output, {recursive:true});
const python = process.env.PYTHON || 'python3';
const server = spawn(python, [script, 'serve', '--project', temporary]);
let browser;
function publish(document) {
  const source = path.join(temporary, 'source.json'); fs.writeFileSync(source, JSON.stringify(document));
  const result = spawnSync(python, [script, 'publish', '--project', temporary, '--file', source], {encoding:'utf8'});
  assert.equal(result.status, 0, result.stderr); return JSON.parse(result.stdout).published;
}
async function waitFor(check) { const end=Date.now()+5000; while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,50));}throw Error('Timed out'); }

(async()=>{
  const info = await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.includes('\n'))resolve(JSON.parse(buffer.split('\n')[0]));});server.once('error',reject);server.once('exit',code=>reject(Error('Server exited '+code)));setTimeout(()=>reject(Error('Server did not start')),5000).unref();});
  const decision={mode:'decision',title:'할 일, 어떤 모습이 더 편한가요?',summary:'선택 기능의 테스트 화면입니다. 실제 제품에 대한 승인 요청이 아닙니다.',question:'목록을 읽는 방식만 비교합니다.',options:[
    {id:'list',title:'간결한 목록',body:'할 일을 한 줄씩 빠르게 훑어봅니다.',html:'<div style="background:#eef4f1;padding:24px;border-radius:12px"><h2>오늘의 할 일</h2><p>☐ 장보기</p><p>☑ 운동하기</p><p style="color:#647">+ 할 일 추가</p></div>'},
    {id:'board',title:'상태별 보드',body:'해야 할 일과 완료한 일을 나눠 봅니다.',html:'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><section style="background:#eef4f1;border-radius:12px;padding:18px"><h3>할 일</h3><p>장보기</p></section><section style="background:#e9eff8;border-radius:12px;padding:18px"><h3>완료</h3><p>운동하기</p></section></div><script>parent.__unsafe=true</script>'}
  ]};
  const oldVersion=publish(decision);
  browser=await chromium.launch({headless:true,executablePath:process.env.SHOWWORK_CHROMIUM});
  const page=await browser.newPage({viewport:{width:1280,height:960}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(info.url);await page.getByRole('heading',{name:decision.title}).waitFor();
  assert.equal(await page.evaluate(()=>window.__unsafe),undefined,'Embedded scripts must not execute');
  await page.screenshot({path:path.join(output,'decision.png'),fullPage:true});
  await page.getByRole('radio',{name:'간결한 목록'}).focus();await page.keyboard.press('ArrowRight');
  assert.equal(await page.getByRole('radio',{name:'상태별 보드'}).getAttribute('aria-checked'),'true');
  await page.getByRole('button',{name:'이 안으로 선택'}).click();
  await page.getByText('선택을 기록했습니다. 채팅에서 계속할 수 있습니다.').waitFor();
  const events=JSON.parse(spawnSync(python,[script,'events','--project',temporary],{encoding:'utf8'}).stdout);
  assert.equal(events.events.at(-1).choice,'board');
  const handoff={mode:'handoff',title:'무엇이 바뀌었는지 함께 보기',summary:'선택할 때는 비교 화면을, 끝났을 때는 결과와 근거를 보여줍니다.',sections:[{kind:'explanation',title:'요청에서 결과까지',body:'명확한 작업은 바로 진행합니다. 선택이 필요한 지점에서만 비교안을 보여줍니다.',html:'<div style="display:grid;gap:12px"><div style="background:#eef4f1;padding:16px;border-radius:10px">요청 → 필요할 때만 시각적 선택</div><div style="text-align:center">↓</div><div style="background:#e9eff8;padding:16px;border-radius:10px">구현 · 검증 → 결과 설명</div></div>'}],checks:[{status:'verified',text:'키보드로 선택하고 결과 저장',evidence:'Chromium에서 방향키로 선택 후 제출, events 명령으로 board 기록 확인.'},{status:'unverified',text:'실제 사용자 앱의 시각적 품질',evidence:'이 화면은 companion 기능을 시험한 결과이며 별도 앱을 평가하지 않았습니다.'}]};
  handoff.sections.push({kind:'explanation',title:'라우팅 · 스키마 변경 설명 예시',body:'렌더링 검사용 예시입니다. 실제 앱의 변경이나 적용된 마이그레이션을 뜻하지 않습니다.',html:'<h2>변경된 필드 비교</h2><table><thead><tr><th>필드</th><th>이전</th><th>이후</th></tr></thead><tbody>'+Array.from({length:25},(_,i)=>`<tr><th>column_${i}</th><td>nullable</td><td>NOT NULL · 설명 예시</td></tr>`).join('')+'</tbody></table><details><summary>검증 명령 상세</summary><div style="height:400px">추가 검증 결과</div></details>'});
  publish(handoff);await page.getByRole('heading',{name:handoff.title}).waitFor();
  const detailed=page.locator('#section-1 iframe');
  await waitFor(async()=>await detailed.evaluate(frame=>frame.clientHeight>760));
  assert.equal(await page.locator('#contents a').count(),2);
  const gridWidth=await page.locator('#sections').evaluate(e=>e.clientWidth);
  assert.ok((await detailed.boundingBox()).width>gridWidth-4,'Handoff diagrams use full width');
  const heightBefore=(await detailed.boundingBox()).height;
  await page.frameLocator('#section-1 iframe').getByText('검증 명령 상세').click();
  await waitFor(async()=>(await detailed.boundingBox()).height>heightBefore+300);
  await page.getByRole('link',{name:'라우팅 · 스키마 변경 설명 예시'}).click();
  assert.ok(page.url().endsWith('#section-1'));
  assert.equal(await page.getByRole('button',{name:'이 안으로 선택'}).isVisible(),false);
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
  await page.getByText('연결 끊김 · 마지막 화면').waitFor();
  const result={passed:true,checks:['rendered alternatives','sandboxed HTML','keyboard selection','persisted choice','live handoff update','no approval on handoff','stale-choice rejection','mobile width','reload cookie','disconnection indicator','full-width detailed handoff','long table without height cap','expandable details resize','section navigation'],screenshots:['decision.png','handoff.png','mobile.png']};
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server.exitCode===null)server.kill('SIGINT');await waitFor(()=>server.exitCode!==null).catch(()=>server.kill('SIGKILL'));fs.rmSync(temporary,{recursive:true,force:true});});
