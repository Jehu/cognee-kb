// Bootstrap: shared UI helpers für PWA-Seiten.
// api.js hält die API-Calls, hier die kleinen Wrapper.

// Zeigt den Wall-Hinweis unter dem Vault-Selektor.
export function getVaultMeta(select) {
  const opt = select.selectedOptions[0];
  if (!opt) return null;
  const wall = (opt.parentNode.label || '').toLowerCase();
  return { name: select.value, wall };
}

// Ersetzt das alte nodesets.js — liefert eine einfache Autosuggest-Befüllung.
export async function loadNodeSets(vault, datalistEl) {
  if (!vault) return;
  datalistEl.innerHTML = '';
  try {
    const { api } = await import('./api.js');
    const d = await api(`/api/node-sets/${encodeURIComponent(vault)}`);
    const sets = Array.isArray(d.node_sets) ? d.node_sets : [];
    for (const ns of sets) {
      const o = document.createElement('option');
      o.value = ns;
      datalistEl.appendChild(o);
    }
  } catch {
    // still fallback: kein Node-Set-Vorschlag.
  }
}

export { initVaultSelect } from './api.js';