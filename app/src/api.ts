import { invoke, convertFileSrc } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { ReportMeta } from './model';

export type { ReportMeta };
export type View = 'list' | 'flow';

export interface ProjectSummary {
  id: string;
  name: string;
  displayName: string;
  remote: string | null;
  lastActivity: string | null;
  unread: number;
}

export interface ReportDetail {
  meta: ReportMeta;
  page: any;
  dir: string;
}

export interface ReportRef {
  projectId: string;
  reportId: string;
}

export interface ShowworkApi {
  listProjects(): Promise<ProjectSummary[]>;
  listReports(projectId: string): Promise<ReportMeta[]>;
  getReport(projectId: string, reportId: string): Promise<ReportDetail>;
  submitChoice(projectId: string, reportId: string, version: string, choice: string): Promise<void>;
  markRead(reportId: string): Promise<void>;
  getState(): Promise<{ view: View }>;
  setView(view: View): Promise<void>;
  deleteReport(projectId: string, reportId: string): Promise<void>;
  deleteProject(projectId: string): Promise<void>;
  revealProject(projectId: string): Promise<void>;
  onArrival(cb: (p: ReportRef) => void): void;
  onOpenReport(cb: (p: ReportRef) => void): void;
  assetUrl(dir: string, relative: string): string;
}

function tauriApi(): ShowworkApi {
  return {
    listProjects: () => invoke('list_projects'),
    listReports: (projectId) => invoke('list_reports', { projectId }),
    getReport: (projectId, reportId) => invoke('get_report', { projectId, reportId }),
    submitChoice: (projectId, reportId, version, choice) =>
      invoke('submit_choice', { projectId, reportId, version, choice }),
    markRead: (reportId) => invoke('mark_read', { reportId }),
    getState: () => invoke('get_state'),
    setView: (view) => invoke('set_view', { view }),
    deleteReport: (projectId, reportId) => invoke('delete_report', { projectId, reportId }),
    deleteProject: (projectId) => invoke('delete_project', { projectId }),
    revealProject: (projectId) => invoke('reveal_project', { projectId }),
    onArrival: (cb) => void listen<ReportRef>('report-arrived', (e) => cb(e.payload)),
    onOpenReport: (cb) => void listen<ReportRef>('open-report', (e) => cb(e.payload)),
    assetUrl: (dir, relative) => convertFileSrc(dir + '/' + relative),
  };
}

interface Fixture {
  projects: Omit<ProjectSummary, 'unread'>[];
  reports: Record<string, ReportMeta[]>;
  pages: Record<string, any>;
  unread?: string[];
}

function mockApi(fixture: Fixture): ShowworkApi {
  const reports: Record<string, ReportMeta[]> = JSON.parse(JSON.stringify(fixture.reports));
  const pages: Record<string, any> = { ...fixture.pages };
  const projects = fixture.projects.map((p) => ({ ...p }));
  const unread = new Set(fixture.unread ?? []);
  const arrivals: Array<(p: ReportRef) => void> = [];
  const opens: Array<(p: ReportRef) => void> = [];
  const calls: any[] = [];
  const find = (reportId: string) =>
    Object.values(reports).flat().find((r) => r.id === reportId);
  const newestFirst = (list: ReportMeta[]) =>
    [...list].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  const read = (k: string): string | null => {
    try { return localStorage.getItem(k); } catch { return null; }
  };

  const mock = ((window as any).__showworkMock = {
    calls,
    // Set to a string to make the next submitChoice reject with it, as Tauri does.
    failNext: null as string | null,
    // Set a method name to a string to make its next call reject with that string.
    fail: {} as Record<string, string>,
    arrive(projectId: string, meta: ReportMeta, page: any) {
      (reports[projectId] ??= []).push(meta);
      pages[meta.id] = page;
      unread.add(meta.id);
      arrivals.forEach((cb) => cb({ projectId, reportId: meta.id }));
    },
    open(projectId: string, reportId: string) {
      opens.forEach((cb) => cb({ projectId, reportId }));
    },
  });

  const failing = (fn: string) => {
    const reason = mock.fail[fn];
    if (reason === undefined) return;
    delete mock.fail[fn];
    throw reason;
  };

  return {
    async listProjects() {
      return projects.map((p) => ({
        ...p,
        unread: (reports[p.id] ?? []).filter((r) => unread.has(r.id)).length,
      }));
    },
    async listReports(projectId) {
      return newestFirst(reports[projectId] ?? []);
    },
    async getReport(projectId, reportId) {
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta) throw new Error('Report not found');
      return { meta: { ...meta }, page: pages[reportId], dir: '/mock/' + projectId };
    },
    async submitChoice(projectId, reportId, version, choice) {
      if (mock.failNext !== null) {
        const reason = mock.failNext;
        mock.failNext = null;
        throw reason;
      }
      calls.push({ fn: 'submitChoice', projectId, reportId, version, choice });
      const meta = find(reportId);
      if (meta) meta.chosen = true;
    },
    async markRead(reportId) {
      failing('markRead');
      unread.delete(reportId);
    },
    async getState() {
      // A test can set __SHOWWORK_OPEN__ to deliver an open-report event while startup is still loading.
      const early = (window as any).__SHOWWORK_OPEN__ as ReportRef | undefined;
      if (early) {
        (window as any).__SHOWWORK_OPEN__ = undefined;
        opens.forEach((cb) => cb(early));
      }
      return { view: read('showwork-mock-view') === 'flow' ? 'flow' : 'list' };
    },
    async setView(view) {
      failing('setView');
      try { localStorage.setItem('showwork-mock-view', view); } catch { /* ignore */ }
    },
    async deleteReport(projectId, reportId) {
      failing('deleteReport');
      reports[projectId] = (reports[projectId] ?? []).filter((r) => r.id !== reportId);
    },
    async deleteProject(projectId) {
      delete reports[projectId];
      projects.splice(projects.findIndex((p) => p.id === projectId), 1);
    },
    async revealProject(projectId) {
      failing('revealProject');
      calls.push({ fn: 'revealProject', projectId });
    },
    onArrival: (cb) => void arrivals.push(cb),
    onOpenReport: (cb) => void opens.push(cb),
    assetUrl: (dir, relative) => dir + '/' + relative,
  };
}

export function createApi(): ShowworkApi {
  if ((window as any).__TAURI_INTERNALS__) return tauriApi();
  return mockApi((window as any).__SHOWWORK_FIXTURE__ ?? { projects: [], reports: {}, pages: {} });
}
