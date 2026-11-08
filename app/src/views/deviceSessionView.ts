import type { IosSession, AndroidSession } from '../model';

type DeviceSession = IosSession | AndroidSession;
const label = (s: DeviceSession) => s.kind === 'android-emulator' ? 'Android Emulator' : 'Simulator';
type View = { img: HTMLImageElement; status: HTMLElement };
type Live = { item: DeviceSession; views: Set<View>; controller: AbortController; seq: number; width: number; height: number; frame?: string; error?: string; terminal?: boolean; closing?: ReturnType<typeof setTimeout> };
const live = new Map<string, Live>();
// Ended frames stay in memory only, with a small bound, and are released on eviction.
const ended = new Map<string, { frame: string; width: number; height: number }>();
const keyOf = (s: DeviceSession) => `${s.projectId}/${s.id}/${s.port}/${s.token}`;
function paint(state: Live) {
  for (const v of state.views) {
    v.img.hidden = !state.frame || !!state.error;
    if (state.frame && !state.error) v.img.src = state.frame;
    else v.img.removeAttribute('src');
    v.img.style.opacity = state.item.alive ? '1' : '.55';
    v.status.textContent = state.error || (!state.item.alive ? `${label(state.item)} session ended.` : !state.frame ? `Connecting to ${label(state.item)}…` : '');
    v.status.classList.toggle('error', !!state.error);
  }
}
async function poll(state: Live) {
  let failures = 0;
  while (!state.controller.signal.aborted && state.item.alive) {
    try {
      const r = await fetch(`http://127.0.0.1:${state.item.port}/frame?after=${state.seq}`, { headers: { 'X-Session-Token': state.item.token }, signal: state.controller.signal });
      if (r.status === 410) { state.error = `${label(state.item)} session ended.`; state.terminal = true; state.item = {...state.item, alive:false}; paint(state); return; }
      if (r.status === 204) { continue; }
      if (!r.ok) throw Error('relay response');
      const units = state.item.kind === 'android-emulator' ? 'Pixels' : 'Points';
      const width = Number(r.headers.get(`X-${units}-Width`)), height = Number(r.headers.get(`X-${units}-Height`));
      const seq = Number(r.headers.get('X-Frame-Seq'));
      if (!(width > 0 && height > 0 && seq > state.seq)) throw Error('invalid frame metadata');
      const blob = await r.blob();
      if (state.controller.signal.aborted) return;
      const candidate = URL.createObjectURL(blob);
      try {
        const decoded = new Image(); decoded.src = candidate;
        await decoded.decode();
        if (state.controller.signal.aborted) { URL.revokeObjectURL(candidate); return; }
      } catch (error) { URL.revokeObjectURL(candidate); throw error; }
      const previous = state.frame;
      state.frame = candidate; state.width = width; state.height = height; state.seq = seq;
      failures = 0; state.error = undefined; paint(state);
      if (previous) URL.revokeObjectURL(previous);
    } catch {
      if (state.controller.signal.aborted) return;
      // Hide stale content immediately; retry briefly before terminating the poll.
      state.error = `Could not connect to this ${label(state.item)}.`; paint(state);
      if (++failures >= 3) return;
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, 250);
        state.controller.signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, {once:true});
      });
    }
  }
}
export function createDeviceScreen(s: DeviceSession, interactive: boolean): HTMLElement & { dispose(): void } {
  const key = keyOf(s);
  let state = live.get(key);
  if (!state) {
    state = {item:s, views:new Set(), controller:new AbortController(), seq:0, width:s.kind === 'ios-simulator' ? s.pointsWidth : s.width, height:s.kind === 'ios-simulator' ? s.pointsHeight : s.height};
    if (!s.alive) { const old = ended.get(key); if (old) { Object.assign(state, old); ended.delete(key); } }
    live.set(key,state);
    if (s.alive) void poll(state);
  }
  state.item = state.terminal ? {...s, alive:false} : s;
  if (!s.alive) state.controller.abort();
  clearTimeout(state.closing);
  const current = state;
  const root = document.createElement('div') as unknown as HTMLElement & { dispose(): void };
  root.className = `session-screen device-screen ${s.kind === 'android-emulator' ? 'android-screen' : 'ios-screen'}`;
  const img = document.createElement('img'); img.className='session-frame'; img.alt=`Live ${s.kind === 'android-emulator' ? 'Android Emulator' : 'iOS Simulator'} screen`; img.draggable=false;
  img.onerror=()=>{
    if (disposed || !img.getAttribute('src')) return;
    current.error=`Could not display this ${label(current.item)}.`;
    current.controller.abort();paint(current);
  };
  const status=document.createElement('div');status.className='session-status';
  const viewport=document.createElement('div');viewport.className='session-viewport';viewport.append(img,status);
  const inputControllers = new Set<AbortController>();
  let disposed=false;
  const send = async(action: object) => {
    if (disposed || !interactive || !current.item.alive || current.error) return;
    const body=JSON.stringify(action);
    const controller=new AbortController();inputControllers.add(controller);
    try {
      const r=await fetch(`http://127.0.0.1:${s.port}/input`,{method:'POST',headers:{'X-Session-Token':s.token,'Content-Type':'application/json'},body,signal:controller.signal});
      if(!r.ok)throw Error('input failed');
    } catch { if(!controller.signal.aborted){current.error=`Could not send input to this ${label(current.item)}.`;current.controller.abort();paint(current);} }
    finally {inputControllers.delete(controller);}
  };
  if(interactive){
    const point=(e:PointerEvent,clamp:boolean)=>{
      const b=img.getBoundingClientRect();
      const scale=Math.min(b.width/current.width,b.height/current.height);
      const x=(e.clientX-b.left-(b.width-current.width*scale)/2)/scale;
      const y=(e.clientY-b.top-(b.height-current.height*scale)/2)/scale;
      if(!scale || (!clamp && (x<0||y<0||x>=current.width||y>=current.height)))return;
      return {x:Math.max(0,Math.min(current.width-1,Math.round(x))),y:Math.max(0,Math.min(current.height-1,Math.round(y)))};
    };
    let start: {x:number;y:number;time:number;clientX:number;clientY:number;pointerId:number} | undefined;
    img.onpointerdown=e=>{if(e.button!==0||!current.item.alive||current.error)return;const p=point(e,false);if(!p)return;start={...p,time:performance.now(),clientX:e.clientX,clientY:e.clientY,pointerId:e.pointerId};img.setPointerCapture(e.pointerId);e.preventDefault();};
    img.onpointerup=e=>{const from=start;start=undefined;if(!from||from.pointerId!==e.pointerId)return;const to=point(e,true);if(!to)return;const drag=Math.hypot(e.clientX-from.clientX,e.clientY-from.clientY)>5;void send(drag?{type:'swipe',x1:from.x,y1:from.y,x2:to.x,y2:to.y,duration:Math.max(.05,Math.min(2,(performance.now()-from.time)/1000))}:{type:'tap',x:from.x,y:from.y});};
    img.onpointercancel=()=>{start=undefined;};
  }
  root.append(viewport);
  const view={img,status};current.views.add(view);paint(current);
  root.dispose=()=>{
    if(disposed)return;disposed=true;inputControllers.forEach(c=>c.abort());current.views.delete(view);
    if(!current.views.size)current.closing=setTimeout(()=>{
      if(current.views.size)return;current.controller.abort();live.delete(key);
      if(current.frame){
        if(!current.item.alive && !current.error){ended.set(key,{frame:current.frame,width:current.width,height:current.height});if(ended.size>8){const first=ended.keys().next().value!;URL.revokeObjectURL(ended.get(first)!.frame);ended.delete(first);}}
        else URL.revokeObjectURL(current.frame);
      }
    },0);
  };
  return root;
}
