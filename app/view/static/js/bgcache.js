// VIEW — backgrounds of the documents kept on this device, so that opening a
// document downloads only what is not here yet.
//
// A background is a PDF without the notes (see the model's backgrounds.py),
// identified by the first 32 hex characters of its SHA-256: the same id is always
// the same content, so a background found here is used as it is. They live in the
// browser's Cache Storage, separately for each user, up to BUDGET bytes: beyond
// that, the backgrounds used least recently go. Everything is optional: without
// Cache Storage (no HTTPS, private browsing, storage full) the backgrounds are
// simply downloaded every time, as before.
const PREFIX = 'tapbook-bg-';
const INDEX_KEY = 'notes.bgIndex';          // {user: {id: {size, used}}}: for the budget
const BUDGET = 1024 * 1024 * 1024;          // 1 GB per device
const ID_RE = /^[0-9a-f]{32}$/;

const supported = () => typeof caches !== 'undefined' && window.isSecureContext;
const cacheName = (user) => PREFIX + encodeURIComponent(user);
const keyUrl = (id) => `/bgcache/${id}`;     // only a name inside the cache: never requested

function readIndex() {
  try { return JSON.parse(localStorage.getItem(INDEX_KEY) || '{}') || {}; } catch { return {}; }
}
function writeIndex(index) {
  try { localStorage.setItem(INDEX_KEY, JSON.stringify(index)); } catch { /* no storage available */ }
}
function touch(user, id, size) {
  const index = readIndex();
  index[user] = index[user] || {};
  index[user][id] = { size: size ?? index[user][id]?.size ?? 0, used: Date.now() };
  writeIndex(index);
}

let persistAsked = false;

// Bytes of the background, or null if this device does not have it.
export async function getBackground(user, id) {
  if (!supported() || !ID_RE.test(id)) return null;
  try {
    const resp = await (await caches.open(cacheName(user))).match(keyUrl(id));
    if (!resp) return null;
    const bytes = new Uint8Array(await resp.arrayBuffer());
    touch(user, id, bytes.length);
    return bytes;
  } catch {
    return null;
  }
}

// Keeps a background just downloaded. It is kept only if its content really has
// that id (a damaged download is never kept).
export async function putBackground(user, id, bytes) {
  if (!supported() || !ID_RE.test(id)) return;
  try {
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    const hex = Array.from(digest.slice(0, 16), (b) => b.toString(16).padStart(2, '0')).join('');
    if (hex !== id) return;
    if (!persistAsked) { persistAsked = true; navigator.storage?.persist?.().catch(() => {}); }
    await makeRoom(user, bytes.length);
    const cache = await caches.open(cacheName(user));
    await cache.put(keyUrl(id), new Response(bytes, { headers: { 'Content-Type': 'application/pdf' } }));
    touch(user, id, bytes.length);
  } catch { /* not kept: it will be downloaded again next time */ }
}

// A background that turned out to be unreadable.
export async function dropBackground(user, id) {
  try { await (await caches.open(cacheName(user))).delete(keyUrl(id)); } catch { /* ignored */ }
  const index = readIndex();
  if (index[user]) { delete index[user][id]; writeIndex(index); }
}

// Before keeping `size` more bytes: the backgrounds used least recently go, so
// that the total stays within the budget (and within the space the browser grants).
async function makeRoom(user, size) {
  const index = readIndex();
  const all = [];
  for (const [u, items] of Object.entries(index)) {
    for (const [id, info] of Object.entries(items || {})) all.push({ u, id, size: info.size || 0, used: info.used || 0 });
  }
  let total = all.reduce((t, x) => t + x.size, 0);
  let limit = BUDGET;
  try {
    const est = await navigator.storage?.estimate?.();
    if (est?.quota) limit = Math.min(limit, est.quota * 0.6 - ((est.usage || 0) - total));
  } catch { /* no estimate */ }
  all.sort((a, b) => a.used - b.used);
  for (const x of all) {
    if (total + size <= limit) break;
    try { await (await caches.open(cacheName(x.u))).delete(keyUrl(x.id)); } catch { /* ignored */ }
    delete index[x.u][x.id];
    total -= x.size;
  }
  writeIndex(index);
}

// Logging out, or account deleted: the user's backgrounds are removed from this device.
export async function clearBackgrounds(user) {
  if (!user) return;
  try { if (supported()) await caches.delete(cacheName(user)); } catch { /* ignored */ }
  const index = readIndex();
  delete index[user];
  writeIndex(index);
}
