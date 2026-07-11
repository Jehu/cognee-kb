import { ApiError, createCollection, loadCollections } from './api.js';

const VISIBILITY_KEY = 'kb_collection_visibility';
const LABEL_COLLATOR = new Intl.Collator('de', { usage: 'search', sensitivity: 'base' });

function normalizedCollectionLabel(label) {
  return label.normalize('NFKC').trim().replace(/\s+/g, ' ');
}

export function collectionLabelsEqual(left, right) {
  return LABEL_COLLATOR.compare(normalizedCollectionLabel(left), normalizedCollectionLabel(right)) === 0;
}

export function readCollectionVisibility() {
  try {
    const value = JSON.parse(localStorage.getItem(VISIBILITY_KEY) || 'null');
    if (value?.version === 1 && value.vaults && typeof value.vaults === 'object') return value;
  } catch { /* safe default */ }
  return { version: 1, vaults: {} };
}

export function collectionControlsVisible(vault) {
  return readCollectionVisibility().vaults[vault] !== false;
}

export function writeCollectionVisibility(vault, visible) {
  const value = readCollectionVisibility();
  value.vaults[vault] = Boolean(visible);
  localStorage.setItem(VISIBILITY_KEY, JSON.stringify(value));
}

export function filterSources(sources, type, collectionIds) {
  return sources.filter((source) =>
    (!type || source.type === type)
    && (!collectionIds.length || collectionIds.some((id) => source.collection_ids?.includes(id))),
  );
}

export function mountCollectionSelector(root, options = {}) {
  let vault = options.vault || '';
  let selected = new Set(options.selected || []);
  let selectedRecords = new Map((options.selectedRecords || []).map((record) => [record.id, record]));
  let collections = [];
  let request = 0;
  const control = root.closest?.('.collection-control') || root;

  const announce = document.createElement('div');
  announce.className = 'collection-state';
  announce.setAttribute('role', 'status');
  announce.setAttribute('aria-live', 'polite');
  const choices = document.createElement('div');
  choices.className = 'collection-choices';
  choices.setAttribute('role', 'group');
  choices.setAttribute('aria-label', options.label || 'Sammlungen');
  root.replaceChildren(announce, choices);

  function notify() { options.onChange?.([...selected], collections.filter((c) => selected.has(c.id))); }
  function render() {
    choices.replaceChildren();
    if (!collectionControlsVisible(vault)) {
      control.classList.add('hidden');
      return;
    }
    control.classList.remove('hidden');
    if (!collections.length) announce.textContent = 'Noch keine Sammlungen vorhanden.';
    else announce.textContent = `${collections.length} Sammlungen verfügbar.`;
    for (const collection of collections) {
      const label = document.createElement('label'); label.className = 'collection-choice';
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = collection.id;
      input.checked = selected.has(collection.id); input.disabled = options.disabled || collection.state === 'archived';
      const text = document.createElement('span'); text.textContent = collection.label;
      input.addEventListener('change', () => {
        if (input.checked) selected.add(collection.id); else selected.delete(collection.id);
        notify();
      });
      label.append(input, text); choices.appendChild(label);
    }
    const availableIds = new Set(collections.map((collection) => collection.id));
    for (const id of selected) {
      if (availableIds.has(id)) continue;
      const stale = document.createElement('span'); stale.className = 'collection-choice stale';
      stale.setAttribute('aria-disabled', 'true');
      stale.textContent = `${selectedRecords.get(id)?.label || 'Nicht mehr verfügbare Sammlung'} (archiviert)`;
      choices.appendChild(stale);
    }
    if (options.allowCreate !== false && !options.disabled) {
      const form = document.createElement('form'); form.className = 'collection-create';
      const input = document.createElement('input'); input.placeholder = 'Neue Sammlung'; input.maxLength = 64;
      input.setAttribute('aria-label', 'Neue Sammlung');
      const button = document.createElement('button'); button.type = 'submit'; button.className = 'btn-secondary btn-sm'; button.textContent = 'Anlegen';
      form.append(input, button);
      form.addEventListener('submit', async (event) => {
        event.preventDefault(); const label = input.value.trim(); if (!label) return;
        button.disabled = true; announce.textContent = 'Sammlung wird angelegt…';
        try {
          const created = await createCollection(vault, label);
          collections.push(created); selected.add(created.id); input.value = '';
          render(); notify(); announce.textContent = `„${created.label}“ wurde angelegt und ausgewählt.`;
        } catch (error) {
          if (error instanceof ApiError && error.status === 409) {
            const duplicate = collections.find((c) => collectionLabelsEqual(c.label, label));
            if (duplicate) { selected.add(duplicate.id); render(); notify(); announce.textContent = 'Vorhandene Sammlung wurde ausgewählt.'; }
            else announce.textContent = error.message;
          } else announce.textContent = error.message || 'Sammlung konnte nicht angelegt werden.';
          input.focus();
        } finally { button.disabled = false; }
      });
      choices.appendChild(form);
    }
  }

  async function setVault(nextVault, nextSelected = [], nextRecords = []) {
    vault = nextVault; selected = new Set(nextSelected); const current = ++request;
    selectedRecords = new Map(nextRecords.map((record) => [record.id, record]));
    control.classList.toggle('hidden', !collectionControlsVisible(vault));
    announce.textContent = 'Sammlungen werden geladen…'; choices.replaceChildren();
    if (!collectionControlsVisible(vault)) return;
    if (!vault) {
      collections = [];
      announce.textContent = '';
      return;
    }
    try {
      const loaded = await loadCollections(vault);
      if (current !== request) return;
      collections = loaded; render(); notify();
    } catch (error) {
      if (current !== request) return;
      collections = []; choices.replaceChildren(); announce.textContent = error.message || 'Sammlungen konnten nicht geladen werden.';
    }
  }

  function getSelected() { return [...selected]; }
  function getSelectedRecords() { return collections.filter((c) => selected.has(c.id)); }
  setVault(vault, options.selected || []);
  return { setVault, getSelected, getSelectedRecords };
}
