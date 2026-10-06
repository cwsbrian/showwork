'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { cpSync, mkdtempSync, mkdirSync, readFileSync, writeFileSync, existsSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const { test } = require('node:test');
const { pathToFileURL } = require('node:url');

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
    assert.match(ok(run('npm', [...args, '--target', project])), /installed\/updated 4/);
    const instructions = readFileSync(join(project, 'AGENTS.md'), 'utf8');
    assert.ok(instructions.startsWith('Keep my instructions.\n'));
    for (const file of ['scripts/companion.py', 'assets/companion.html', 'references/companion.md']) {
      assert.ok(existsSync(join(project, '.agents/skills/showwork', file)), file);
    }
    assert.match(ok(run('npm', [...args, 'install', '--target', project], { cwd: temporary })), /installed\/updated 0/);
    assert.equal(existsSync(join(temporary, 'AGENTS.md')), false);
    assert.equal(readFileSync(join(project, 'AGENTS.md'), 'utf8'), instructions);
    const skill = join(project, '.agents/skills/showwork/SKILL.md');
    writeFileSync(skill, 'User customization');
    const update = ok(run('npm', [...args, '--target', project]));
    const backup = update.match(/backed up in: (.+)/)[1].trim();
    assert.equal(readFileSync(join(backup, 'showwork/SKILL.md'), 'utf8'), 'User customization');
    assert.equal(readFileSync(skill, 'utf8'), readFileSync(join(root, 'skills/showwork/SKILL.md'), 'utf8'));
    assert.equal(readFileSync(join(project, 'AGENTS.md'), 'utf8'), instructions);
    const cli = join(root, 'scripts/cli.cjs');
    const noPython = { env: { ...process.env, PATH: temporary } };
    assert.match(ok(run(process.execPath, [cli, '--help'], noPython)), /Usage:/);
    const missing = run(process.execPath, [cli], noPython);
    assert.equal(missing.status, 1);
    assert.match(missing.stderr, /Python 3\.11\+ is required/);
    assert.equal(run(process.execPath, [cli, '--typo']).status, 1);
    assert.equal(run(process.execPath, [cli, 'unknown']).status, 1);
    assert.equal(run(process.execPath, [cli, '--user', '--target', project]).status, 1);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});

test('the same npx command and cache pick up a new Git commit and update installed skills', () => {
  const root = resolve(__dirname, '..');
  const temporary = mkdtempSync(join(tmpdir(), 'showwork-update-'));
  const repository = join(temporary, 'repository');
  const project = join(temporary, 'project');
  mkdirSync(repository);
  mkdirSync(project);
  const run = (command, args, cwd) => {
    const result = spawnSync(command, args, { cwd, encoding: 'utf8', timeout: 60000 });
    assert.equal(result.status, 0, result.stderr || result.error?.message);
    return result.stdout;
  };
  try {
    for (const name of ['scripts', 'instructions', 'skills', 'package.json']) {
      cpSync(join(root, name), join(repository, name), { recursive: true });
    }
    const skill = join(repository, 'skills/showwork/SKILL.md');
    const retired = join(repository, 'skills/showwork/retired.md');
    writeFileSync(skill, 'First release');
    writeFileSync(retired, 'Removed in next release');
    run('git', ['init', '--initial-branch=main'], repository);
    const commit = () => {
      run('git', ['add', '.'], repository);
      run('git', ['-c', 'user.name=Showwork test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Test release'], repository);
    };
    commit();
    const args = ['--yes', '--cache', join(temporary, 'npm-cache'),
      `git+${pathToFileURL(repository).href}#main`, '--target', project];
    assert.match(run('npx', args, project), /installed\/updated 4/);
    const installed = join(project, '.agents/skills/showwork');
    assert.equal(readFileSync(join(installed, 'SKILL.md'), 'utf8'), 'First release');
    writeFileSync(skill, 'Second release');
    rmSync(retired);
    // Keep package.version unchanged: Git commit freshness must decide this.
    commit();
    const updated = run('npx', args, project);
    assert.match(updated, /installed\/updated 1/);
    assert.equal(readFileSync(join(installed, 'SKILL.md'), 'utf8'), 'Second release');
    assert.equal(existsSync(join(installed, 'retired.md')), false);
    const backup = updated.match(/backed up in: (.+)/)[1].trim();
    assert.equal(readFileSync(join(backup, 'showwork/SKILL.md'), 'utf8'), 'First release');
    assert.match(run('npx', args, project), /installed\/updated 0/);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
