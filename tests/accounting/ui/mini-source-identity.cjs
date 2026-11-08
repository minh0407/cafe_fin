'use strict';

const { execFileSync } = require('node:child_process');

const LEGACY_APPROVED_SOURCE_SHA = 'eab8c96b851f039de515083189f4301cc09437c0';
const PRODUCT_PATHS = Object.freeze([
  'backend', 'frontend/src', 'desktop',
  'pyproject.toml', 'uv.lock',
  'frontend/package.json', 'frontend/package-lock.json',
  'frontend/tsconfig.json', 'frontend/vite.config.ts', 'frontend/index.html',
  'Dockerfile', 'compose.preview.yaml',
]);

function reject(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function approvedSourceSha(explicitSha) {
  const value = explicitSha === undefined ? LEGACY_APPROVED_SOURCE_SHA : explicitSha;
  if (typeof value !== 'string' || !/^[0-9a-fA-F]{40}$/.test(value)) {
    reject('APPROVED_SOURCE_MALFORMED', 'Approved source must be an explicit full40hex SHA; only an absent setting uses the legacy baseline.');
  }
  return value.toLowerCase();
}

function verifySourceIdentity(repository, explicitSha) {
  const approved = approvedSourceSha(explicitSha);
  const git = args => execFileSync('git', args, {
    cwd: repository, encoding: 'utf8', windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
  let objectType;
  try { objectType = git(['cat-file', '-t', approved]); }
  catch { reject('APPROVED_SOURCE_UNKNOWN', 'Approved source commit does not exist in this repository.'); }
  if (objectType !== 'commit') reject('APPROVED_SOURCE_NOT_COMMIT', 'Approved source must identify a commit, not another Git object.');
  const harnessHead = git(['rev-parse', '--verify', 'HEAD']);
  try { git(['merge-base', '--is-ancestor', approved, harnessHead]); }
  catch { reject('APPROVED_SOURCE_NOT_ANCESTOR', 'Approved source must be an ancestor of the actual harness HEAD.'); }
  if (git(['status', '--porcelain=v1', '--untracked-files=all', '--', ...PRODUCT_PATHS])) {
    reject('PRODUCT_WORKTREE_DIRTY', 'Guarded source/runtime paths contain staged, unstaged or untracked changes.');
  }
  if (git(['diff', '--no-ext-diff', '--name-only', approved, '--', ...PRODUCT_PATHS])) {
    reject('APPROVED_SOURCE_PRODUCT_MISMATCH', 'Actual source/runtime paths differ from the approved commit.');
  }
  return {
    approved_source_sha: approved,
    approval_input: explicitSha === undefined ? 'legacy_default' : 'explicit_env',
    harness_head: harnessHead,
    product_paths: [...PRODUCT_PATHS],
    product_guard: {
      approved_commit_exists: true,
      approved_is_ancestor: true,
      approved_product_diff_empty: true,
      product_worktree_clean: true,
    },
  };
}

module.exports = { LEGACY_APPROVED_SOURCE_SHA, PRODUCT_PATHS, approvedSourceSha, verifySourceIdentity };
