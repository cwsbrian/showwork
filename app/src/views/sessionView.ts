import type { BrowserSession } from '../model';
import { connect, type Cdp } from '../cdp';

type View = { img: HTMLImageElement; status: HTMLElement; viewport: HTMLElement; address?: HTMLInputElement; size?: HTMLElement };
type Live = { item: BrowserSession; views: Set<View>; cdp?: Cdp; connecting?: boolean; frame?: string; width: number; height: number; url: string; failed: boolean; closing?: ReturnType<typeof setTimeout> };
const live = new Map<string, Live>();
const endedFrames = new Map<string, { frame: string; width: number; height: number; url: string }>();
(window as any).__showworkLiveCount = 0;

function displayUrl(url: string): string {
  if (!url.startsWith('data:')) return url;
  const mime = url.slice(5).split(/[;,]/, 1)[0] || 'text/plain';
  return `${mime} · inline page`;
}

function paint(state: Live) {
  for (const view of state.views) {
    view.img.hidden = !state.frame;
    if (state.frame) view.img.src = 'data:image/jpeg;base64,' + state.frame;
    view.img.style.opacity = state.item.alive ? '1' : '.55';
    view.status.textContent = state.failed && state.item.alive ? 'Could not connect to this browser.' : !state.frame ? (state.item.alive ? 'Connecting to browser…' : 'Browser session ended.') : '';
    view.status.classList.toggle('error', state.failed && state.item.alive);
    if (view.address) {
      if (document.activeElement !== view.address) { view.address.value = displayUrl(state.url); view.address.scrollLeft = 0; }
      view.address.readOnly = !state.item.alive;
    }
    if (view.size) view.size.textContent = `${state.width} × ${state.height}`;
  }
}

function connectState(state: Live) {
  if (!state.item.alive || state.cdp || state.connecting) return;
  state.connecting = true;
  void connect(state.item.ws, {
    frame(data, width, height) {
      state.frame = data;
      if (width > 0) state.width = width;
      if (height > 0) state.height = height;
      paint(state);
    },
    url(url) { state.url = url; paint(state); },
    closed() {
      if (state.cdp) {
        state.cdp = undefined;
        (window as any).__showworkLiveCount--;
      }
      state.failed = true;
      paint(state);
    },
  }).then((cdp) => {
    state.connecting = false;
    if (!state.views.size || !state.item.alive) { cdp.close(); return; }
    state.cdp = cdp;
    (window as any).__showworkLiveCount++;
    for (const view of state.views) if (view.address) {
      const box = view.viewport.getBoundingClientRect();
      if (box.width && box.height) cdp.resize(Math.round(box.width), Math.round(box.height));
    }
  }).catch(() => { state.connecting = false; state.failed = true; paint(state); });
}

