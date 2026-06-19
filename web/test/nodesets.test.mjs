import { test } from 'node:test';
import assert from 'node:assert';
import { loadCurrentNodeSets } from '../src/lib/nodesets.js';

const tick = () => new Promise((r) => setTimeout(r, 0));

test('returns node sets when the vault is still current', async () => {
  const out = await loadCurrentNodeSets(
    'business-ki', () => true, async () => ['a', 'b']);
  assert.deepEqual(out, ['a', 'b']);
});

test('returns null when the selection moved on (stale request)', async () => {
  // Simuliert Vault A→B: nach dem await ist der angefragte Vault nicht mehr aktuell.
  const out = await loadCurrentNodeSets(
    'allgemein', (v) => v === 'business-ki', async () => ['x']);
  assert.equal(out, null);
});

test('returns null for empty vault', async () => {
  const out = await loadCurrentNodeSets('', () => true, async () => ['x']);
  assert.equal(out, null);
});

test('returns null when loading throws (comfort feature, no hard fail)', async () => {
  const out = await loadCurrentNodeSets(
    'privat', () => true, async () => { throw new Error('boom'); });
  assert.equal(out, null);
});

test('checks staleness AFTER the await resolves (not before)', async () => {
  // Der Guard muss nach dem await prüfen — ein Check davor fängt das Rennen nicht.
  let current = 'allgemein';
  const load = async () => { current = 'business-ki'; return ['late']; };
  // isCurrent liest CURRENT (vom Aufrufer); nach dem await ist es 'business-ki',
  // angefragt war 'allgemein' -> null.
  const out = await loadCurrentNodeSets(
    'allgemein', (v) => v === current, load);
  assert.equal(out, null);
});
