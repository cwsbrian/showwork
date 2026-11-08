import type { SessionItem } from '../model';

export type TabContext = { key: string; running: boolean; stopped?: boolean } | null;

export function sessionLabel(s: SessionItem): string {
  if (s.title) return s.title;
  if (s.kind === 'ios-simulator') return 'iOS Simulator';
  try { return new URL(s.url).host || s.url; } catch { return s.url; }
}

export function createTabs(container: HTMLElement, h: {
  reportHost: HTMLElement;
  screen(s: SessionItem, interactive: boolean): HTMLElement & { dispose?: () => void };
  closeSession(id: string): void;
}) {
  const active = new Map<string, string>();
  let context: TabContext = null;
  let sessions: SessionItem[] = [];
  let screens: Array<HTMLElement & { dispose?: () => void }> = [];

  function choose(id: string) {
    if (!context) return;
    active.set(context.key, id);
    render(context, sessions);
  }

  function render(ctx: TabContext, next: SessionItem[]) {
    context = ctx;
    sessions = next;
    const current = ctx ? active.get(ctx.key) ?? 'report' : 'report';
    const valid = current === 'report' || (current === 'split' && next.length >= 2) || next.some((s) => s.id === current);
    const selected = valid ? current : 'report';
    if (ctx) active.set(ctx.key, selected);

    screens.forEach((screen) => screen.dispose?.());
    screens = [];
    container.replaceChildren();
    const bar = document.createElement('div');
    bar.className = 'tabs-bar';
    bar.setAttribute('role', 'tablist');
    const body = document.createElement('div');
    body.className = 'tabs-body';
    if (selected !== 'report' && selected !== 'split') body.classList.add('session-body');
    const tab = (id: string, label: string, closable = false) => {
      const el = document.createElement('div');
      el.className = 'tab';
      el.setAttribute('role', 'tab');
      el.setAttribute('aria-selected', String(selected === id));
      el.tabIndex = 0;
      const name = document.createElement('span');
      name.textContent = label;
      el.append(name);
      el.onclick = () => choose(id);
      el.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(id); } };
      if (closable) {
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'tab-close';
        close.setAttribute('aria-label', `Close ${label.replace(' · ended', '')}`);
        close.textContent = '×';
        close.onclick = (e) => { e.stopPropagation(); h.closeSession(id); };
        el.append(close);
      }
      bar.append(el);
    };
    tab('report', 'Report');
    for (const s of next) tab(s.id, sessionLabel(s) + (s.alive ? '' : ' · ended'), !s.alive);
    if (next.length >= 2) tab('split', 'Split');
    container.append(bar, body);

    h.reportHost.hidden = selected !== 'report';
    if (selected === 'report') {
      body.append(h.reportHost);
      if (ctx?.running) {
        h.reportHost.hidden = true;
        const waiting = document.createElement('p');
        waiting.className = 'report-waiting';
        waiting.textContent = 'Working on it. The report appears here when it is ready.';
        body.append(waiting);
      } else if (ctx?.stopped) {
        const stopped = document.createElement('p');
        stopped.className = 'report-waiting';
        stopped.textContent = 'This task ended without a report.';
        body.append(stopped);
      }
    } else {
      // Keep the report view attached so publishing can update it without rebuilding the pane.
      h.reportHost.hidden = true;
      body.append(h.reportHost);
      if (selected === 'split') {
        const grid = document.createElement('div');
        grid.className = 'split-grid';
        for (const s of next) {
          const tile = document.createElement('button');
          tile.type = 'button';
          tile.className = 'split-tile';
          const name = document.createElement('span');
          name.className = 'split-label';
          name.textContent = sessionLabel(s);
          const preview = document.createElement('div');
          preview.className = 'split-preview';
          preview.style.aspectRatio = `${s.width} / ${s.height}`;
          const screen = h.screen(s, false);
          screens.push(screen);
          preview.append(screen);
          tile.append(name, preview);
          tile.onclick = () => choose(s.id);
          grid.append(tile);
        }
        body.append(grid);
      } else {
        const s = next.find((item) => item.id === selected);
        if (s) {
          const screen = h.screen(s, true);
          screens.push(screen);
          body.append(screen);
        }
      }
    }
  }
  return { render };
}