export function createScreen(s: BrowserSession, interactive: boolean): HTMLElement & { dispose(): void } {
  let state = live.get(s.id);
  if (!state) {
    state = { item: s, views: new Set(), width: s.width, height: s.height, url: s.url, failed: false };
    if (!s.alive) Object.assign(state, endedFrames.get(s.id));
    live.set(s.id, state);
  }
  state.item = s;
  if (state.closing) { clearTimeout(state.closing); state.closing = undefined; }
  if (!s.alive && state.cdp) { state.cdp.close(); state.cdp = undefined; (window as any).__showworkLiveCount--; }

  const root = document.createElement('div') as HTMLElement & { dispose?: () => void };
  root.className = 'session-screen';
  if (interactive) root.tabIndex = 0;
  const img = document.createElement('img');
  img.className = 'session-frame';
  img.alt = 'Live browser screen';
  img.draggable = false;
  const status = document.createElement('div');
  status.className = 'session-status';
  const viewport = document.createElement('div');
  viewport.className = 'session-viewport';
  viewport.append(img, status);
  const address = interactive ? document.createElement('input') : undefined;
  const size = interactive ? document.createElement('span') : undefined;
  if (address && size) {
    const toolbar = document.createElement('div');
    toolbar.className = 'session-toolbar';
    address.className = 'session-address';
    address.type = 'text';
    address.inputMode = 'url';
    address.setAttribute('aria-label', 'Page address');
    address.spellcheck = false;
    size.className = 'session-size';
    toolbar.append(address, size);
    root.append(toolbar);
  }
  root.append(viewport);
  const view = { img, status, viewport, address, size };
  state.views.add(view);
  paint(state);
  connectState(state);
  const resize = interactive ? new ResizeObserver(() => {
    const box = viewport.getBoundingClientRect();
    if (box.width && box.height) state!.cdp?.resize(Math.round(box.width), Math.round(box.height));
  }) : undefined;
  resize?.observe(viewport);

  const point = (e: MouseEvent | WheelEvent) => {
    const box = img.getBoundingClientRect();
    const scale = Math.min(box.width / state!.width, box.height / state!.height);
    const left = box.left + (box.width - state!.width * scale) / 2;
    const top = box.top + (box.height - state!.height * scale) / 2;
    return { x: Math.max(0, Math.min(state!.width, (e.clientX - left) / scale)), y: Math.max(0, Math.min(state!.height, (e.clientY - top) / scale)) };
  };
  if (interactive) {
    address!.onkeydown = (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      e.stopPropagation();
      const entered = address!.value.trim();
      if (!entered || !state!.cdp) return;
      const url = /^[a-z][a-z\d+.-]*:/i.test(entered) ? entered : `https://${entered}`;
      state!.url = url;
      state!.cdp.navigate(url);
      address!.blur();
    };
    address!.onfocus = () => { address!.value = state!.url; address!.select(); };
    address!.onblur = () => paint(state!);
    img.onmousedown = (e) => { if (!state!.cdp) return; root.focus(); const p = point(e); state!.cdp.mouse('mousePressed', p.x, p.y, e.detail || 1); e.preventDefault(); };
    img.onmouseup = (e) => { if (!state!.cdp) return; const p = point(e); state!.cdp.mouse('mouseReleased', p.x, p.y, e.detail || 1); e.preventDefault(); };
    let movePending = false;
    img.onmousemove = (e) => {
      if (!state!.cdp || movePending) return;
      const p = point(e); movePending = true;
      requestAnimationFrame(() => { movePending = false; state!.cdp?.mouse('mouseMoved', p.x, p.y, 0); });
    };
    img.onwheel = (e) => { if (!state!.cdp) return; const p = point(e); state!.cdp.wheel(p.x, p.y, e.deltaX, e.deltaY); e.preventDefault(); };
    root.onkeydown = (e) => {
      if (!state!.cdp || e.target !== root) return;
      if (e.key.length === 1 && !e.metaKey && !e.ctrlKey && !e.altKey) state!.cdp.text(e.key);
      else state!.cdp.key('rawKeyDown', { key: e.key, code: e.code, keyCode: e.keyCode });
      e.preventDefault();
    };
    root.onkeyup = (e) => {
      if (!state!.cdp || e.target !== root) return;
      if (e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey) state!.cdp.key('keyUp', { key: e.key, code: e.code, keyCode: e.keyCode });
      e.preventDefault();
    };
  }
  root.dispose = () => {
    resize?.disconnect();
    state!.views.delete(view);
    if (!state!.views.size) state!.closing = setTimeout(() => {
      if (state!.views.size) return;
      if (!state!.item.alive && state!.frame) {
        endedFrames.delete(s.id);
        endedFrames.set(s.id, { frame: state!.frame, width: state!.width, height: state!.height, url: state!.url });
        if (endedFrames.size > 8) endedFrames.delete(endedFrames.keys().next().value!);
      }
      state!.cdp?.close();
      if (state!.cdp) (window as any).__showworkLiveCount--;
      state!.cdp = undefined;
      live.delete(s.id);
    }, 0);
  };
  return root as HTMLElement & { dispose(): void };
}
