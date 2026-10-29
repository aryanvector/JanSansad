/* A one-use handoff skips the intro only for a normal section-link click. */
(() => {
  const key = 'jansansad-section-navigation';
  const sections = new Set(['/', '/bills', '/ministers']);
  window.janSansadInternalNavigation = false;
  try {
    const pending = JSON.parse(sessionStorage.getItem(key) || 'null');
    sessionStorage.removeItem(key);
    const navigation = performance.getEntriesByType('navigation')[0];
    window.janSansadInternalNavigation = navigation?.type === 'navigate' &&
      pending?.path === location.pathname && Date.now() - pending.at < 15000;
  } catch (_) { /* Blocked storage leaves the original intro available. */ }
  document.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href]');
    if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const destination = new URL(link.href, location.href);
    if (destination.origin !== location.origin || !sections.has(destination.pathname) || destination.pathname === location.pathname) return;
    try { sessionStorage.setItem(key, JSON.stringify({path:destination.pathname, at:Date.now()})); } catch (_) {}
  });
})();
