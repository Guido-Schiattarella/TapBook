// Pencil and fingers (touch.js, input.js), run in Node with fake events:
//   node --import ./tests/js/register.mjs tests/js/test_pencil.mjs
// The Pencil must never scroll the sheet: its touch is prevented with fingers
// already down, when Safari does not report it as a stylus (recognised from its
// pointer event, in either order), and while it is on the screen every movement
// is prevented; a finger arriving meanwhile is the palm. After the Pencil is
// lifted a finger scrolls freely (the browser's own scrolling), right away. While
// writing the sheet cannot scroll at all (class pen-down: overflow hidden), and
// as soon as the Pencil is lifted it can scroll again, and a finger scrolls at once.
import { TouchMethods } from '../../app/view/static/js/editor/touch.js';
import { InputMethods } from '../../app/view/static/js/editor/input.js';

const ed = Object.create(null);
for (const cls of [TouchMethods, InputMethods]) {
  for (const k of Object.getOwnPropertyNames(cls.prototype)) if (k !== 'constructor') ed[k] = cls.prototype[k];
}
const classes = new Set();
const page = { closest: (sel) => (sel.split(',').some((s) => ['.page', '.pages'].includes(s.trim())) ? page : null) };
Object.assign(ed, {
  pencilIds: new Set(), penDown: false, penLast: -1e9, finger: null, pinch: null, gesture: null, fingerDraw: false, tool: 'pen',
  pagesEl: { classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) } },
  hideMenu() {}, startLongPress() {}, cancelLongPress() {}, flushStatus() {}, showMenu() {},
  startPinch() { this.pinch = { started: true }; }, movePinch() {}, endPinch() { this.pinch = null; },
  cancelPinch() { this.pinch = null; }, nextPage() {}, toggleZoomAt() {},
});
const touch = (id, x, y, type = 'direct', r = 8) => ({ identifier: id, clientX: x, clientY: y, radiusX: r, radiusY: r, touchType: type });
const ev = (touches, changed) => ({ touches, changedTouches: changed, target: page, cancelable: true, prevented: false,
  preventDefault() { this.prevented = true; } });
