// Gemeinsamer API-Helper: same-origin Gateway, Bearer-Token aus localStorage.

export const STATIC_VAULTS = ['privat', 'business-ki', 'business-mwe'];

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export function getToken() {
  return localStorage.getItem('kb_token') || '';
}

export function getDefaultVault() {
  return localStorage.getItem('kb_vault') || STATIC_VAULTS[0];
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';

  let res;
  try {
    res = await fetch(path, { ...options, headers });
  } catch {
    throw new ApiError('Gateway nicht erreichbar (Netzwerkfehler).', 0);
  }
  if (res.status === 401) throw new ApiError('Nicht autorisiert — Token in Einstellungen setzen.', 401);
  if (res.status === 502) throw new ApiError('Instanz nicht erreichbar.', 502);
  if (!res.ok) {
    let detail = '';
    try {
      const data = await res.json();
      detail = data.detail || data.error || '';
    } catch { /* kein JSON */ }
    throw new ApiError(detail || `Fehler ${res.status}`, res.status);
  }
  return res.json();
}

// Vault-Namen laden, Fallback auf die drei statischen.
export async function loadVaults() {
  try {
    const vaults = await api('/api/vaults');
    if (Array.isArray(vaults) && vaults.length) {
      return vaults.map((v) => (typeof v === 'string' ? v : v.name));
    }
  } catch { /* Fallback */ }
  return STATIC_VAULTS;
}

// <select> mit Vaults befüllen, Standard-Vault vorauswählen.
export async function initVaultSelect(select) {
  const names = await loadVaults();
  const current = getDefaultVault();
  select.innerHTML = '';
  for (const name of names) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  }
  if (names.includes(current)) select.value = current;
}
