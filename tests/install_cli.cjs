'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { test } = require('node:test');

test('packed CLI installs from npx cache and preserves project changes', () => {
  const root = resolve(__dirname, '..');
  const temporary = mkdtempSync(join(tmpdir(), 'showwork-npx-'));
  const project = join(temporary, 'project with spaces');
  mkdirSync(project);
  const run = (command, args, options = {}) => spawnSync(command, args, {
    cwd: project, encoding: 'utf8', timeout: 60000, ...options,
  });
  const ok = result => {
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    return result.stdout;
  };
  try {
    const [packed] = JSON.parse(ok(run('npm', ['pack', '--json', '--pack-destination', temporary], { cwd: root })));
    assert.ok(packed.files.every(({ path }) => !/(__pycache__|\.pyc$|\.showwork\/|node_modules\/)/.test(path)));
    const args = ['exec', '--yes', '--offline', '--package', join(temporary, packed.filename), '--', 'showwork'];
    writeFileSync(join(project, 'AGENTS.md'), 'Keep my instructions.\n');
    assert.match(ok(run('npm', args)), /Copied 4/);
    const instructions = readFileSync(join(project, 'AGENTS.md'), 'utf8');
    assert.ok(instructions.startsWith('Keep my instructions.\n'));
    for (const file of ['scripts/companion.py', 'assets/companion.html', 'references/companion.md']) {
      assert.ok(existsSync(join(project, '.agents/skills/showwork', file)), file);
    }
    assert.match(ok(run('npm', [...args, 'install', '--target', project], { cwd: temporary })), /Copied 0/);
    assert.equal(existsSync(join(temporary, 'AGENTS.md')), false);
    assert.equal(readFileSync(join(project, 'AGENTS.md'), 'utf8'), instructions);
    const skill = join(project, '.agents/skills/showwork/SKILL.md');
    writeFileSync(skill, 'User customization');
    assert.equal(run('npm', args).status, 1);
    assert.equal(readFileSync(skill, 'utf8'), 'User customization');
    assert.equal(readFileSync(join(project, 'AGENTS.md'), 'utf8'), instructions);
    const cli = join(root, 'scripts/cli.cjs');
    const noPython = { env: { ...process.env, PATH: temporary } };
    assert.match(ok(run(process.execPath, [cli, '--help'], noPython)), /Usage:/);
    const missing = run(process.execPath, [cli], noPython);
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /Python 3\.11\+ is required/);
    assert.equal(run(process.execPath, [cli, '--typo']).status, 1);
    assert.equal(run(process.execPath, [cli, 'unknown']).status, 1);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
