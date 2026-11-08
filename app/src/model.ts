export interface ReportMeta {
  id: string;
  projectId: string;
  type: string;
  mode: string;
  title: string;
  branch: string | null;
  commit: string | null;
  worktree: string;
  agent: string;
  createdAt: string;
  version: string;
  run?: string | null;
  open: boolean;
  chosen: boolean;
  read?: boolean;
}

interface SessionCommon {
  id: string;
  projectId: string;
  run: string;
  title: string | null;
  width: number;
  height: number;
  port: number;
  pid: number;
  startedAt: string;
  endedAt: string | null;
  alive: boolean;
}

export interface BrowserSession extends SessionCommon {
  kind: 'browser';
  url: string;
  ws: string;
}
export interface IosSession extends SessionCommon {
  kind: 'ios-simulator';
  udid: string;
  pointsWidth: number;
  pointsHeight: number;
  token: string;
}
export interface AndroidSession extends SessionCommon {
  kind: 'android-emulator';
  serial: string;
  token: string;
}
export type SessionItem = BrowserSession | IosSession | AndroidSession;

/** A report an agent has started but not published yet. */
export interface RunningItem {
  id: string;
  projectId: string;
  type: string;
  title: string | null;
  branch: string | null;
  worktree: string;
  agent: string;
  startedAt: string;
  ended?: boolean;
}

export interface BranchGroup {
  branch: string;
  latest: string;
  reports: ReportMeta[];
}

export const NO_BRANCH = '(no branch)';

// Report ids are sortable timestamps with sub-second precision; createdAt has whole seconds.
const byId = (a: ReportMeta, b: ReportMeta) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

export function filterReports(reports: ReportMeta[], f: { branch?: string; type?: string }): ReportMeta[] {
  return reports.filter(
    (r) => (!f.branch || (r.branch ?? NO_BRANCH) === f.branch) && (!f.type || r.type === f.type),
  );
}

export function branchGroups(reports: ReportMeta[]): BranchGroup[] {
  const map = new Map<string, ReportMeta[]>();
  for (const r of reports) {
    const key = r.branch ?? NO_BRANCH;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(r);
  }
  const groups: BranchGroup[] = [];
  for (const [branch, items] of map) {
    items.sort(byId);
    groups.push({ branch, latest: items[items.length - 1].createdAt, reports: items });
  }
  groups.sort((a, b) => byId(b.reports[b.reports.length - 1], a.reports[a.reports.length - 1]));
  return groups;
}

const LABELS: Record<string, string> = {
  plan: 'Plan',
  review: 'Review',
  verify: 'Verify',
  result: 'Result',
  'adversarial-review': 'Adversarial review',
};

export function typeLabel(type: string): string {
  return LABELS[type] ?? type;
}
