// Apply before styles paint, then attach the same accessible switch on every page.
(() => {
    'use strict';
    const key = 'sansad-ai-theme';
    const root = document.documentElement;
    const system = window.matchMedia('(prefers-color-scheme: dark)');
    let choice = null;
    let button;
    try {
        const saved = localStorage.getItem(key);
        if (saved === 'dark' || saved === 'light') choice = saved;
    } catch (_) { /* Theme switching still works when browser storage is blocked. */ }

    function apply(theme) {
        root.dataset.theme = theme;
        if (button) {
            button.setAttribute('aria-checked', String(theme === 'dark'));
            button.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
        }
    }
    apply(choice || 'dark');

    function mount() {
        const header = document.querySelector('.header');
        if (!header) return;
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'theme-toggle';
        button.setAttribute('role', 'switch');
        button.setAttribute('aria-label', 'Dark mode');
        button.innerHTML = '<span class="theme-toggle-label">Dark mode</span><span class="theme-toggle-track" aria-hidden="true"><span class="theme-toggle-thumb"></span></span>';
        button.addEventListener('click', () => {
            choice = root.dataset.theme === 'dark' ? 'light' : 'dark';
            apply(choice);
            try { localStorage.setItem(key, choice); } catch (_) { /* Session-only fallback. */ }
        });
        header.appendChild(button);
        apply(root.dataset.theme);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
    else mount();

    system.addEventListener('change', event => {
        if (!choice) apply(event.matches ? 'dark' : 'light');
    });
    window.addEventListener('storage', event => {
        if (event.key !== key && event.key !== null) return;
        choice = event.key === key && ['dark', 'light'].includes(event.newValue) ? event.newValue : null;
        apply(choice || 'dark');
    });
})();
