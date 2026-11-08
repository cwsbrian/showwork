import type { ProjectSummary } from '../api';
import { showMenu } from './menu';

export interface ProjectsHandlers {
  select(projectId: string): void;
  reveal(projectId: string): void;
  remove(projectId: string): void;
}

const HUES = [168, 212, 262, 18, 336, 42, 128, 190];

function avatar(name: string, size: 'lg' | 'sm') {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const el = document.createElement('span');
  el.className = 'avatar avatar-' + size;
  el.style.setProperty('--hue', String(HUES[hash % HUES.length]));
  el.textContent = (name.match(/[A-Za-z0-9가-힣]/)?.[0] ?? '?').toUpperCase();
  el.setAttribute('aria-hidden', 'true');
  return el;
}

// "https://github.com/owner/repo.git" or "git@github.com:owner/repo.git" -> "owner/repo".
export function shortRemote(remote: string | null): string | null {
  if (!remote) return null;
  const parts = remote.replace(/\.git$/, '').split(/[/:]/).filter(Boolean);
  return parts.length >= 2 ? parts.slice(-2).join('/') : remote;
}

// The current project sits at the top of the reports column; clicking it opens a list of all projects.
export function createProjects(container: HTMLElement, h: ProjectsHandlers) {
  let open = false;
  let query = '';
  let projects: ProjectSummary[] = [];
  let selectedId: string | null = null;

  const actions = (p: ProjectSummary) => [
    { label: 'Reveal in Finder', run: () => h.reveal(p.id) },
    { label: 'Delete history', confirm: 'Click again to delete history', run: () => h.remove(p.id) },
  ];
  const setOpen = (v: boolean, focusTrigger = false) => {
    if (open === v) return;
    open = v;
    if (!v) query = '';
    draw();
    if (v) (container.querySelector<HTMLElement>('.switcher-search') ?? container.querySelector<HTMLElement>('.project[aria-current="true"], .project'))?.focus();
    else if (focusTrigger) container.querySelector<HTMLElement>('.switcher-trigger')?.focus();
  };

  document.addEventListener('mousedown', (e) => {
    const t = e.target as Element;
    if (open && !container.contains(t) && !t.closest?.('.ctx-menu')) setOpen(false);
  });
  window.addEventListener('blur', () => setOpen(false));

  function row(p: ProjectSummary) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'project';
    b.dataset.projectId = p.id;
    b.title = p.remote ?? p.name;
    if (p.id === selectedId) b.setAttribute('aria-current', 'true');
    const name = document.createElement('span');
    name.className = 'project-name';
    name.textContent = p.displayName;
    b.append(avatar(p.name, 'sm'), name);
    if (p.running > 0) {
      const spinner = document.createElement('span');
      spinner.className = 'spinner';
      spinner.title = p.running === 1 ? 'Working on a report' : `Working on ${p.running} reports`;
      spinner.setAttribute('aria-label', spinner.title);
      b.append(spinner);
    }
    if (p.unread > 0) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = String(p.unread);
      badge.setAttribute('aria-label', p.unread + ' unread');
      b.append(badge);
    }
    if (p.id === selectedId) {
      const check = document.createElement('span');
      check.className = 'current-mark';
      check.textContent = '✓';
      check.setAttribute('aria-hidden', 'true');
      b.append(check);
    }
    b.onclick = () => {
      setOpen(false, true);
      h.select(p.id);
    };
    b.oncontextmenu = (e) => {
      e.preventDefault();
      showMenu(e.clientX, e.clientY, actions(p));
    };
    return b;
  }

  function draw() {
    container.replaceChildren();
    const current = projects.find((p) => p.id === selectedId) ?? null;
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'switcher-trigger';
    trigger.setAttribute('aria-haspopup', 'true');
    trigger.setAttribute('aria-expanded', String(open));
    trigger.setAttribute('aria-label', 'Project: ' + (current?.displayName ?? 'none') + '. Switch project');
    const text = document.createElement('span');
    text.className = 'switcher-text';
    const name = document.createElement('span');
    name.className = 'switcher-name';
    const sub = document.createElement('span');
    sub.className = 'switcher-sub';
    if (current) {
      name.textContent = current.displayName;
      sub.textContent = shortRemote(current.remote) ?? 'Local folder';
      trigger.append(avatar(current.name, 'lg'));
    } else {
      name.textContent = projects.length ? 'Select a project' : 'No projects yet';
      sub.textContent = projects.length ? projects.length + ' projects' : 'Reports show up here';
    }
    text.append(name, sub);
    trigger.append(text);
    const others = projects.reduce((n, p) => n + (p.id === selectedId ? 0 : p.unread), 0);
    if (others > 0) {
      const badge = document.createElement('span');
      badge.className = 'badge others-unread';
      badge.textContent = String(others);
      badge.title = others + ' unread in other projects';
      trigger.append(badge);
    }
    const chevron = document.createElement('span');
    chevron.className = 'chevron';
    chevron.setAttribute('aria-hidden', 'true');
    trigger.append(chevron);
    trigger.disabled = !projects.length;
    trigger.onclick = () => setOpen(!open);
    trigger.oncontextmenu = (e) => {
      if (!current) return;
      e.preventDefault();
      showMenu(e.clientX, e.clientY, actions(current));
    };
    container.append(trigger);
    if (!open) return;

    const pop = document.createElement('div');
    pop.className = 'switcher-pop';
    const list = document.createElement('div');
    list.className = 'project-list';
    const fill = () => {
      const q = query.trim().toLowerCase();
      const shown = projects.filter((p) => !q || p.displayName.toLowerCase().includes(q) || (p.remote ?? '').toLowerCase().includes(q));
      list.replaceChildren(...shown.map(row));
      if (!shown.length) list.append(Object.assign(document.createElement('p'), { className: 'empty', textContent: 'No matching project' }));
    };
    if (projects.length > 6) {
      const search = document.createElement('input');
      search.className = 'switcher-search';
      search.type = 'search';
      search.placeholder = 'Find a project';
      search.setAttribute('aria-label', 'Find a project');
      search.value = query;
      search.oninput = () => {
        query = search.value;
        fill();
      };
      pop.append(search);
    }
    fill();
    pop.append(list);
    pop.onkeydown = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false, true);
        return;
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      const rows = [...list.querySelectorAll<HTMLElement>('.project')];
      const at = rows.indexOf(document.activeElement as HTMLElement);
      const next = e.key === 'ArrowDown' ? Math.min(at + 1, rows.length - 1) : Math.max(at - 1, 0);
      rows[next]?.focus();
    };
    container.append(pop);
  }

  return {
    render(next: ProjectSummary[], nextSelected: string | null) {
      projects = next;
      selectedId = nextSelected;
      // Keep focus inside an open list when a refresh redraws it.
      const focused = (document.activeElement as HTMLElement | null)?.dataset?.projectId;
      const searching = document.activeElement?.classList.contains('switcher-search');
      draw();
      if (!open) return;
      if (searching) container.querySelector<HTMLInputElement>('.switcher-search')?.focus();
      else if (focused) container.querySelector<HTMLElement>(`.project[data-project-id="${CSS.escape(focused)}"]`)?.focus();
    },
  };
}
