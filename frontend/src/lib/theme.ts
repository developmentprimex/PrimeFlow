export type Theme = "light" | "dark" | "system"

// Runs before paint, independently of React hydration and authentication.
export const THEME_SCRIPT = `(() => {
  const root = document.documentElement;
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const valid = value => ['light', 'dark', 'system'].includes(value) ? value : 'system';
  const read = () => { try { return valid(localStorage.getItem('primex-theme')); } catch { return 'system'; } };
  let theme = read();
  const apply = () => {
    const dark = theme === 'dark' || (theme === 'system' && media.matches);
    root.classList.toggle('dark', dark);
    root.dataset.theme = theme;
    root.dataset.resolvedTheme = dark ? 'dark' : 'light';
    window.dispatchEvent(new Event('primex:theme-change'));
  };
  window.addEventListener('primex:set-theme', event => {
    theme = valid(event.detail);
    try { localStorage.setItem('primex-theme', theme); } catch {}
    apply();
  });
  media.addEventListener('change', apply);
  window.addEventListener('storage', event => {
    if (event.key === 'primex-theme' || event.key === null) { theme = read(); apply(); }
  });
  apply();
})();`
