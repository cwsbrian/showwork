import { invoke, convertFileSrc } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { ReportMeta, RunningItem, SessionItem } from './model';

export type { ReportMeta, RunningItem, SessionItem };
export type View = 'list' | 'flow';

export interface ProjectSummary {
  id: string;
  name: string;
  displayName: string;
  remote: string | null;
  lastActivity: string | null;
  unread: number;
  running: number;
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
  listRunning(projectId: string): Promise<RunningItem[]>;
  listSessions(projectId: string, runId: string): Promise<SessionItem[]>;
  listAllSessions(projectId: string): Promise<SessionItem[]>;
  deleteSession(projectId: string, sessionId: string): Promise<void>;
  deleteRunning(projectId: string, runId: string): Promise<void>;
  getReport(projectId: string, reportId: string): Promise<ReportDetail>;
  submitChoice(projectId: string, reportId: string, version: string, choice: string): Promise<void>;
  markRead(reportId: string): Promise<void>;
  getState(): Promise<{ view: View }>;
  setView(view: View): Promise<void>;
  deleteReport(projectId: string, reportId: string): Promise<void>;
  deleteProject(projectId: string): Promise<void>;
  revealProject(projectId: string): Promise<void>;
  onArrival(cb: (p: ReportRef) => void): void;
  onRunningChanged(cb: () => void): void;
  onOpenReport(cb: (p: ReportRef) => void): void;
  assetUrl(dir: string, relative: string): string;
}

function tauriApi(): ShowworkApi {
  return {
    listProjects: () => invoke('list_projects'),
    listReports: (projectId) => invoke('list_reports', { projectId }),
    listRunning: (projectId) => invoke('list_running', { projectId }),
    listSessions: (projectId, runId) => invoke('list_sessions', { projectId, runId }),
    listAllSessions: (projectId) => invoke('list_all_sessions', { projectId }),
    deleteSession: (projectId, sessionId) => invoke('delete_session', { projectId, sessionId }),
    deleteRunning: (projectId, runId) => invoke('delete_running', { projectId, runId }),
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
    onRunningChanged: (cb) => void listen('running-changed', () => cb()),
    onOpenReport: (cb) => void listen<ReportRef>('open-report', (e) => cb(e.payload)),
    assetUrl: (dir, relative) => convertFileSrc(dir + '/' + relative),
  };
}

interface Fixture {
  projects: Omit<ProjectSummary, 'unread' | 'running'>[];
  running?: Record<string, RunningItem[]>;
  sessions?: SessionItem[];
  reports: Record<string, ReportMeta[]>;
  pages: Record<string, any>;
  unread?: string[];
}

function mockApi(fixture: Fixture): ShowworkApi {
  const reports: Record<string, ReportMeta[]> = JSON.parse(JSON.stringify(fixture.reports));
  const pages: Record<string, any> = { ...fixture.pages };
  const projects = fixture.projects.map((p) => ({ ...p }));
  const unread = new Set(fixture.unread ?? []);
  const running: Record<string, RunningItem[]> = JSON.parse(JSON.stringify(fixture.running ?? {}));
  const sessions: SessionItem[] = JSON.parse(JSON.stringify(fixture.sessions ?? []));
  const runningChanged: Array<() => void> = [];
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
    start(item: RunningItem) {
      const list = (running[item.projectId] ??= []).filter((r) => r.id !== item.id);
      running[item.projectId] = [item, ...list];
      runningChanged.forEach((cb) => cb());
    },
    finish(projectId: string, runId: string) {
      running[projectId] = (running[projectId] ?? []).filter((r) => r.id !== runId);
      runningChanged.forEach((cb) => cb());
    },
    addSession(s: SessionItem) {
      const old = sessions.findIndex((x) => x.id === s.id);
      if (old >= 0) sessions.splice(old, 1);
      sessions.push(s);
      runningChanged.forEach((cb) => cb());
    },
    endSession(id: string) {
      const s = sessions.find((x) => x.id === id);
      if (s) { s.endedAt = new Date().toISOString(); s.alive = false; }
      runningChanged.forEach((cb) => cb());
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
        running: (running[p.id] ?? []).length,
      }));
    },
    async listReports(projectId) {
      return newestFirst(reports[projectId] ?? []).map((r) => ({ ...r, read: !unread.has(r.id) }));
    },
    async listRunning(projectId) {
      return [...(running[projectId] ?? [])];
    },
    async listSessions(projectId, runId) {
      return sessions.filter((s) => s.projectId === projectId && s.run === runId)
        .sort((a, b) => a.startedAt.localeCompare(b.startedAt) || a.id.localeCompare(b.id)).map((s) => ({ ...s }));
    },
    async listAllSessions(projectId) {
      return sessions.filter((s) => s.projectId === projectId).map((s) => ({...s}));
    },
    async deleteSession(projectId, sessionId) {
      const idx = sessions.findIndex((s) => s.projectId === projectId && s.id === sessionId);
      if (idx >= 0 && sessions[idx].alive) throw new Error('This session is still running');
      if (idx >= 0) sessions.splice(idx, 1);
      runningChanged.forEach((cb) => cb());
    },
    async deleteRunning(projectId, runId) {
      failing('deleteRunning');
      running[projectId] = (running[projectId] ?? []).filter((r) => r.id !== runId);
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
      if (sessions.some((s) => s.projectId === projectId && s.alive)) throw new Error('This session is still running');
      delete reports[projectId];
      projects.splice(projects.findIndex((p) => p.id === projectId), 1);
    },
    async revealProject(projectId) {
      failing('revealProject');
      calls.push({ fn: 'revealProject', projectId });
    },
    onArrival: (cb) => void arrivals.push(cb),
    onRunningChanged: (cb) => void runningChanged.push(cb),
    onOpenReport: (cb) => void opens.push(cb),
    assetUrl: (dir, relative) => dir + '/' + relative,
  };
}

export function createApi(): ShowworkApi {
  if ((window as any).__TAURI_INTERNALS__) return tauriApi();
  return mockApi((window as any).__SHOWWORK_FIXTURE__ ?? { projects: [], reports: {}, pages: {} });
}
