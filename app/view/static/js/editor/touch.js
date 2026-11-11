// VIEW — editor, touches: one finger scrolls the sheet with the browser's own
// scrolling (it runs apart from the page, so it answers at once and slides as on any
// page, whatever the page is doing); two fingers zoom and move the sheet, done by
// the app; a quick swipe turns the page, two taps zoom in, a long press opens the menu.
// The pages allow the browser only to scroll (touch-action: pan-x pan-y): it never
// zooms them itself. When a second finger arrives the browser's scrolling is stopped
// (the sheet cannot scroll while two fingers are down, see startPinch), so it never
// fights the zoom. The palm and the Pencil never scroll: their touches are prevented
// as soon as they start. Pencil and palm: see input.js.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { PEN_LOST_MS, PEN_MATCH_MS, PEN_MATCH_PX, SWIPE_MIN_PX, SWIPE_MAX_MS, SWIPE_RATIO, DOUBLE_TAP_MS,
  TAP_MOVE_PX, LONG_PRESS_MS, LONG_PRESS_MOVE_PX } from './shared.js';

export class TouchMethods {
  bindTouch() {
    this.pagesEl.addEventListener('touchstart', (e) => this.touchStart(e), { passive: false });
    this.pagesEl.addEventListener('touchmove', (e) => this.touchMove(e), { passive: false });
    this.pagesEl.addEventListener('touchend', (e) => this.touchEnd(e), { passive: true });
    this.pagesEl.addEventListener('touchcancel', (e) => this.touchEnd(e, true), { passive: true });
  }

  // Touches of fingers only (the Pencil is handled by the pointer events).
  fingersOf(e) {
    return [...e.touches].filter((t) => !this.isPencil(t));
  }

  // A touch of the Pencil. Safari says so (touchType "stylus"), but not always: a
  // touch is the Pencil also when it starts where the Pencil has just touched the
  // screen (its pointer event comes first). Once known, it stays the Pencil until
  // lifted. Taking the Pencil for a finger made the sheet scroll (or zoom, with the
  // palm) while writing.
  isPencil(t) {
    if (t.touchType === 'stylus' || this.pencilIds.has(t.identifier)) return true;
    const p = this.penPoint;
    return !!p && performance.now() - p.t < PEN_MATCH_MS && Math.hypot(t.clientX - p.x, t.clientY - p.y) < PEN_MATCH_PX;
  }

  // The Pencil touched the page (pointer event, before or after its touch event):
  // from now until it is lifted nothing scrolls or zooms. A finger being watched
  // that is actually the Pencil (its touch came first) is forgotten, and a pinch
  // started with it is undone.
  penTouched(e) {
    this.penLast = performance.now();
    this.penDown = true;
    this.lockScroll();
    this.penPoint = { x: e.clientX, y: e.clientY, t: performance.now() };
    const f = this.finger;
    if (f) {
      if (Math.hypot(f.x - e.clientX, f.y - e.clientY) < PEN_MATCH_PX) this.pencilIds.add(f.id);
      this.finger = null;
      this.cancelLongPress();
    }
    if (this.pinch) this.cancelPinch();
  }

  // A finger that writes (with "Dito" on) is not a finger that scrolls.
  fingerDraws(e) {
    return this.fingerDraw && !['text', 'image'].includes(this.tool)
      && e.target.closest('.page') && !e.target.closest('.textbox, .imagebox, .selection, .selection-menu, .ctx-menu');
  }

  touchStart(e) {
    for (const t of e.changedTouches) if (this.isPencil(t)) { this.pencilIds.add(t.identifier); this.lockScroll(); }
    // The Pencil's lifting was lost (no Pencil touch left, nothing from it for a
    // while): the sheet must not stay locked.
    if (this.penDown && ![...e.touches].some((t) => this.isPencil(t)) && performance.now() - this.penLast > PEN_LOST_MS) {
      this.penDown = false;
      this.unlockScroll();
    }
    // The Pencil never scrolls: its touch is prevented however many fingers are down.
    if (this.penDown || [...e.changedTouches].some((t) => this.pencilIds.has(t.identifier))) this.penTouch(e);
    this.hideMenu();
    // The palm: prevented, so the browser does not scroll with it (and no click).
    if (this.isPalm(e)) { e.preventDefault(); this.finger = null; this.cancelLongPress(); return; }
    const fingers = this.fingersOf(e);
    if (!fingers.length) { this.penTouch(e); return; }             // Pencil only
    if (fingers.length >= 2) {
      // Second finger: whatever the first one was doing becomes a pinch.
      this.finger = null;
      this.cancelLongPress();
      if (e.cancelable) e.preventDefault();
      if (!this.pinch) this.startPinch({ touches: fingers.slice(0, 2) });
      return;
    }
    if (this.fingerDraws(e)) { if (e.cancelable) e.preventDefault(); return; }   // pointer events draw the stroke
    // On a text box, an image, the selection or a menu the finger works on that item.
    if (e.target.closest('.textbox, .imagebox, .selection, .selection-menu, .ctx-menu')) return;
    // One finger: the browser scrolls; here only taps, swipes and the long press are watched.
    const t = fingers[0];
    const now = performance.now();
    this.finger = { id: t.identifier, x: t.clientX, y: t.clientY, x0: t.clientX, y0: t.clientY, t0: now, moved: false };
    this.startLongPress(t.clientX, t.clientY);
  }

