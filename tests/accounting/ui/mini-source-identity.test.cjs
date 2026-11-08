'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { LEGACY_APPROVED_SOURCE_SHA, PRODUCT_PATHS, approvedSourceSha, verifySourceIdentity } = require('./mini-source-identity.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cafe-fin-ui-identity-'));
  const git = args => execFileSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const write = (filename, value) => { const full = path.join(root, filename); fs.mkdirSync(path.dirname(full), { recursive: true }); fs.writeFileSync(full, value); };
  git(['init', '--quiet']); git(['config', 'user.name', 'Synthetic UI Identity']); git(['config', 'user.email', 'ui-identity@example.invalid']); git(['config', 'core.autocrlf', 'false']);
  write('backend/runtime.py', 'approved product A\n');
  write('frontend/src/main.ts', 'approved UI A\n');
  write('desktop/Cargo.toml', '[package]\nname="synthetic"\n');
  write('pyproject.toml', '[project]\nname="synthetic-a"\n');
  git(['add', '.']); git(['commit', '--quiet', '-m', 'Synthetic product A']);
  const sourceA = git(['rev-parse', 'HEAD']);
  t.after(() => {
    const resolved = path.resolve(root);
    assert.equal(path.dirname(resolved).toLowerCase(), path.resolve(os.tmpdir()).toLowerCase());
    assert.ok(path.basename(resolved).startsWith('cafe-fin-ui-identity-'));
    fs.rmSync(resolved, { recursive: true, force: true });
  });
  return { root, git, write, sourceA, commit(message) { git(['add', '.']); git(['commit', '--quiet', '-m', message]); return git(['rev-parse', 'HEAD']); } };
}

test('only an absent approval uses the fixed legacy source; malformed or symbolic values never mean HEAD', () => {
  assert.equal(approvedSourceSha(undefined), LEGACY_APPROVED_SOURCE_SHA);
  for (const value of ['', 'HEAD', 'f1bfc4f', 'a'.repeat(39), 'a'.repeat(41), 'g'.repeat(40), ` ${'a'.repeat(40)}`]) assert.throws(() => approvedSourceSha(value), { code: 'APPROVED_SOURCE_MALFORMED' });
  assert.equal(approvedSourceSha('A'.repeat(40)), 'a'.repeat(40));
});

test('unknown approval and default legacy absent from a temporary repository reject instead of selecting its HEAD', t => {
  const repo = fixture(t);
  assert.throws(() => verifySourceIdentity(repo.root, 'f'.repeat(40)), { code: 'APPROVED_SOURCE_UNKNOWN' });
  assert.throws(() => verifySourceIdentity(repo.root), { code: 'APPROVED_SOURCE_UNKNOWN' });
});

test('a full SHA naming a blob is not an approved commit', t => {
  const repo = fixture(t); const blob = repo.git(['rev-parse', 'HEAD:backend/runtime.py']);
  assert.throws(() => verifySourceIdentity(repo.root, blob), { code: 'APPROVED_SOURCE_NOT_COMMIT' });
});

test('a known unrelated commit is rejected without switching any checkout', t => {
  const repo = fixture(t); const tree = repo.git(['rev-parse', 'HEAD^{tree}']);
  const unrelated = repo.git(['commit-tree', tree, '-m', 'Unrelated synthetic source']);
  assert.throws(() => verifySourceIdentity(repo.root, unrelated), { code: 'APPROVED_SOURCE_NOT_ANCESTOR' });
});

test('tests/docs-only descendants retain approved source identity and record their separate harness HEAD', t => {
  const repo = fixture(t); repo.write('tests/new-test.txt', 'test harness\n'); repo.write('docs/handoff.md', 'source evidence\n');
  const harnessHead = repo.commit('Synthetic harness only'); const identity = verifySourceIdentity(repo.root, repo.sourceA);
  assert.equal(identity.approved_source_sha, repo.sourceA); assert.equal(identity.harness_head, harnessHead); assert.notEqual(harnessHead, repo.sourceA); assert.equal(identity.approval_input, 'explicit_env');
  repo.write('tests/uncommitted-test.txt', 'allowed test draft\n'); repo.write('docs/handoff.md', 'allowed documentation draft\n');
  assert.equal(verifySourceIdentity(repo.root, repo.sourceA).harness_head, harnessHead);
});

test('a different actual product requires its own explicit approved source, not the historical source', t => {
  const repo = fixture(t); repo.write('backend/runtime.py', 'different approved product B\n'); repo.write('pyproject.toml', '[project]\nname="synthetic-b"\n');
  const sourceB = repo.commit('Synthetic different product B');
  assert.throws(() => verifySourceIdentity(repo.root, repo.sourceA), { code: 'APPROVED_SOURCE_PRODUCT_MISMATCH' });
  repo.write('tests/source-b-test.txt', 'B harness\n'); const harnessHead = repo.commit('Synthetic B harness');
  const identity = verifySourceIdentity(repo.root, sourceB);
  assert.equal(identity.approved_source_sha, sourceB); assert.equal(identity.harness_head, harnessHead); assert.ok(Object.values(identity.product_guard).every(Boolean));
});

for (const filename of PRODUCT_PATHS.filter(value => !['backend', 'frontend/src', 'desktop'].includes(value))) test(`runtime input ${filename} is guarded`, t => {
  const repo = fixture(t); repo.write(filename, 'changed runtime input\n');
  assert.throws(() => verifySourceIdentity(repo.root, repo.sourceA), { code: 'PRODUCT_WORKTREE_DIRTY' });
  repo.commit('Synthetic changed runtime input');
  assert.throws(() => verifySourceIdentity(repo.root, repo.sourceA), { code: 'APPROVED_SOURCE_PRODUCT_MISMATCH' });
});

test('an untracked frontend source cannot bypass the clean-product guard', t => {
  const repo = fixture(t); repo.write('frontend/src/untracked.ts', 'uncommitted product\n');
  assert.throws(() => verifySourceIdentity(repo.root, repo.sourceA), { code: 'PRODUCT_WORKTREE_DIRTY' });
});

test('staged product changes hidden by restoring the working file still reject', t => {
  const repo = fixture(t); repo.write('backend/runtime.py', 'staged different product\n'); repo.git(['add', 'backend/runtime.py']); repo.write('backend/runtime.py', 'approved product A\n');
  assert.equal(repo.git(['diff', '--name-only', repo.sourceA, '--', 'backend']), '');
  assert.throws(() => verifySourceIdentity(repo.root, repo.sourceA), { code: 'PRODUCT_WORKTREE_DIRTY' });
});
