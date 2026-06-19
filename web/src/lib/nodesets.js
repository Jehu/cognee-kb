// Lädt Node-Sets für einen Vault — aber nur, wenn der Vault danach noch
// aktuell ausgewählt ist. Bei schnellem Vault-Wechsel (A→B) können zwei
// loadNodeSets-Requests concurrent laufen; löst der ältere (A) später auf,
// würde er sonst Node-Sets aus A in die Datalliste mischen, während B
// ausgewählt ist -> falsch getaggter Ingest. Rückgabe null = Request überholt
// (oder leer/Fehler); der Aufrufer rendert dann nichts.

export async function loadCurrentNodeSets(vault, isCurrent, load) {
  if (!vault) return null;
  let nodeSets;
  try {
    nodeSets = await load(vault);
  } catch {
    return null; // Vorschläge sind Komfort; Ingest darf ohne sie weiter laufen.
  }
  return isCurrent(vault) ? nodeSets : null;
}
