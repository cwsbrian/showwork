import '@report-view.css';
import './styles.css';
import { createApi, ProjectSummary, ReportMeta, ReportRef, RunningItem, SessionItem, View } from './api';
import { createProjects } from './views/projects';
import { createMiddle } from './views/middle';
import { createReportPane } from './views/reportPane';
import { createTabs } from './views/tabs';
import { createScreen } from './views/sessionView';
import { createIosScreen } from './views/iosSessionView';
import { sessionLabel } from './views/tabs';

const api = createApi();
const $ = (id: string) => document.getElementById(id) as HTMLElement;

// Selection lives only here. Views receive it and report changes.
let projectId: string | null = null;
let reportId: string | null = null;
let runId: string | null = null;
let sessions: SessionItem[] = [];
let sessionToken = 0;
let view: View = 'list';
let projects: ProjectSummary[] = [];
let reports: ReportMeta[] = [];
let running: RunningItem[] = [];
let stopped: RunningItem[] = [];
let loadingReports = false;
// Only the newest list request may write `reports`; older answers are dropped.
let listToken = 0;

// A small non-blocking line for failed actions. It hides itself after a while or on click.
const errorLine = $('error-line');
let errorTimer: ReturnType<typeof setTimeout> | undefined;
errorLine.onclick = () => (errorLine.hidden = true);
function showError(what: string, e: unknown) {
  errorLine.textContent = what + ': ' + (e instanceof Error ? e.message : String(e));
  errorLine.hidden = false;
  clearTimeout(errorTimer);
  errorTimer = setTimeout(() => (errorLine.hidden = true), 8000);
}
const run = (what: string, task: () => Promise<unknown>) => void task().catch((e) => showError(what, e));

const pane = createReportPane($('report'), api, (id) => {
  // The list item drops "Needs your choice" now; the refresh confirms it from the store.
  reports = reports.map((r) => (r.id === id ? { ...r, chosen: true } : r));
  drawMiddle();
  run('Could not refresh the reports', refreshReports);
});
const tabs = createTabs($('tabs'), {
  reportHost: $('report'),
  screen: (s, interactive) => s.kind === 'ios-simulator' ? createIosScreen(s, interactive) : createScreen(s, interactive),
  closeSession: (id) => run('Could not close the session', async () => {
    if (!projectId) return;
    await api.deleteSession(projectId, id);
    await refreshReports();
  }),
});
const projectsView = createProjects($('projects'), {
  select: (id) => run('Could not open the project', () => selectProject(id)),
  reveal: (id) => run('Could not reveal the project', () => api.revealProject(id)),
  remove: (id) => run('Could not delete the history', () => removeProject(id)),
});
const middle = createMiddle($('middle'), {
  select: (id) => run('Could not open the report', () => selectReport(id)),
  selectRun: (id) => run('Could not open the task', () => selectRun(id)),
  setView: (v) => {
    view = v;
    drawMiddle();
    run('Could not save the view', () => api.setView(v));
  },
  remove: (id) => run('Could not delete the report', () => removeReport(id)),
  removeRunning: (id) => run('Could not remove the item', () => removeRunning(id)),
});

function drawProjects() {
  projectsView.render(projects, projectId);
}
function drawMiddle() {
  middle.render(projectId, reports, view, reportId, loadingReports, [...running, ...stopped], runId);
}
function taskContext() {
  if (runId) {
    const active = running.some((r) => r.id === runId);
    return { key: runId, running: active, stopped: !active };
  }
  if (reportId) {
    const meta = reports.find((r) => r.id === reportId);
    return { key: meta?.run || 'report:' + reportId, running: false };
  }
  return null;
}
function drawTabs() { tabs.render(taskContext(), sessions); }
async function refreshSessions(onlyIfChanged = false) {
  const pid = projectId;
  const ctx = taskContext();
  const mine = ++sessionToken;
  if (!pid || !ctx) { sessions = []; drawTabs(); return; }
  const found = ctx.key.startsWith('report:') ? [] : await api.listSessions(pid, ctx.key);
  if (mine !== sessionToken || pid !== projectId || ctx.key !== taskContext()?.key) return;
  if (!onlyIfChanged || JSON.stringify(found) !== JSON.stringify(sessions)) {
    sessions = found;
    drawTabs();
  }
}

