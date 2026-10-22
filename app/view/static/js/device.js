// VIEW — identifier of this browser tab.
// It survives a page reload (sessionStorage belongs to the tab), so the
// controller recognises the same tab opening a document again and replaces its
// previous connection instead of counting one more device.
const KEY = 'notes.tab';
let memory = null;   // when the browser keeps no storage (e.g. private mode)

function create() {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function tabId() {
  try {
    let id = sessionStorage.getItem(KEY);
    if (!id || !/^[0-9a-f]{24}$/.test(id)) { id = create(); sessionStorage.setItem(KEY, id); }
    return id;
  } catch {
    memory = memory || create();
    return memory;
  }
}

// A new identifier: when another tab turns out to have the same one (a tab
// duplicated by the browser copies it).
export function renewTabId() {
  const id = create();
  memory = id;
  try { sessionStorage.setItem(KEY, id); } catch { /* no storage available */ }
  return id;
}