const pen = (x, y) => ed.penTouched({ clientX: x, clientY: y });
const penUp = () => { ed.penLast = performance.now(); ed.penDown = false; ed.unlockScroll(); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let passed = 0;
const ok = (c, m) => { if (!c) { console.error('FAIL', m); process.exitCode = 1; } else passed++; };

// 1) a finger (or a small palm) already down, then the Pencil
const palm = touch(1, 50, 600, 'direct', 20);
ed.touchStart(ev([palm], [palm]));
pen(200, 300);
const p1 = touch(2, 200, 300, 'stylus');
let e = ev([palm, p1], [p1]); ed.touchStart(e);
ok(e.prevented, 'Pencil touching with a finger already down: prevented');
e = ev([palm, touch(2, 230, 305, 'stylus')], [touch(2, 230, 305, 'stylus')]); ed.touchMove(e);
ok(e.prevented && !ed.pinch, 'its movement prevented, and no pinch with the palm');
penUp(); ed.touchEnd(ev([], [palm, p1]));
ok(!ed.penDown && ed.pencilIds.size === 0, 'all lifted: nothing left marked');
// 2) Pencil reported as a plain touch, its pointer event first
pen(200, 300);
const p2 = touch(3, 202, 301);
e = ev([p2], [p2]); ed.touchStart(e);
ok(e.prevented && !ed.finger, 'Pencil not reported as stylus: recognised from its pointer event, prevented');
e = ev([touch(3, 260, 303)], [touch(3, 260, 303)]); ed.touchMove(e);
ok(e.prevented, 'and its movement prevented');
penUp(); ed.touchEnd(ev([], [p2]));
// 3) the other order: touch first, pointer event after
const p3 = touch(4, 200, 340);
ed.touchStart(ev([p3], [p3]));
ok(!!ed.finger, '(touch first: watched as a finger for now)');
pen(200, 340);
ok(!ed.finger && ed.pencilIds.has(4), 'pointer event after: the touch becomes the Pencil');
e = ev([touch(4, 240, 342)], [touch(4, 240, 342)]); ed.touchMove(e);
ok(e.prevented, 'its movement prevented (no scrolling)');
penUp(); ed.touchEnd(ev([], [p3]));
// 4) Pencil just lifted: a finger scrolls freely at once
const f = touch(5, 200, 600);
e = ev([f], [f]); ed.touchStart(e);
ok(!e.prevented && !!ed.finger, 'finger after the Pencil: not prevented (browser scrolls)');
e = ev([touch(5, 200, 500)], [touch(5, 200, 500)]); ed.touchMove(e);
ok(!e.prevented, 'its movement not prevented');
ed.touchEnd(ev([], [touch(5, 200, 500)]));
// 5) a finger arriving while the Pencil writes is the palm
pen(200, 300);
const p5 = touch(6, 200, 300, 'stylus');
ed.touchStart(ev([p5], [p5]));
const f5 = touch(7, 500, 600);
e = ev([p5, f5], [f5]); ed.touchStart(e);
ok(e.prevented && !ed.finger && !ed.pinch, 'finger while the Pencil writes: palm, prevented');
penUp(); ed.touchEnd(ev([], [p5, f5]));
// 7) the sheet is locked while writing, and free again as soon as the Pencil is lifted
pen(200, 300);
ok(classes.has('pen-down'), 'Pencil down: the sheet cannot scroll');
penUp();
ok(!classes.has('pen-down'), 'Pencil lifted: the sheet can scroll at once');
pen(220, 300);
ok(classes.has('pen-down'), 'next stroke: locked again at once');
penUp();
const quick = touch(30, 500, 900);
e = ev([quick], [quick]); ed.touchStart(e);
ok(!e.prevented && !!ed.finger, 'a finger right after the last stroke scrolls (no waiting time)');
ed.touchEnd(ev([], [quick]));
// 8) a lost lifting does not leave the sheet locked
pen(200, 300);
ed.penLast = performance.now() - 5000;
const g8 = touch(20, 600, 900);
ed.touchStart(ev([g8], [g8]));
ok(!ed.penDown && !classes.has('pen-down'), 'Pencil lifting lost: unlocked at the next finger');
ed.touchEnd(ev([], [g8]));
// 6) a pinch started by the Pencil taken for a finger is undone
const a = touch(8, 100, 100), c = touch(9, 300, 300);
ed.touchStart(ev([a], [a])); ed.touchStart(ev([a, c], [c]));
ok(!!ed.pinch, '(two touches: pinch)');
pen(300, 300);
ok(!ed.pinch, 'one of them was the Pencil: pinch undone');
penUp(); ed.touchEnd(ev([], [a, c]));

// 9) palm by size: a thumb lying sideways is still a finger, a palm is not
const thumb = touch(40, 300, 900, 'direct', 44);
e = ev([thumb], [thumb]); ed.touchStart(e);
ok(!e.prevented && !!ed.finger, 'thumb sideways (radius 44): a finger, it scrolls');
ed.touchEnd(ev([], [thumb]));
const palmBig = touch(41, 300, 900, 'direct', 70);
e = ev([palmBig], [palmBig]); ed.touchStart(e);
ok(e.prevented && !ed.finger, 'palm (radius 70): prevented');
ed.touchEnd(ev([], [palmBig]));
const index = touch(42, 400, 700, 'direct', 10), thumbP = touch(43, 250, 800, 'direct', 80);
ed.touchStart(ev([index], [index])); e = ev([index, thumbP], [thumbP]); ed.touchStart(e);
ok(!!ed.pinch, 'pinch with a wide thumb (radius 80): still a pinch');
ed.endPinch(); ed.touchEnd(ev([], [index, thumbP]));
console.log(`${passed} controlli superati (Pencil e dita)`);
