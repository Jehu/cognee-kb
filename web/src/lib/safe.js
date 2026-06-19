// Erlaubt nur http(s)-URLs als href — verteidigt gegen javascript:/data:-URLs,
// die über einen DB-Edit oder einen künftigen Schreiber (der classify umgeht)
// in die sources.url-Spalte gelangen könnten. Click-Driven-XSS würde sonst den
// localStorage-Token (kb_token) exfiltrieren.

export function safeSourceHref(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null;
}
