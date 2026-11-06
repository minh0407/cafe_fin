// Register once when the feature is imported, before the shell installs its hash
// listener. Window-target hashchange listeners otherwise run in registration order
// even with capture=true, allowing the shell to unmount a dirty grid first.
const guards = new Set<() => boolean>();
if (typeof window !== 'undefined') {
  let acceptedHash = location.hash;
  window.addEventListener('hashchange', event => {
    if (location.hash === acceptedHash) return;
    if ([...guards].some(dirty => dirty()) && !window.confirm('Còn bản nháp chưa lưu. Bỏ bản nháp và rời trang?')) {
      history.replaceState(null, '', `${location.pathname}${location.search}${acceptedHash}`);
      event.stopImmediatePropagation();
    } else acceptedHash = location.hash;
  }, true);
  window.addEventListener('beforeunload', event => {
    if ([...guards].some(dirty => dirty())) { event.preventDefault(); event.returnValue = ''; }
  });
}
export function registerDraftGuard(dirty: () => boolean) {
  guards.add(dirty);
  return () => { guards.delete(dirty); };
}
