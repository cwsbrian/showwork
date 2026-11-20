import type { View } from '../api';
import { branchGroups, NO_BRANCH, ReportMeta, RunningItem, typeLabel } from '../model';
import { showMenu } from './menu';

export interface MiddleHandlers {
  select(reportId: string): void;
  selectRun(runId: string): void;
  setView(view: View): void;
  remove(reportId: string): void;
  removeRunning(runId: string): void;
  removeStopped(runId: string): void;
  filterChanged(): void;
  loadMore(): void;
}

export interface ListPageState {
  branches: string[];
  types: string[];
  hasMore: boolean;
  loadingMore: boolean;
}

export function createMiddle(container: HTMLElement, h: MiddleHandlers) {
  const filter = { branch: '', type: '' };
  let lastProject: string | null = null;
  let filterOpen = false;
  container.addEventListener('scroll', () => {
    if (last && !last.loading && last.page.hasMore && !last.page.loadingMore
      && container.scrollTop + container.clientHeight >= container.scrollHeight - 180) h.loadMore();
  });

  const closeFilters = (focusButton: boolean) => {
    if (!filterOpen) return;
    filterOpen = false;
    redraw();
    if (focusButton) container.querySelector<HTMLElement>('.filter-btn')?.focus();
  };
  document.addEventListener('mousedown', (e) => {
    if (filterOpen && !(e.target as Element).closest?.('.filter-wrap')) closeFilters(false);
  });
  document.addEventListener('keydown', (e) => {
    if (filterOpen && e.key === 'Escape') closeFilters(true);
  });

  function select(label: string, options: string[], current: string, all: string, text: (v: string) => string, set: (v: string) => void, rerender: () => void) {
    const el = document.createElement('select');
    el.setAttribute('aria-label', label);
    el.append(new Option(all, ''));
    for (const o of options) el.append(new Option(text(o), o));
    el.value = options.includes(current) ? current : '';
    el.onchange = () => {
      set(el.value);
      rerender();
      container.querySelector<HTMLElement>(`select[aria-label="${label}"]`)?.focus();
    };
    return el;
  }

  function withActions(button: HTMLButtonElement, title: string, actions: Array<{label: string; confirm?: string; run: () => void}>): HTMLElement {
    const entry = document.createElement('div');
    entry.className = 'list-entry';
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'item-actions';
    more.textContent = '⋯';
    more.setAttribute('aria-label', `Actions for ${title}`);
    more.setAttribute('aria-haspopup', 'menu');
    more.title = `Actions for ${title}`;
    const open = (x: number, y: number) => showMenu(x, y, actions, more);
    more.onclick = (e) => {
      e.stopPropagation();
      const rect = more.getBoundingClientRect();
      open(Math.max(8, rect.right - 180), rect.bottom + 4);
    };
    button.oncontextmenu = (e) => { e.preventDefault(); open(e.clientX, e.clientY); };
    entry.append(button, more);
    return entry;
  }

  function item(r: ReportMeta, selectedId: string | null): HTMLElement {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = r.read ? 'item' : 'item unread';
    b.dataset.reportId = r.id;
    if (r.id === selectedId || r.versions?.some((version) => version.id === selectedId)) b.setAttribute('aria-current', 'true');
    const tag = document.createElement('span');
    tag.className = 'type-tag type-' + r.type;
    tag.textContent = typeLabel(r.type);
    const title = document.createElement('span');
    title.className = 'item-title';
    title.textContent = r.versions?.slice().reverse().find((version) => version.reportType === 'plan')?.title ?? r.versions?.[0]?.title ?? r.title;
    const sub = document.createElement('span');
    sub.className = 'item-sub';
    sub.textContent = new Date(r.createdAt).toLocaleString();
    b.append(tag, title, sub);
    if ((r.versions?.length ?? 0) > 1) {
      const count = document.createElement('span');
      count.className = 'version-count';
      count.textContent = `${r.versions!.length} versions`;
      b.append(count);
    }
    if (!r.read) {
      const dot = document.createElement('span');
      dot.className = 'unread-dot';
      dot.setAttribute('aria-label', 'Unread');
      dot.title = 'Unread';
      b.prepend(dot);
    }
    if (r.open && !r.chosen) {
      const need = document.createElement('span');
      need.className = 'needs-choice';
      need.textContent = 'Needs your choice';
      b.append(need);
    }
    b.onclick = () => h.select(r.id);
    return withActions(b, r.title, [{ label: 'Delete report', confirm: 'Click again to delete report', run: () => h.remove(r.id) }]);
  }

  // A report still being made can be opened to watch its sessions.
  function workingItem(r: RunningItem, selectedId: string | null): HTMLElement {
    const el = document.createElement('button');
    el.type = 'button';
    el.className = r.ended ? 'item stopped' : 'item running';
    el.dataset.runId = r.id;
    if (r.id === selectedId) el.setAttribute('aria-current', 'true');
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    spinner.setAttribute('aria-hidden', 'true');
    const tag = document.createElement('span');
    tag.className = 'type-tag type-' + r.type;
    tag.textContent = typeLabel(r.type);
    const title = document.createElement('span');
    title.className = 'item-title';
    title.textContent = r.title || (r.ended ? 'Finished browser session' : 'Working on the ' + typeLabel(r.type).toLowerCase() + '…');
    const sub = document.createElement('span');
    sub.className = 'item-sub';
    const started = new Date(r.startedAt);
    const time = isNaN(started.getTime()) ? '' : ' · started ' + started.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    sub.textContent = (r.ended ? 'Task ended' : 'In progress') + time + (r.agent && r.agent !== 'unknown' ? ' · ' + r.agent : '');
    if (!r.ended) el.append(spinner);
    el.append(tag, title, sub);
    el.onclick = () => h.selectRun(r.id);
    return withActions(el, title.textContent, r.ended
      ? [{label: 'Delete task history', confirm: 'Click again to delete task history', run: () => h.removeStopped(r.id)}]
      : [{label: 'Remove from list', run: () => h.removeRunning(r.id)}]);
  }

  let last: { projectId: string | null; reports: ReportMeta[]; view: View; selectedId: string | null; loading: boolean; running: RunningItem[]; selectedRunId: string | null; page: ListPageState } | null = null;

  function render(projectId: string | null, reports: ReportMeta[], view: View, selectedId: string | null, loading = false, running: RunningItem[] = [], selectedRunId: string | null = null, page: ListPageState = {branches: [], types: [], hasMore: false, loadingMore: false}) {
    last = { projectId, reports, view, selectedId, loading, running, selectedRunId, page };
    if (projectId !== lastProject) {
      filter.branch = '';
      filter.type = '';
      lastProject = projectId;
    }
    const scrollTop = container.scrollTop;
    container.replaceChildren();
    const bar = document.createElement('div');
    bar.className = 'toolbar';
    const seg = document.createElement('div');
    seg.className = 'segmented';
    seg.setAttribute('role', 'group');
    seg.setAttribute('aria-label', 'View');
    for (const v of ['list', 'flow'] as View[]) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = v === 'list' ? 'List' : 'Flow';
      b.setAttribute('aria-pressed', String(v === view));
      b.onclick = () => h.setView(v);
      seg.append(b);
    }
    const rerender = () => render(projectId, reports, view, selectedId, loading, running, selectedRunId, page);
    const branches = page.branches;
    const types = page.types;
    // A filter whose last report is gone would hide everything while its control reads "All".
    if (!loading && !branches.includes(filter.branch)) filter.branch = '';
    if (!loading && !types.includes(filter.type)) filter.type = '';
    bar.append(seg, filterControl(branches, types, rerender));
    const body = document.createElement('div');
    body.className = 'middle-body';
    const shown = reports;
    const working = running.filter((r) => (!filter.branch || (r.branch ?? NO_BRANCH) === filter.branch) && (!filter.type || r.type === filter.type));
    if (projectId && !loading && working.length) {
      const group = document.createElement('div');
      group.className = 'working-list';
      working.forEach((r) => group.append(workingItem(r, selectedRunId)));
      body.append(group);
    }
    if (!projectId) {
      body.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Select a project' }));
    } else if (loading) {
      body.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Loading…' }));
    } else if (!shown.length && working.length) {
      // only working items so far
    } else if (!shown.length) {
      body.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'No reports' }));
    } else if (view === 'list') {
      body.classList.add('view-list');
      shown.forEach((r) => body.append(item(r, selectedId)));
    } else {
      body.classList.add('view-flow');
      for (const g of branchGroups(shown)) {
        const sec = document.createElement('section');
        sec.className = 'flow-branch';
        const head = document.createElement('h3');
        head.textContent = g.branch;
        const chain = document.createElement('div');
        chain.className = 'flow-chain';
        g.reports.forEach((r) => chain.append(item(r, selectedId)));
        sec.append(head, chain);
        body.append(sec);
      }
    }
    if (projectId && !loading && page.hasMore) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'load-more';
      more.textContent = page.loadingMore ? 'Loading more…' : 'Load more reports';
      more.disabled = page.loadingMore;
      more.onclick = h.loadMore;
      body.append(more);
    }
    container.append(bar, body);
    container.scrollTop = scrollTop;
  }

  // A funnel button that shows how many filters are on; the branch and type choices open in a popover.
  function filterControl(branches: string[], types: string[], rerender: () => void) {
    const wrap = document.createElement('div');
    wrap.className = 'filter-wrap';
    const active = (filter.branch ? 1 : 0) + (filter.type ? 1 : 0);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'filter-btn';
    btn.setAttribute('aria-label', active ? `Filters (${active} on)` : 'Filters');
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', String(filterOpen));
    btn.title = 'Filters';
    btn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 5h18l-7 8.5V19l-4 2v-7.5z"/></svg>';
    if (active) {
      btn.classList.add('on');
      const count = document.createElement('span');
      count.className = 'filter-count';
      count.textContent = String(active);
      btn.append(count);
    }
    btn.onclick = () => {
      filterOpen = !filterOpen;
      rerender();
      if (filterOpen) container.querySelector<HTMLElement>('.filter-pop select')?.focus();
    };
    wrap.append(btn);
    if (!filterOpen) return wrap;
    const pop = document.createElement('div');
    pop.className = 'filter-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Filters');
    const field = (name: string, control: HTMLSelectElement) => {
      const label = document.createElement('label');
      label.className = 'filter-field';
      label.append(Object.assign(document.createElement('span'), { textContent: name }), control);
      return label;
    };
    pop.append(
      field('Branch', select('Branch', branches, filter.branch, 'All branches', (v) => v, (v) => (filter.branch = v), h.filterChanged)),
      field('Type', select('Type', types, filter.type, 'All types', typeLabel, (v) => (filter.type = v), h.filterChanged)),
    );
    if (active) {
      const clear = document.createElement('button');
      clear.type = 'button';
      clear.className = 'filter-clear';
      clear.textContent = 'Clear filters';
      clear.onclick = () => {
        filter.branch = '';
        filter.type = '';
        h.filterChanged();
        container.querySelector<HTMLElement>('.filter-pop select')?.focus();
      };
      pop.append(clear);
    }
    wrap.append(pop);
    return wrap;
  }

  function redraw() {
    if (last) render(last.projectId, last.reports, last.view, last.selectedId, last.loading, last.running, last.selectedRunId, last.page);
  }

  return {
    render,
    filters: () => ({...filter}),
    syncFilters: (branches: string[], types: string[]) => {
      let changed = false;
      if (filter.branch && !branches.includes(filter.branch)) { filter.branch = ''; changed = true; }
      if (filter.type && !types.includes(filter.type)) { filter.type = ''; changed = true; }
      return changed;
    },
    rerender: redraw,
  };
}
