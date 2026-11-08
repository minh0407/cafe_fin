export const LEGACY_APPROVED_SOURCE_SHA: string;
export const PRODUCT_PATHS: readonly string[];
export function approvedSourceSha(explicitSha?: string): string;
export function verifySourceIdentity(repository: string, explicitSha?: string): {
  approved_source_sha: string;
  approval_input: 'legacy_default' | 'explicit_env';
  harness_head: string;
  product_paths: string[];
  product_guard: {
    approved_commit_exists: true;
    approved_is_ancestor: true;
    approved_product_diff_empty: true;
    product_worktree_clean: true;
  };
};
