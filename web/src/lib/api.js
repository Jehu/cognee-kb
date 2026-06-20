// Gemeinsamer API-Helper: same-origin Gateway, Bearer-Token aus localStorage.

export const STATIC_VAULTS = ['privat', 'allgemein', 'business-ki', 'business-mwe'];
export const STATIC_VAULT_META = [
  { name: 'privat', instance: 'local' },
  { name: 'allgemein', instance: 'cloud' },
  { name: 'business-ki', instance: 'cloud' },
  { name: 'business-mwe', instance: 'cloud' },
];

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

function normalizeVault(vault) {
  if (typeof vault === 'string') return { name: vault, instance: '' };
  return { name: vault.name, instance: vault.instance || '' };
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

// Vault-Namen laden. Auth-Fehler sind kein Fallback-Fall: eine unvollständige
// statische Liste würde sonst wie echte Gateway-Daten wirken.
export async function loadVaults() {
  try {
    const vaults = await api('/api/vaults');
    if (Array.isArray(vaults) && vaults.length) {
      const normalized = vaults.map(normalizeVault).filter((v) => v.name);
      return {
        ok: true,
        source: 'api',
        vaults: normalized,
        names: normalized.map((v) => v.name),
      };
    }
  } catch (e) {
    if (e.status === 401) {
      return { ok: false, reason: 'auth', names: [], message: e.message };
    }
    return {
      ok: true,
      source: 'fallback',
      vaults: STATIC_VAULT_META,
      names: STATIC_VAULTS,
      message: e.message,
    };
  }
  return { ok: true, source: 'fallback', vaults: STATIC_VAULT_META, names: STATIC_VAULTS };
}

// Token bleibt im Authorization-Header, nie in der URL — sonst landet er im
// Server-Log und in der Browser-History (Privacy-Wand würde brechen).
export async function openSourceRaw(vault, sourceId) {
  const token = getToken();
  let res;
  try {
    res = await fetch(
      `/api/source/${encodeURIComponent(vault)}/${encodeURIComponent(sourceId)}/raw`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
  } catch {
    alert('Quelle nicht erreichbar (Netzwerkfehler).');
    return;
  }
  if (res.status === 401) { alert('Nicht autorisiert — Token in Einstellungen prüfen.'); return; }
  if (res.status === 404) { alert('Quelle nicht gefunden.'); return; }
  if (!res.ok) { alert(`Fehler ${res.status} beim Laden der Quelle.`); return; }
  openBlobInNewTab(await res.blob());
}

// Öffnet einen Blob in einem neuen Tab und gibt die Object-URL nach kurzem
// Timeout frei (sonst Leak über lange Sessions). Erkennt blockierte Popups
// (iOS Safari außerhalb einer User-Gesture) und meldet sich statt stumm zu
// scheitern — extrahiert, damit es ohne DOM testbar ist.
export function openBlobInNewTab(blob) {
  const u = URL.createObjectURL(blob);
  const win = window.open(u, '_blank');
  setTimeout(() => URL.revokeObjectURL(u), 60_000);
  if (!win) alert('Popup wurde blockiert — bitte Popups für diese Seite erlauben.');
}

// <select> mit Vaults befüllen, Standard-Vault vorauswählen.
export async function initVaultSelect(select) {
  const state = await loadVaults();
  const current = getDefaultVault();
  const vaults = state.vaults || state.names.map((name) => ({ name, instance: '' }));
  const names = vaults.map((v) => v.name);
  select.innerHTML = '';
  select.disabled = !state.ok;
  select.dataset.vaultState = state.ok ? state.source : state.reason;
  if (!state.ok) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Token in Einstellungen setzen';
    select.appendChild(opt);
    return state;
  }
  const groups = new Map();
  for (const vault of vaults) {
    const groupName = vault.instance || 'Vaults';
    if (!groups.has(groupName)) groups.set(groupName, []);
    groups.get(groupName).push(vault);
  }
  for (const [groupName, groupVaults] of groups) {
    const group = document.createElement('optgroup');
    group.label = groupName;
    for (const vault of groupVaults) {
      const opt = document.createElement('option');
      opt.value = vault.name;
      opt.textContent = vault.instance ? `${vault.name} (${vault.instance})` : vault.name;
      group.appendChild(opt);
    }
    select.appendChild(group);
  }
  if (names.includes(current)) select.value = current;
  return state;
}

export async function loadNodeSets(vault) {
  const data = await api(`/api/node-sets/${encodeURIComponent(vault)}`);
  return Array.isArray(data.node_sets) ? data.node_sets : [];
}

export async function loadSources(vault) {
  const data = await api(`/api/sources/${encodeURIComponent(vault)}`);
  return Array.isArray(data.sources) ? data.sources : [];
}
