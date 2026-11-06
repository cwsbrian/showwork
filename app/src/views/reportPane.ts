import { renderReport } from '@report-view';
import type { ShowworkApi } from '../api';
import { typeLabel } from '../model';

let paneCount = 0;

export function createReportPane(container: HTMLElement, api: ShowworkApi, onChosen: (reportId: string) => void = () => {}) {
  const prefix = `pane${paneCount++}-`;
  let current: { destroy(): void; refresh(): void } | null = null;
  let token = 0;

  function placeholder(text: string) {
    current?.destroy();
    current = null;
    container.replaceChildren();
    const p = document.createElement('p');
    p.className = 'empty';
    p.textContent = text;
    container.append(p);
  }
  placeholder('Select a report');

  function header(meta: import('../model').ReportMeta): HTMLElement {
    const head = document.createElement('div');
    head.className = 'pane-head';
    const parts: Array<[string, string]> = [['type', typeLabel(meta.type)]];
    if (meta.branch) parts.push(['branch', meta.branch]);
    if (meta.commit) parts.push(['commit', meta.commit.slice(0, 7)]);
    parts.push(['agent', meta.agent], ['time', new Date(meta.createdAt).toLocaleString()]);
    for (const [cls, value] of parts) {
      const s = document.createElement('span');
      s.className = 'meta meta-' + cls;
      s.textContent = value;
      head.append(s);
    }
    if (meta.open && !meta.chosen) {
      const tag = document.createElement('span');
      tag.className = 'needs-choice';
      tag.textContent = 'Needs your choice';
      head.append(tag);
    }
    return head;
  }

  return {
    clear() {
      token++;
      placeholder('Select a report');
    },
    // Resolves true only when this report was rendered and is still the one shown.
    async show(projectId: string, reportId: string): Promise<boolean> {
      const mine = ++token;
      let detail;
      try {
        detail = await api.getReport(projectId, reportId);
      } catch (e) {
        // Tauri rejects with a plain string.
        if (mine === token) placeholder('Could not open this report: ' + (e instanceof Error ? e.message : String(e)));
        return false;
      }
      if (mine !== token) return false;
      current?.destroy();
      container.replaceChildren();
      const head = header(detail.meta);
      const body = document.createElement('div');
      body.className = 'report-body';
      container.append(head, body);
      current = renderReport(body, detail.page, {
        idPrefix: prefix,
        // A closed decision (a newer report exists) shows its options but cannot be chosen.
        connected: () => detail.meta.open,
        unavailableText: 'This question is closed. A newer report replaced it.',
        assetUrl: (rel) => api.assetUrl(detail.dir, rel),
        submitChoice: async (choice) => {
          try {
            await api.submitChoice(projectId, reportId, detail.meta.version, choice);
          } catch (e) {
            // Tauri rejects with a plain string; the renderer shows error.message.
            throw e instanceof Error ? e : new Error(String(e));
          }
          head.querySelector('.needs-choice')?.remove();
          onChosen(reportId);
        },
      });
      // The shared renderer sets the title to the page title; keep the app's own.
      document.title = 'Showwork · ' + detail.meta.title;
      return true;
    },
  };
}
