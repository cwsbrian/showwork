import { invoke, convertFileSrc } from '@tauri-apps/api/core';
import { getVersion } from '@tauri-apps/api/app';
import { listen } from '@tauri-apps/api/event';
import { check, type Update } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';
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

export interface CommentAnchor {
  target: string;
  start: number;
  end: number;
  quote: string;
}

export interface ReportComment {
  id: string;
  version: string;
  anchor: CommentAnchor;
  body: string;
  createdAt: string;
}

export interface PlanNote {
  version: string;
  body: string;
  updatedAt: string;
}

export interface FeedbackStatus {
  available: boolean;
  submitted: boolean;
  hasFeedback: boolean;
  reason: string | null;
}

export interface DecisionDelivery {
  sent: boolean;
  retryable: boolean;
  reason: string | null;
}

export interface AgentSessionStatus {
  linked: boolean;
  connected: boolean;
  reason: string | null;
}

export interface AppUpdate {
  version: string;
  notes: string | null;
}

export interface AppUpdateProgress {
  downloaded: number;
  total: number | null;
}

export interface ShowworkApi {
  getAppVersion(): Promise<string>;
  getAppRevision(): Promise<string>;
  getRepositoryRevision(): Promise<string>;
  checkAppUpdate(): Promise<AppUpdate | null>;
  closeAppUpdate(): Promise<void>;
  installAppUpdate(onProgress: (progress: AppUpdateProgress) => void): Promise<void>;
  listProjects(): Promise<ProjectSummary[]>;
  listReports(projectId: string): Promise<ReportMeta[]>;
  listRunning(projectId: string): Promise<RunningItem[]>;
  listSessions(projectId: string, runId: string): Promise<SessionItem[]>;
  listAllSessions(projectId: string): Promise<SessionItem[]>;
  deleteSession(projectId: string, sessionId: string): Promise<void>;
  deleteRunning(projectId: string, runId: string): Promise<void>;
  getReport(projectId: string, reportId: string): Promise<ReportDetail>;
  listComments(projectId: string, reportId: string): Promise<ReportComment[]>;
  addComment(projectId: string, reportId: string, version: string, anchor: CommentAnchor, body: string): Promise<ReportComment>;
  deleteComment(projectId: string, reportId: string, version: string, commentId: string): Promise<void>;
  getPlanNote(projectId: string, reportId: string): Promise<PlanNote | null>;
  savePlanNote(projectId: string, reportId: string, version: string, body: string): Promise<PlanNote | null>;
  feedbackStatus(projectId: string, reportId: string): Promise<FeedbackStatus>;
  agentSessionStatus(projectId: string, reportId: string): Promise<AgentSessionStatus>;
  submitFeedback(projectId: string, reportId: string, version: string): Promise<void>;
  submitChoice(projectId: string, reportId: string, version: string, choice: string): Promise<DecisionDelivery>;
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
  let pendingUpdate: Update | null = null;
  return {
    getAppVersion: () => getVersion(),
    getAppRevision: () => invoke('app_revision'),
    async getRepositoryRevision() {
      const response = await fetch('https://api.github.com/repos/cwsbrian/showwork/commits/main', { cache: 'no-store' });
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      const commit: unknown = await response.json();
      const sha = (commit as { sha?: unknown }).sha;
      if (typeof sha !== 'string' || !/^[0-9a-f]{40}$/.test(sha)) throw new Error('GitHub commit is missing');
      return sha;
    },
    async checkAppUpdate() {
      if (pendingUpdate) await pendingUpdate.close();
      pendingUpdate = null;
      pendingUpdate = await check({ timeout: 15000 });
      return pendingUpdate ? { version: pendingUpdate.version, notes: pendingUpdate.body ?? null } : null;
    },
    async closeAppUpdate() {
      if (pendingUpdate) await pendingUpdate.close();
      pendingUpdate = null;
    },
    async installAppUpdate(onProgress) {
      if (!pendingUpdate) throw new Error('Check for an update first');
      let downloaded = 0;
      let total: number | null = null;
      await pendingUpdate.downloadAndInstall((event) => {
        if (event.event === 'Started') {
          total = event.data.contentLength ?? null;
          downloaded = 0;
        } else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength;
        }
        onProgress({ downloaded, total });
      });
      pendingUpdate = null;
      await relaunch();
    },
    listProjects: () => invoke('list_projects'),
    listReports: (projectId) => invoke('list_reports', { projectId }),
    listRunning: (projectId) => invoke('list_running', { projectId }),
    listSessions: (projectId, runId) => invoke('list_sessions', { projectId, runId }),
    listAllSessions: (projectId) => invoke('list_all_sessions', { projectId }),
    deleteSession: (projectId, sessionId) => invoke('delete_session', { projectId, sessionId }),
    deleteRunning: (projectId, runId) => invoke('delete_running', { projectId, runId }),
    getReport: (projectId, reportId) => invoke('get_report', { projectId, reportId }),
    listComments: (projectId, reportId) => invoke('list_comments', { projectId, reportId }),
    addComment: (projectId, reportId, version, anchor, body) =>
      invoke('add_comment', { projectId, reportId, version, anchor, body }),
    deleteComment: (projectId, reportId, version, commentId) =>
      invoke('delete_comment', { projectId, reportId, version, commentId }),
    getPlanNote: (projectId, reportId) => invoke('get_plan_note', { projectId, reportId }),
    savePlanNote: (projectId, reportId, version, body) =>
      invoke('save_plan_note', { projectId, reportId, version, body }),
    feedbackStatus: (projectId, reportId) => invoke('feedback_status', { projectId, reportId }),
    agentSessionStatus: (projectId, reportId) => invoke('agent_session_status', { projectId, reportId }),
    submitFeedback: (projectId, reportId, version) => invoke('submit_feedback', { projectId, reportId, version }),
    submitChoice: (projectId, reportId, version, choice) =>
      invoke<DecisionDelivery>('submit_choice', { projectId, reportId, version, choice }),
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
  appVersion?: string;
  appRevision?: string;
  repositoryRevision?: string;
  availableUpdate?: AppUpdate | null;
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
  const comments: Record<string, ReportComment[]> = {};
  const notes: Record<string, PlanNote> = {};
  const submissions: Record<string, string> = {};
  const disconnectedSessions = new Set<string>();
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
    disconnectedSessions,
    // Set to a string to make the next submitChoice reject with it, as Tauri does.
    failNext: null as string | null,
    // Set a method name to a string to make its next call reject with that string.
    fail: {} as Record<string, string>,
    availableUpdate: fixture.availableUpdate ?? null as AppUpdate | null,
    repositoryRevision: fixture.repositoryRevision ?? fixture.appRevision ?? 'local-revision',
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
    progress(projectId: string, runId: string, text: string) {
      const item = (running[projectId] ?? []).find((r) => r.id === runId);
      if (!item) throw new Error('Run not found');
      item.draftText = (item.draftText ?? '') + text;
      item.revision = (item.revision ?? 0) + 1;
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
    async getAppVersion() { return fixture.appVersion ?? '0.2.0'; },
    async getAppRevision() { return fixture.appRevision ?? 'local-revision'; },
    async getRepositoryRevision() {
      failing('getRepositoryRevision');
      calls.push({ fn: 'getRepositoryRevision' });
      return mock.repositoryRevision;
    },
    async checkAppUpdate() {
      failing('checkAppUpdate');
      calls.push({ fn: 'checkAppUpdate' });
      return mock.availableUpdate;
    },
    async closeAppUpdate() {
      calls.push({ fn: 'closeAppUpdate' });
    },
    async installAppUpdate(onProgress) {
      failing('installAppUpdate');
      if (!mock.availableUpdate) throw new Error('Check for an update first');
      calls.push({ fn: 'installAppUpdate', version: mock.availableUpdate.version });
      onProgress({ downloaded: 50, total: 100 });
      onProgress({ downloaded: 100, total: 100 });
      mock.availableUpdate = null;
    },
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
    async listComments(_projectId, reportId) {
      failing('listComments');
      return [...(comments[reportId] ?? [])];
    },
    async addComment(projectId, reportId, version, anchor, body) {
      failing('addComment');
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta) throw new Error('Report not found');
      if (meta.version !== version) throw new Error('This report was updated; reload it');
      const comment = { id: `comment-${Date.now()}-${(comments[reportId] ?? []).length}`, version, anchor, body: body.trim(), createdAt: new Date().toISOString() };
      (comments[reportId] ??= []).push(comment);
      calls.push({ fn: 'addComment', projectId, reportId, version, anchor, body: body.trim() });
      return comment;
    },
    async deleteComment(projectId, reportId, version, commentId) {
      failing('deleteComment');
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta || meta.version !== version) throw new Error('This report was updated; reload it');
      const index = (comments[reportId] ?? []).findIndex((comment) => comment.id === commentId);
      if (index < 0) throw new Error('Not found');
      comments[reportId].splice(index, 1);
      calls.push({ fn: 'deleteComment', projectId, reportId, version, commentId });
    },
    async getPlanNote(_projectId, reportId) {
      failing('getPlanNote');
      return notes[reportId] ?? null;
    },
    async savePlanNote(projectId, reportId, version, body) {
      failing('savePlanNote');
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta || meta.version !== version) throw new Error('This report was updated; reload it');
      const trimmed = body.trim();
      const note = trimmed ? { version, body: trimmed, updatedAt: new Date().toISOString() } : null;
      if (note) notes[reportId] = note; else delete notes[reportId];
      calls.push({ fn: 'savePlanNote', projectId, reportId, version, body: trimmed });
      return note;
    },
    async feedbackStatus(projectId, reportId) {
      failing('feedbackStatus');
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta?.agentSession || disconnectedSessions.has(reportId)) return { available: false, submitted: false, hasFeedback: !!notes[reportId] || !!comments[reportId]?.length, reason: meta?.agentSession ? 'The original terminal has changed or closed.' : 'This report has no linked agent session.' };
      const snapshot = JSON.stringify([notes[reportId]?.updatedAt ?? null, (comments[reportId] ?? []).map((c) => c.id)]);
      return { available: true, submitted: submissions[reportId] === snapshot, hasFeedback: !!notes[reportId] || !!comments[reportId]?.length, reason: null };
    },
    async agentSessionStatus(_projectId, reportId) {
      const meta = find(reportId);
      const linked = !!meta?.agentSession;
      const connected = linked && !disconnectedSessions.has(reportId);
      return { linked, connected, reason: connected ? null : linked ? 'The original terminal has changed or closed.' : 'This report has no linked agent session.' };
    },
    async submitFeedback(projectId, reportId, version) {
      failing('submitFeedback');
      const meta = (reports[projectId] ?? []).find((r) => r.id === reportId);
      if (!meta?.agentSession || meta.version !== version) throw new Error('Original agent session is unavailable');
      const note = notes[reportId]?.body ?? '';
      const inline = comments[reportId] ?? [];
      if (!note && !inline.length) throw new Error('Add a note or comment first');
      const snapshot = JSON.stringify([notes[reportId]?.updatedAt ?? null, inline.map((c) => c.id)]);
      if (submissions[reportId] === snapshot) throw new Error('Feedback already submitted');
      calls.push({ fn: 'submitFeedback', projectId, reportId, version, note, inline: inline.map((c) => ({ target: c.anchor.target, quote: c.anchor.quote, body: c.body })) });
      submissions[reportId] = snapshot;
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
      return { sent: !!meta?.agentSession, retryable: false, reason: meta?.agentSession ? null : 'This report has no linked agent session.' };
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
