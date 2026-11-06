import test from 'node:test';
import assert from 'node:assert/strict';
import { filterReports, branchGroups, typeLabel } from '../src/model.ts';

const r = (id: string, branch: string | null, type: string, createdAt: string) =>
  ({ id, projectId: 'p', type, mode: 'handoff', title: id, branch, commit: null, worktree: '/w', agent: 'a', createdAt, version: 'v', open: false, chosen: false });

const reports = [
  r('c', 'main', 'result', '2026-01-03T00:00:00Z'),
  r('b', 'feat', 'review', '2026-01-02T00:00:00Z'),
  r('a', 'feat', 'plan', '2026-01-01T00:00:00Z'),
  r('0', null, 'plan', '2026-01-00T00:00:00Z'),
];

test('filter by branch and type', () => {
  assert.deepEqual(filterReports(reports, { branch: 'feat' }).map((x) => x.id), ['b', 'a']);
  assert.deepEqual(filterReports(reports, { type: 'plan' }).map((x) => x.id), ['a', '0']);
  assert.deepEqual(filterReports(reports, { branch: 'feat', type: 'plan' }).map((x) => x.id), ['a']);
  assert.equal(filterReports(reports, {}).length, 4);
  assert.equal(typeLabel('adversarial-review'), 'Adversarial review');
  assert.equal(typeLabel('plan'), 'Plan');
});

test('flow groups newest branch first, items oldest→newest', () => {
  const g = branchGroups(reports);
  assert.deepEqual(g.map((x) => x.branch), ['main', 'feat', '(no branch)']);
  assert.deepEqual(g[1].reports.map((x) => x.id), ['a', 'b']);
  assert.equal(g[1].latest, '2026-01-02T00:00:00Z');
});

test('null branch grouped as (no branch)', () => {
  const g = branchGroups([r('x', null, 'plan', '2026-01-01T00:00:00Z')]);
  assert.equal(g[0].branch, '(no branch)');
});

test('same-second reports keep publish order by id', () => {
  const sec = '2026-01-05T10:00:00Z';
  const g = branchGroups([
    r('20260105-100000-900000-aaaa', 'main', 'result', sec),
    r('20260105-100000-100000-ffff', 'main', 'plan', sec),
    r('20260105-100000-500000-0000', 'main', 'review', sec),
  ]);
  assert.deepEqual(g[0].reports.map((x) => x.type), ['plan', 'review', 'result']);
});

test('newest branch by id when latest times tie', () => {
  const sec = '2026-01-05T10:00:00Z';
  const g = branchGroups([
    r('20260105-100000-200000-aaaa', 'later', 'plan', sec),
    r('20260105-100000-100000-aaaa', 'earlier', 'plan', sec),
  ]);
  assert.deepEqual(g.map((x) => x.branch), ['later', 'earlier']);
});