  touchMove(e) {
    // While the Pencil is on the screen nothing scrolls, even if a touch slipped
    // through at its start (prevented as long as the browser allows it).
    if (this.penDown || [...e.touches].some((t) => this.pencilIds.has(t.identifier))) this.penTouch(e);
    if (this.isPalm(e)) { if (e.cancelable) e.preventDefault(); return; }
    if (!this.fingersOf(e).length) { this.penTouch(e); return; }
    if (this.pinch) {
      if (e.cancelable) e.preventDefault();
      const fingers = this.fingersOf(e);
      if (fingers.length >= 2) this.movePinch({ touches: fingers.slice(0, 2) });
      return;
    }
    const f = this.finger;
    if (!f) return;
    const t = [...e.touches].find((c) => c.identifier === f.id);
    if (!t) return;
    if (!f.moved && Math.hypot(t.clientX - f.x0, t.clientY - f.y0) > LONG_PRESS_MOVE_PX) {
      f.moved = true;
      this.cancelLongPress();
    }
    f.x = t.clientX; f.y = t.clientY;
  }

  touchEnd(e, cancelled = false) {
    for (const t of e.changedTouches) this.pencilIds.delete(t.identifier);
    if (!e.touches.length) {                     // nothing left on the screen
      this.pencilIds.clear();
      if (this.penDown) { this.penDown = false; this.unlockScroll(); }
    }
    if (this.pinch && (cancelled || this.fingersOf(e).length < 2)) {
      this.endPinch();
      this.finger = null;              // the finger left on the screen does nothing more
      this.flushStatus();
      return;
    }
    const f = this.finger;
    if (!f) return;
    // Its touch should be among those that ended; if it has simply vanished (Safari
    // may drop it), the finger is over as well: otherwise the sheet would count as
    // still moving, and the pages would not be drawn again until the next touch.
    const t = [...e.changedTouches].find((c) => c.identifier === f.id) || ([...e.touches].some((c) => c.identifier === f.id) ? null : { clientX: f.x, clientY: f.y });
    if (!t) return;
    this.finger = null;
    this.flushStatus();                // the save status received while scrolling
    this.cancelLongPress();
    if (cancelled || this.longPressed) { this.longPressed = false; return; }
    const now = performance.now();
    const dx = t.clientX - f.x0, dy = t.clientY - f.y0, dt = now - f.t0;
    // Quick swipe sideways, when the sheet fits the screen sideways: next or previous page.
    if (dt < SWIPE_MAX_MS && Math.abs(dx) >= SWIPE_MIN_PX && Math.abs(dx) > SWIPE_RATIO * Math.abs(dy)
        && this.pagesEl.scrollWidth <= this.pagesEl.clientWidth + 2) {
      this.lastTap = null;
      this.nextPage(dx < 0 ? 1 : -1);
      return;
    }
    if (f.moved) {                     // the browser goes on sliding by itself
      this.lastTap = null;
      return;
    }
    // A tap. Two taps close together: zoom in on that spot, or back to the page width.
    if (dt > SWIPE_MAX_MS || ['text', 'image'].includes(this.tool)) { this.lastTap = null; return; }
    const last = this.lastTap;
    this.lastTap = { x: t.clientX, y: t.clientY, t: now };
    if (last && now - last.t < DOUBLE_TAP_MS && Math.hypot(last.x - t.clientX, last.y - t.clientY) < TAP_MOVE_PX) {
      this.lastTap = null;
      this.toggleZoomAt(t.clientX, t.clientY);
    }
  }

  // While the Pencil touches the screen the sheet cannot scroll at all (overflow:
  // hidden, like during a pinch). Preventing the Pencil's touches is not enough with
  // the browser's own scrolling: the browser decides to scroll apart from the page,
  // and the prevention arrives in time only if the page is free at that moment, and
  // never while the sheet is still sliding after a finger flick (then the Pencil
  // drags it). This also stops that sliding. As soon as the Pencil is lifted the
  // sheet is free again: a finger scrolls at once.
  lockScroll() {
    this.pagesEl.classList.add('pen-down');
  }

  unlockScroll() {
    if (!this.penDown) this.pagesEl.classList.remove('pen-down');
  }

  // The Pencil's own touch events are always prevented, as the editor has done from
  // the start: otherwise Safari may take a quick Pencil touch for a gesture of its
  // own and cancel the pointer events of the stroke (strokes lost when writing fast).
  penTouch(e) {
    if (e.cancelable && e.target.closest('.pages') && !e.target.closest('.textbox, .imagebox, .selection, .selection-menu, .ctx-menu')) e.preventDefault();
  }

  // --- long press: the menu ---------------------------------------------------------------------
  startLongPress(x, y) {
    this.cancelLongPress();
    this.longPressTimer = setTimeout(() => {
      this.longPressTimer = null;
      if (!this.finger || this.finger.moved) return;
      this.longPressed = true;        // the release that follows is not a tap
      this.finger = null;
      this.showMenu(x, y);
    }, LONG_PRESS_MS);
  }

  cancelLongPress() {
    clearTimeout(this.longPressTimer);
    this.longPressTimer = null;
  }
}
