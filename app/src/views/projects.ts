import type { ProjectSummary } from '../api';
import { showMenu } from './menu';

export interface ProjectsHandlers {
  select(projectId: string): void;
  reveal(projectId: string): void;
  remove(projectId: string): void;
}

export function createProjects(container: HTMLElement, h: ProjectsHandlers) {
  return {
    render(projects: ProjectSummary[], selectedId: string | null) {
      container.replaceChildren();
      const title = document.createElement('h2');
      title.className = 'col-title';
      title.textContent = 'Projects';
      const list = document.createElement('div');
      list.className = 'project-list';
      if (!projects.length) {
        const p = document.createElement('p');
        p.className = 'empty';
        p.textContent = 'No projects yet';
        list.append(p);
      }
      for (const p of projects) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'project';
        b.dataset.projectId = p.id;
        b.title = p.remote ?? p.name;
        if (p.id === selectedId) b.setAttribute('aria-current', 'true');
        const name = document.createElement('span');
        name.className = 'project-name';
        name.textContent = p.displayName;
        b.append(name);
        if (p.unread > 0) {
          const badge = document.createElement('span');
          badge.className = 'badge';
          badge.textContent = String(p.unread);
          badge.setAttribute('aria-label', p.unread + ' unread');
          b.append(badge);
        }
        b.onclick = () => h.select(p.id);
        b.oncontextmenu = (e) => {
          e.preventDefault();
          showMenu(e.clientX, e.clientY, [
            { label: 'Reveal in Finder', run: () => h.reveal(p.id) },
            { label: 'Delete history', confirm: 'Click again to delete history', run: () => h.remove(p.id) },
          ]);
        };
        list.append(b);
      }
      container.append(title, list);
    },
  };
}
