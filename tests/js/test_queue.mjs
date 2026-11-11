// Operation queue of the editor (sync.js), run in Node:
//   node --import ./tests/js/register.mjs tests/js/test_queue.mjs
// After a long pause the computer closes the device's session; the first change
// reopens the document. Operations queued meanwhile (the second stroke of an "=")
// must leave with the new session, not be dropped; operations of a document that
// was closed (or replaced by another one) are dropped.
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
const { SyncMethods } = await import('../../app/view/static/js/editor/sync.js');
const { ApiError } = await import('../../app/view/static/js/api.js');

const ed = Object.create(SyncMethods.prototype);
Object.assign(ed, {
  openId: 1, session: 'old', blocked: false, inFlight: 0, queue: Promise.resolve(), lastStatus: 'saved',
  setStatus() {}, showStatus() {}, showBanner(m) { this.banner = m; }, applyResult() {},
  reopens: 0,
  async reopen() { this.reopens++; await new Promise((r) => setTimeout(r, 50)); this.session = 'new'; },
});
let passed = 0;
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exitCode = 1; } else passed++; };
const sent = [];
const op = (name) => async (session) => {
  if (session === 'old') throw new ApiError('chiusa', 410, { reason: 'idle' });
  sent.push([name, session]);
  return {};
};
// first stroke after the pause, and the second one right after it
const first = ed.enqueue(op('primo tratto'));
await new Promise((r) => setTimeout(r, 10));              // the reopening is under way
const second = ed.enqueue(op('secondo tratto'));
await Promise.all([first, second]);
ok(ed.reopens === 1, 'the document is reopened once');
ok(sent.length === 2 && sent.every(([, s]) => s === 'new'), 'both strokes sent, with the new session: ' + JSON.stringify(sent));
ok(sent[0][0] === 'primo tratto' && sent[1][0] === 'secondo tratto', 'in their order');
ok(ed.inFlight === 0, 'nothing left in flight');
// another document opened: what was queued for the old one is dropped
sent.length = 0;
ed.session = 'doc1';
const slow = ed.enqueue(async (s) => { await new Promise((r) => setTimeout(r, 30)); sent.push(['lento', s]); return {}; });
const stale = ed.enqueue(async (s) => { sent.push(['vecchio documento', s]); return {}; });
ed.openId++; ed.session = 'doc2';                           // the editor now shows another document
await Promise.all([slow, stale]);
ok(!sent.some(([n]) => n === 'vecchio documento'), 'operations of a closed document are not sent to the new one');
console.log(`${passed} controlli superati (coda delle operazioni)`);
