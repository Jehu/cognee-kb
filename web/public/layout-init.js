// Layout-Init (läuft auf jeder Seite): Service Worker registrieren + dezenter
// Token-Hinweis. Liegt unter public/ und wird same-origin als externe Datei
// ausgeliefert (per <script is:inline src>) — nötig für eine CSP mit
// `script-src 'self'` (kein Inline-Script im HTML).

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

// Dezenter Hinweis, wenn ohne Token geladen wird (außer auf /settings).
(() => {
  const el = document.getElementById('token-hinweis');
  if (!el) return;
  const hasToken = !!localStorage.getItem('kb_token');
  const onSettings = location.pathname.replace(/\/$/, '') === '/settings';
  if (!hasToken && !onSettings) el.classList.remove('hidden');
})();