setInterval(() => {
  if (projectId && sessions.some((s) => s.alive)) {
    void refreshSessions(true).catch((e) => showError('Could not refresh sessions', e));
  }
}, 2000);
async function refreshProjects() {
  projects = await api.listProjects();
  drawProjects();
}
async function refreshReports() {
  const pid = projectId;
  const mine = ++listToken;
  try {
    const [list, working, stored] = pid ? await Promise.all([api.listReports(pid), api.listRunning(pid), api.listAllSessions(pid)]) : [[], [], []];
    if (mine !== listToken) return;
    reports = list;
    running = working;
    const activeRuns = new Set(working.map((r) => r.id));
    const reportedRuns = new Set(list.map((r) => r.run).filter(Boolean));
    const groups = new Map<string, SessionItem[]>();
    for (const session of stored) {
      if (activeRuns.has(session.run) || reportedRuns.has(session.run)) continue;
      const group = groups.get(session.run) ?? [];
      group.push(session);
      groups.set(session.run, group);
    }
    stopped = [...groups].map(([id, group]) => ({
      id, projectId: pid!, type: 'browser', title: sessionLabel(group[0]),
      branch: null, worktree: '', agent: 'unknown', startedAt: group[0].startedAt, ended: true,
    }));
    if (runId && !working.some((r) => r.id === runId)) {
      const published = list.find((r) => r.run === runId);
      if (published) {
        runId = null;
        reportId = published.id;
        void selectReport(published.id).catch((e) => showError('Could not open the report', e));
      } else if (!stopped.some((r) => r.id === runId)) {
        runId = null;
        pane.clear();
      }
    }
  } finally {
    if (mine === listToken) {
      loadingReports = false;
      drawMiddle();
      void refreshSessions().catch((e) => showError('Could not refresh sessions', e));
    }
  }
}

// Switch the selected project at once: the old project's list and report go away before anything loads.
function setProject(id: string | null) {
  if (id === projectId) return;
  projectId = id;
  reportId = null;
  runId = null;
  sessions = [];
  ++sessionToken;
  reports = [];
  running = [];
  stopped = [];
  loadingReports = id !== null;
  ++listToken;
  pane.clear();
  drawProjects();
  drawMiddle();
  drawTabs();
}

async function selectRun(id: string) {
  if (!projectId) return;
  runId = id;
  reportId = null;
  pane.clear();
  sessions = [];
  drawMiddle();
  drawTabs();
  await refreshSessions();
}

async function selectProject(id: string) {
  if (id === projectId) return;
  setProject(id);
  await refreshReports();
}

async function selectReport(id: string) {
  const pid = projectId;
  if (!pid) return;
  reportId = id;
  runId = null;
  drawMiddle();
  await refreshSessions();
  // Mark read only when this report was actually shown and is still the selection.
  if (!(await pane.show(pid, id)) || pid !== projectId || reportId !== id) return;
  try {
    await api.markRead(id);
  } catch (e) {
    showError('Could not mark the report as read', e);
    return;
  }
  if (pid === projectId) {
    reports = reports.map((r) => (r.id === id ? { ...r, read: true } : r));
    drawMiddle();
  }
  await refreshProjects();
}

async function removeReport(id: string) {
  const pid = projectId;
  if (!pid) return;
  await api.deleteReport(pid, id);
  if (pid === projectId && id === reportId) {
    reportId = null;
    pane.clear();
    sessions = [];
    drawTabs();
  }
  await refreshReports();
  await refreshProjects();
}

async function removeRunning(id: string) {
  const pid = projectId;
  if (!pid) return;
  await api.deleteRunning(pid, id);
  await refreshReports();
  await refreshProjects();
}

async function removeProject(id: string) {
  await api.deleteProject(id);
  if (id === projectId) setProject(null);
  await refreshProjects();
}

// The external path that changes the selection: an open-report event (also one that arrives during startup).
async function openReport(p: ReportRef) {
  setProject(p.projectId);
  reportId = p.reportId;
  runId = null;
  drawMiddle();
  await refreshProjects();
  await refreshReports();
  if (projectId === p.projectId && reportId === p.reportId) await selectReport(p.reportId);
}

// Arrivals only refresh lists and badges; they never touch the selection or the right pane.
api.onArrival(() =>
  run('Could not refresh the reports', async () => {
    await refreshProjects();
    if (projectId) await refreshReports();
  }),
);
api.onRunningChanged(() =>
  run('Could not refresh the reports', async () => {
    await refreshProjects();
    if (projectId) await refreshReports();
  }),
);
api.onOpenReport((p) => run('Could not open the report', () => openReport(p)));

run('Could not load Showwork', async () => {
  try {
    view = (await api.getState()).view;
  } catch (e) {
    showError('Could not load the saved view', e);
  }
  drawMiddle();
  await refreshProjects();
  // An open-report event that arrived meanwhile wins over the default selection.
  if (projectId === null && projects.length) {
    setProject(projects[0].id);
    await refreshReports();
  }
});
