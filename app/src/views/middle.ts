import type { View } from '../api';
import { branchGroups, filterReports, NO_BRANCH, ReportMeta, typeLabel } from '../model';
import { showMenu } from './menu';

export interface MiddleHandlers {
  select(reportId: string): void;
  setView(view: View): void;
  remove(reportId: string): void;
}

export function createMiddle(container: HTMLElement, h: MiddleHandlers) {
  const filter = { branch: '', type: '' };
  let lastProject: string | null = null;

  function select(label: string, options: string[], current: string, all: string, text: (v: string) => string, set: (v: string) => void, rerender: () => void) {
    const el = document.createElement('select');
    el.setAttribute('aria-label', label);
    el.append(new Option(all, ''));
    for (const o of options) el.append(new Option(text(o), o));
    el.value = options.includes(current) ? current : '';
    el.onchange = () => {
      set(el.value);
      rerender();
    };
    return el;
  }

  function item(r: ReportMeta, selectedId: string | null): HTMLElement {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'item';
    b.dataset.reportId = r.id;
    if (r.id === selectedId) b.setAttribute('aria-current', 'true');
    const tag = document.createElement('span');
    tag.className = 'type-tag type-' + r.type;
    tag.textContent = typeLabel(r.type);
    const title = document.createElement('span');
    title.className = 'item-title';
    title.textContent = r.title;
    const sub = document.createElement('span');
    sub.className = 'item-sub';
    sub.textContent = new Date(r.createdAt).toLocaleString();
    b.append(tag, title, sub);
    if (r.open && !r.chosen) {
      const need = document.createElement('span');
      need.className = 'needs-choice';
      need.textContent = 'Needs your choice';
      b.append(need);
    }
    b.onclick = () => h.select(r.id);
    b.oncontextmenu = (e) => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, [{ label: 'Delete report', confirm: 'Click again to delete report', run: () => h.remove(r.id) }]);
    };
    return b;
  }

  let last: { projectId: string | null; reports: ReportMeta[]; view: View; selectedId: string | null; loading: boolean } | null = null;

  function render(projectId: string | null, reports: ReportMeta[], view: View, selectedId: string | null, loading = false) {
    last = { projectId, reports, view, selectedId, loading };
    if (projectId !== lastProject) {
      filter.branch = '';
      filter.type = '';
      lastProject = projectId;
    }
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
    const rerender = () => render(projectId, reports, view, selectedId, loading);
    const branches = [...new Set(reports.map((r) => r.branch ?? NO_BRANCH))];
    const types = [...new Set(reports.map((r) => r.type))];
    // A filter whose last report is gone would hide everything while its control reads "All".
    if (!loading && !branches.includes(filter.branch)) filter.branch = '';
    if (!loading && !types.includes(filter.type)) filter.type = '';
    bar.append(
      seg,
      select('Branch', branches, filter.branch, 'All branches', (v) => v, (v) => (filter.branch = v), rerender),
      select('Type', types, filter.type, 'All types', typeLabel, (v) => (filter.type = v), rerender),
    );
    const body = document.createElement('div');
    body.className = 'middle-body';
    const shown = filterReports(reports, { branch: filter.branch, type: filter.type });
    if (!projectId) {
      body.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Select a project' }));
    } else if (loading) {
      body.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'Loading…' }));
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
    container.append(bar, body);
  }

  return { render, rerender: () => last && render(last.projectId, last.reports, last.view, last.selectedId, last.loading) };
}
