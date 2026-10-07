#!/usr/bin/env node
'use strict';

const { spawnSync } = require('node:child_process');
const { join } = require('node:path');
const { parseArgs } = require('node:util');

try {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      target: { type: 'string' },
      user: { type: 'boolean' },
      runtime: { type: 'string', default: 'both' },
      help: { type: 'boolean', short: 'h' },
      version: { type: 'boolean', short: 'v' },
    },
  });
  if (positionals.length > 1 || (positionals.length && positionals[0] !== 'install')) {
    throw new Error('Expected: showwork [install] [--user | --target <project>]');
  }
  if (values.user && values.target !== undefined) throw new Error('Use either --user or --target, not both.');
  if (!['both', 'codex', 'claude'].includes(values.runtime)) throw new Error('--runtime must be both, codex, or claude.');
  if (values.help) {
    console.log('Usage: showwork [install] [--user | --target <project>] [--runtime both|codex|claude]\n\nInstalls/updates both Codex and Claude Code for the current user by default.\nCodex: ~/.agents/skills + $CODEX_HOME/AGENTS.md (default ~/.codex).\nClaude: ~/.claude/skills + ~/.claude/CLAUDE.md (respects CLAUDE_CONFIG_DIR).\nUse --target for a project-only install. Requires Python 3.11+.\nChanged skills, including local edits, are backed up before replacement.\nRerun npx --yes github:cwsbrian/showwork to update from GitHub.');
  } else if (values.version) {
    console.log(require('../package.json').version);
  } else {
    const candidates = process.platform === 'win32'
      ? [['py', '-3'], ['python3'], ['python']]
      : [['python3'], ['python']];
    const python = candidates.find(([command, ...prefix]) => spawnSync(command, [
      ...prefix, '-c', 'import sys; sys.exit(sys.version_info < (3, 11))',
    ], { stdio: 'ignore', timeout: 5000 }).status === 0);
    if (!python) throw new Error('Python 3.11+ is required. Install it, add it to PATH, and rerun this command.');
    const [command, ...prefix] = python;
    const result = spawnSync(command, [
      ...prefix, join(__dirname, 'install_codex.py'),
      ...(values.target === undefined ? ['--user'] : ['--target', values.target]),
      '--runtime', values.runtime,
    ], { stdio: 'inherit' });
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
  }
} catch (error) {
  console.error(`showwork: ${error.message}`);
  process.exitCode = 1;
}
