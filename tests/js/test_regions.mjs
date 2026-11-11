// Editor regions at strong zoom (render.js), run in Node with a fake DOM:
//   node --import ./tests/js/register.mjs tests/js/test_regions.mjs
// Checks that scrolling never cancels a background drawing under way, that the
// strokes follow the visible part at once, that the next region is asked before
// the edge is reached (mostly ahead of the movement) and that the blurred whole
// page under the regions appears and disappears with the zoom. While the sheet
// moves, the strokes of a new region are drawn by their worker (only those in the
// region), an out-of-date image is dropped, and drawing on the page afterwards
// turns the strokes canvas back into a normal one.
import { RenderMethods } from '../../app/view/static/js/editor/render.js';
globalThis.window = { devicePixelRatio: 2 };
const canvas = (cls = '') => {
  const c = { className: cls, width: 300, height: 150, style: {}, replaced: null,
    getContext: () => new Proxy({}, { get: (t, k) => (k === 'canvas' ? c : () => {}) , set: () => true }),
    replaceWith(n) { c.replaced = n; } };
  return c;
};
globalThis.document = { createElement: () => canvas() };
const VIEW = { w: 1024, h: 1300 };           // iPad-like screen, dpr 2
let scrollTop = 0;
const pagesEl = { getBoundingClientRect: () => ({ left: 0, top: 0, right: VIEW.w, bottom: VIEW.h, width: VIEW.w, height: VIEW.h }) };
const scale = 5;                             // strong zoom
const page = { id: 'p1', w: 595, h: 842, strokes: [], texts: [], images: [] };
const el = { getBoundingClientRect: () => ({ left: 0, top: -scrollTop, right: page.w * scale, bottom: page.h * scale - scrollTop }) };
const v = { el, coarse: canvas('coarse'), base: canvas(), ink: canvas('ink'), rendered: false, task: null, region: null, shown: null, coarseScale: 0 };
let renders = [], cancels = 0, pending = [];
let inkJobs = [];
const painter = { offThread: true, inkOn: false,
  ink(job) {
    if (!this.inkOn) return null;
    let resolve;
    const promise = new Promise((res) => { resolve = res; });
    const j = { job, resolve, cancelled: false };
    inkJobs.push(j);
    return { promise, cancel: () => { j.cancelled = true; } };
  },
  render: (key, idx, region) => {
  renders.push({ ...region });
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  const job = { region, resolve, cancel: () => { cancels++; reject(Object.assign(new Error('c'), { cancelled: true })); } };
  pending.push(job);
  return { promise, cancel: job.cancel };
} };
const ed = Object.assign(Object.create(RenderMethods.prototype), {
  scale, pagesEl, painter, pages: [page], els: new Map([['p1', v]]), hiddenStrokes: new Set(), pendingStrokes: new Map(),
  scrollDir: { x: 0, y: 1 }, bgDocs: { get: async () => true }, finger: null, momentum: null, page: () => page,
  lastScrollAt: -1e9,
});
page.bg = { id: 'bg', page: 0 };
const tick = () => new Promise((r) => setTimeout(r, 0));
const finishAll = async () => { for (const j of pending.splice(0)) j.resolve({ close() {} }); await tick(); await tick(); };
let passed = 0;
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exitCode = 1; } else passed++; };

ed.renderPage(page, v);
await tick(); await tick();
ok(v.region && !v.region.full, 'strong zoom: partial region ' + JSON.stringify(v.region));
ok(v.region.my > 0 && v.region.mx > 0, 'region has margins mx=' + v.region.mx + ' my=' + v.region.my);
ok(renders.length === 2, 'coarse + base asked (' + renders.length + ')');
ok(renders[0].r < 2 && renders[0].w === page.w * scale, 'coarse covers the whole page at low resolution r=' + renders[0].r.toFixed(3));
const inkRegion0 = v.region;
// Scroll while the base is still drawing: the drawing is NOT cancelled, the ink moves when needed.
for (let i = 0; i < 10; i++) { scrollTop += 150; ed.checkRegions(); await tick(); }
ok(cancels === 0, 'no render cancelled by scrolling (cancels=' + cancels + ')');
ok(renders.length === 2, 'no new render while one is under way (' + renders.length + ')');
ok(v.region !== inkRegion0 && v.region.y + v.region.h >= scrollTop + VIEW.h, 'ink moved to cover the visible part');
const before = renders.length;
await finishAll();               // the base arrives (for an old position) → recheck → new render
ok(v.shown && renders.length === before + 1, 'after completion a new base is asked for the current position');
ok(v.task && v.task.region.y <= scrollTop && v.task.region.y + v.task.region.h >= scrollTop + VIEW.h, 'the new base covers the visible part');
await finishAll();
ok(v.task === null && v.shown.y <= scrollTop, 'settled: base shown covers the visible part');
// Guard: a small scroll inside the region asks nothing; crossing the guard asks a new one.
const n = renders.length;
scrollTop += 10; ed.checkRegions(); await tick();
ok(renders.length === n, 'small scroll inside the region: nothing redrawn');
scrollTop = v.shown.y + v.shown.h - VIEW.h - Math.round(v.shown.my * 0.4) + 5; ed.checkRegions(); await tick();
ok(renders.length === n + 1, 'nearing the edge (guard): the next region is asked before the edge is reached');
ok(v.task.region.y + v.task.region.h > v.shown.y + v.shown.h, 'and it reaches further down');
await finishAll();
// Direction: scrolling up puts the margin above.
ed.scrollDir = { x: 0, y: -1 };
scrollTop = 2000; ed.renderPage(page, v); await tick(); await tick(); await finishAll();
const r = v.shown; const above = scrollTop - r.y, below = r.y + r.h - (scrollTop + VIEW.h);
ok(above > below, 'scrolling up: more margin above (' + above + ') than below (' + below + ')');
// Zoom back: full region, coarse freed.
ed.scale = 1; ed.renderPage(page, v); await tick(); await tick(); await finishAll();
ok(v.region.full && v.coarse.width === 0, 'normal zoom: full page, coarse canvas freed');

// --- strokes drawn by their worker while the sheet moves -------------------------------------------
const stroke = (id, x, y) => ({ id, tool: 'pen', color: '#000', width: 2, points: [[x, y, 0.5], [x + 5, y + 2, 0.5], [x + 9, y, 0.5]] });
page.strokes = [stroke('a', 20, 20), stroke('b', 300, 700), stroke('c', 100, 400)];
ed.scale = 5; ed.scrollDir = { x: 0, y: 1 }; painter.inkOn = true;
scrollTop = 0; ed.renderPage(page, v); await tick(); await tick(); await finishAll();
ok(inkJobs.length === 0 && !v.inkBitmap, 'sheet still: strokes drawn here, not by the worker');
ed.finger = { moved: true };                 // a finger scrolls
scrollTop = 1800; ed.checkRegions(); await tick();
ok(inkJobs.length === 1, 'sheet moving: the strokes of the new region go to the worker');
const job = inkJobs[0].job;
ok(job.strokes.length === 1 && job.points.length === 6, 'only the strokes inside the region are sent (' + job.strokes.length + ')');
ok(job.points instanceof Float32Array, 'points packed in one Float32Array');
const oldRegion = v.region;
ok(v.region === oldRegion && !v.inkBitmap, 'until the image arrives the strokes canvas stays where it was');
scrollTop += 40; ed.checkRegions(); await tick();
ok(inkJobs.length === 1, 'no second request while one is on its way');
inkJobs[0].resolve({ width: Math.round(job.w * job.r), height: Math.round(job.h * job.r), close() {} }); await tick(); await tick();
ok(v.inkBitmap && v.region !== oldRegion && v.region.y === job.y, 'image arrived: shown, and the region follows');
ed.drawInk(page);
ok(!v.inkBitmap && v.ink.className === 'ink', 'drawing here afterwards: a normal canvas again');
// An image that is out of date (strokes changed meanwhile) is dropped.
inkJobs = [];
scrollTop = 3200; ed.checkRegions(); await tick();
ok(inkJobs.length === 1, 'new request further down');
const staleRegion = v.region;
ed.drawInk(page);                            // e.g. a stroke from another device
inkJobs[0].resolve({ width: 10, height: 10, close() { this.closed = true; } }); await tick(); await tick();
ok(!v.inkBitmap && inkJobs.length === 2, 'out-of-date image dropped, a fresh one asked');
// The page being written on: its strokes are drawn here even while moving.
inkJobs = [];
ed.gesture = { type: 'draw', page, stroke: stroke('live', 50, 300), onLive: false };
v.inkTask?.cancel(); v.inkTask = null;
scrollTop = 1000; ed.checkRegions(); await tick();
ok(inkJobs.length === 0, 'page being written on: strokes drawn here');
ed.gesture = null; ed.finger = null; painter.inkOn = false;


// --- pen lifted: the stroke is completed where it is, the page is not drawn again ----------------
ed.scale = 5; scrollTop = 0; ed.finger = null;
ed.renderPage(page, v); await tick(); await tick(); await finishAll();
let full = 0;
const realDrawInk = ed.drawInk;
ed.drawInk = function (pg) { full++; return realDrawInk.call(this, pg); };
const live = { type: 'draw', page, stroke: stroke('n1', 30, 40), drawn: 2, curveCtx: {}, region: v.region, onLive: false };
const versionBefore = v.inkVersion || 0;
ed.finishLive(live);
ok(full === 0 && (v.inkVersion || 0) === versionBefore + 1, 'pen lifted: last piece drawn, no full redraw (an image on its way is out of date)');
ed.finishLive({ ...live, stroke: { ...live.stroke, shape: 'line' } });
ok(full === 1, 'a stroke turned into a shape: the page is drawn again');
ed.finishLive({ ...live, region: { ...v.region } });
ok(full === 2, 'the strokes canvas moved during the stroke: the page is drawn again');
ed.drawInk = realDrawInk;

console.log(`${passed} controlli superati (regioni dell'editor)`);
