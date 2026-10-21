// VIEW — editor, input from Apple Pencil, finger and mouse; strokes, geometric shapes (press and hold), eraser.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { apiPost } from '../api.js';
import { COLORS, HIGHLIGHTER_FACTOR, MIN_POINT_DIST, STABILIZER, HOLD_MS, HOLD_MOVE_PX, SNAP_PX, SHAPE_MAX_POINTS, GESTURE_POINT_DIST, GESTURE_MAX_POINTS, uid, ERASER_PREF, touches, isStylus } from './shared.js';

export class InputMethods {
  // =====================================================================
  // Input: Pencil, mouse, finger, buttons, keyboard
  // =====================================================================
  bindInput() {
    document.querySelectorAll('.tool[data-tool]').forEach((b) => b.addEventListener('click', () => {
      this.tool = b.dataset.tool;
      if (this.tool !== 'lasso') this.clearSelection();
      this.showTool();
    }));
    COLORS.forEach((color) => {
      const b = document.createElement('button');
      b.style.background = color;
      b.title = color;
      b.dataset.color = color;
      b.addEventListener('click', () => {
        this.color = color;
        this.showColor();
        // With items selected, the chosen colour applies to them.
        if (this.hasSelection()) this.send({ type: 'recolorSelection', ...this.selectionPayload(), color });
      });
      this.colorsEl.append(b);
    });
    document.getElementById('width').addEventListener('change', (e) => { this.width = Number(e.target.value); });
    document.querySelectorAll('#eraser-sizes .size').forEach((b) => b.addEventListener('click', () => {
      this.eraserRadius = Number(b.dataset.radius);
      try { localStorage.setItem(ERASER_PREF, String(this.eraserRadius)); } catch { /* no storage available */ }
      this.showTool();
    }));
    // Pencil approaching the screen (compatible iPads) or mouse: the eraser circle
    // follows the tip even before touching, so you can see where it will erase.
    this.pagesEl.addEventListener('pointerleave', () => { if (!this.gesture) this.hideEraserCursor(); });
    document.getElementById('finger-draw').addEventListener('change', (e) => {
      this.fingerDraw = e.target.checked;
      e.target.closest('.toggle').classList.toggle('on', this.fingerDraw);
    });
    this.undoBtn.addEventListener('click', () => this.send({ type: 'undo' }));
    this.redoBtn.addEventListener('click', () => this.send({ type: 'redo' }));
    document.getElementById('btn-add-page').addEventListener('click', () => this.addPage());
    this.layoutBtn.addEventListener('click', () => this.chooseLayout());
    document.getElementById('btn-del-page').addEventListener('click', () => this.deletePage());
    document.getElementById('btn-zoom-in').addEventListener('click', () => this.zoomBy(1.25));
    document.getElementById('btn-zoom-out').addEventListener('click', () => this.zoomBy(0.8));
    document.getElementById('btn-back').addEventListener('click', () => this.leave());
    document.getElementById('btn-photo').addEventListener('click', () => this.pickImage(null));
    this.imageInput.addEventListener('change', () => {
      const file = this.imageInput.files[0];
      this.imageInput.value = '';
      if (file && this.imageTarget) this.uploadImage(this.imageTarget, file);
    });

    document.addEventListener('keydown', (e) => {
      if (!this.session || e.target.tagName === 'TEXTAREA') return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if ((key === 'delete' || key === 'backspace') && this.hasSelection()) {
        e.preventDefault();
        this.removeSelection();
      } else if (mod && key === 'z') { e.preventDefault(); this.send({ type: e.shiftKey ? 'redo' : 'undo' }); }
      else if (mod && key === 'y') { e.preventDefault(); this.send({ type: 'redo' }); }
    });

    // Touches: two fingers = pinch zoom; Pencil (and finger with "Dito" on)
    // = writing, so the page must not scroll.
    this.pagesEl.addEventListener('touchstart', (e) => {
      if (e.touches.length === 2 && !isStylus(e.touches)) { this.startPinch(e); e.preventDefault(); return; }
      this.blockScroll(e);
    }, { passive: false });
    this.pagesEl.addEventListener('touchmove', (e) => {
      if (this.pinch) { this.movePinch(e); e.preventDefault(); return; }
      this.blockScroll(e);
    }, { passive: false });
    const endTouch = (e) => { if (this.pinch && e.touches.length < 2) this.endPinch(); };
    this.pagesEl.addEventListener('touchend', endTouch);
    this.pagesEl.addEventListener('touchcancel', endTouch);
    // Safari: prevents zooming the whole web page (we handle zoom ourselves).
    document.addEventListener('gesturestart', (e) => e.preventDefault());

    this.pagesEl.addEventListener('pointerdown', (e) => this.pointerDown(e));
    this.pagesEl.addEventListener('pointermove', (e) => this.pointerMove(e));
    this.pagesEl.addEventListener('pointerup', (e) => this.pointerUp(e));
    this.pagesEl.addEventListener('pointercancel', (e) => this.pointerUp(e));
    // A single tap (not a scroll) creates text boxes and images.
    this.pagesEl.addEventListener('click', (e) => this.pageClick(e));

    // With strong zoom the pages are drawn in pieces: scrolling updates the piece.
    let regionTimer = null;
    this.pagesEl.addEventListener('scroll', () => {
      if (!this.pinch) this.showNav();
      if (regionTimer) return;
      regionTimer = setTimeout(() => { regionTimer = null; this.checkRegions(); }, 80);
    }, { passive: true });

    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { if (this.pdf) { this.computeScale(); this.buildPages(); } }, 200);
    });
    window.addEventListener('beforeunload', (e) => {
      if (this.inFlight > 0) e.preventDefault();  // changes not yet received by the computer
    });
  }

  blockScroll(e) {
    const draws = isStylus(e.touches) || (this.fingerDraw && !['text', 'image'].includes(this.tool));
    if (draws && e.target.closest('.page') && !e.target.closest('.textbox, .imagebox, .selection')) e.preventDefault();
  }

  // Palm rejection: Pencil and mouse always draw; the finger only with "Dito" on.
  acceptsPointer(e) {
    if (e.pointerType === 'pen') return true;
    if (e.pointerType === 'mouse') return e.button === 0;
    return this.fingerDraw && !this.pinch;
  }

  pagePoint(page, e) {
    const rect = this.els.get(page.id).el.getBoundingClientRect();
    return [
      (e.clientX - rect.left) / this.scale,
      (e.clientY - rect.top) / this.scale,
      e.pressure > 0 ? Math.round(e.pressure * 1000) / 1000 : 0.5,
    ];
  }

  pointerDown(e) {
    const pageEl = e.target.closest('.page');
    if (!pageEl || this.gesture || this.blocked || e.target.closest('.textbox, .imagebox, .selection')) return;
    if (['text', 'image'].includes(this.tool) || !this.acceptsPointer(e)) return;
    const page = this.page(pageEl.dataset.id);
    if (!page) return;
    e.preventDefault();
    try { pageEl.setPointerCapture(e.pointerId); } catch { /* the stroke goes on anyway */ }
    const pt = this.pagePoint(page, e);
    if (this.tool === 'eraser') {
      this.gesture = { type: 'erase', page, pointerId: e.pointerId, pointerType: e.pointerType,
        ids: new Set(), path: [], radius: this.eraserRadius };
      this.showEraserCursor(page, pt);
      this.eraseAt(pt);
    } else if (this.tool === 'lasso') {
      this.clearSelection();
      this.gesture = { type: 'lasso', page, pointerId: e.pointerId, pointerType: e.pointerType, points: [pt] };
    } else {
      const tool = this.tool === 'highlighter' ? 'highlighter' : 'pen';   // "shapes" writes like the pen
      const stroke = { id: uid(), tool, color: this.color,
        width: tool === 'highlighter' ? this.width * HIGHLIGHTER_FACTOR : this.width, points: [pt] };
      this.gesture = { type: 'draw', page, pointerId: e.pointerId, pointerType: e.pointerType, stroke,
        filtered: pt, lastRaw: pt, shapeTool: this.tool === 'shape', hold: { x: e.clientX, y: e.clientY } };
      if (!this.gesture.shapeTool) this.armHold(this.gesture);
      this.drawLive(page, stroke, 0);
    }
  }

  pointerMove(e) {
    const g = this.gesture;
    if (!g) { this.hoverEraser(e); return; }
    if (e.pointerId !== g.pointerId) return;
    e.preventDefault();
    const coalesced = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
    const points = (coalesced.length ? coalesced : [e]).map((ev) => this.pagePoint(g.page, ev));
    if (g.type === 'erase') {
      points.forEach((pt) => this.eraseAt(pt));
      this.showEraserCursor(g.page, points[points.length - 1]);
      return;
    }
    if (g.type === 'lasso') {
      for (const pt of points) {
        const last = g.points[g.points.length - 1];
        if (Math.hypot(pt[0] - last[0], pt[1] - last[1]) >= GESTURE_POINT_DIST) g.points.push(pt);
      }
      this.drawInk(g.page);
      return;
    }
    if (g.converted) return;   // already turned into a shape: it does not change while the pen stays down
    // Every real movement restarts the wait for the shape; hand tremor does not.
    if (Math.hypot(e.clientX - g.hold.x, e.clientY - g.hold.y) > HOLD_MOVE_PX) {
      g.hold = { x: e.clientX, y: e.clientY };
      g.holdRequest = null;      // the pen moved: a recognition in progress no longer counts
      if (!g.shapeTool) this.armHold(g);
    }
    const pts = g.stroke.points;
    const from = pts.length;
    for (const raw of points) {
      g.lastRaw = raw;
      const f = g.filtered;
      g.filtered = [f[0] + (raw[0] - f[0]) * (1 - STABILIZER), f[1] + (raw[1] - f[1]) * (1 - STABILIZER), raw[2]];
      const last = pts[pts.length - 1];
      if (Math.hypot(g.filtered[0] - last[0], g.filtered[1] - last[1]) >= MIN_POINT_DIST) {
        pts.push(g.filtered.map((n) => Math.round(n * 100) / 100));
      }
    }
    if (pts.length > from) this.drawLive(g.page, g.stroke, from);
  }

  pointerUp(e) {
    const g = this.gesture;
    if (!g || e.pointerId !== g.pointerId) return;
    this.gesture = null;
    if (g.type === 'draw') {
      clearTimeout(g.holdTimer);
      // The stroke ends exactly where the pen was lifted.
      const pts = g.stroke.points, last = pts[pts.length - 1], raw = g.lastRaw;
      if (!g.converted && raw && Math.hypot(raw[0] - last[0], raw[1] - last[1]) >= MIN_POINT_DIST) pts.push(raw);
      // It first becomes a "pending" stroke (visible until the controller confirms it),
      // then the page is redrawn with the last piece: this way the stroke never disappears.
      this.pendingStrokes.set(g.stroke.id, { page: g.page.id, stroke: g.stroke });
      this.drawInk(g.page);
      this.finishStroke(g);
    } else if (g.type === 'lasso') {
      this.drawInk(g.page);  // removes the dashed outline
      if (g.points.length >= 3) {
        const polygon = g.points.map(([x, y]) => [x, y]);
        this.send({ type: 'select', page: g.page.id, polygon }, { quiet: true });
      }
    } else {
      if (e.pointerType !== 'mouse') this.hideEraserCursor();  // the Pencil was lifted (the mouse stays over the page)
      this.flushErase(g).then(() => {
        // End of preview: only the strokes the controller really removed stay hidden.
        g.ids.forEach((id) => this.hiddenStrokes.delete(id));
        this.drawInk(g.page);
      });
    }
  }

  // --- geometric shapes ---------------------------------------------------------------
  // Wait for the shape: it restarts on every movement; if the Pencil stays still
  // for HOLD_MS without lifting, the stroke becomes the recognised shape.
  armHold(g) {
    clearTimeout(g.holdTimer);
    g.holdTimer = setTimeout(async () => {
      if (this.gesture !== g || g.stroke.points.length < 3) return;
      const request = g.holdRequest = this.recognize(g);
      const shape = await request;
      // Valid only if the pen has not moved in the meantime (holdRequest unchanged).
      if (g.holdRequest === request && this.applyShape(g, shape)) this.drawInk(g.page);
    }, HOLD_MS);
  }

  // Asks the controller which shape the stroke is. If it is not a shape, kind is null
  // and the stroke stays as drawn (you can keep writing).
  recognize(g) {
    let points = g.stroke.points.map(([x, y]) => [x, y]);
    if (points.length > SHAPE_MAX_POINTS) {
      const step = Math.ceil(points.length / SHAPE_MAX_POINTS);
      points = points.filter((_, i) => i % step === 0).concat([points[points.length - 1]]);
    }
    let shape = null;
    const tolerance = SNAP_PX / this.scale;
    return this.enqueue(async (session) => {
      const result = await apiPost('/api/edit/op',
        { session, op: { type: 'recognizeShape', page: g.page.id, points, tolerance } });
      shape = (result.events || []).find((ev) => ev.event === 'shape') || null;
      return result;
    }, { quiet: true }).then(() => shape);
  }

  // Replaces the freehand stroke with the shape (if the controller recognised one).
  applyShape(g, shape) {
    if (!shape?.kind || g.converted) return false;
    g.stroke.points = shape.points;
    g.stroke.shape = shape.kind;
    g.converted = true;
    return true;
  }

  // Pen lifted: with the Shapes tool the stroke becomes a shape right away; with the
  // pen only if the wait had already fired. Then the stroke goes to the controller.
  async finishStroke(g) {
    const request = g.shapeTool && g.stroke.points.length >= 2 ? this.recognize(g) : g.holdRequest;
    if (request && !g.converted) {
      // Wait already fired (pen) or Shapes tool: wait for the controller's answer.
      if (this.applyShape(g, await request)) this.drawInk(g.page);
    }
    this.send({ type: 'addStroke', page: g.page.id, stroke: g.stroke });
  }

  // Sends the eraser path to the controller (it decides which strokes to remove).
  flushErase(g) {
    const path = g.path.map(([x, y]) => [x, y]);
    g.path = g.path.slice(-1);
    return path.length ? this.send({ type: 'erase', page: g.page.id, path, radius: g.radius }) : Promise.resolve();
  }

  // Eraser circle: as large as the eraser, centred on the tip.
  showEraserCursor(page, pt) {
    const v = this.els.get(page.id);
    if (!v) return;
    const d = this.eraserRadius * 2 * this.scale;
    if (this.eraserCursor.parentElement !== v.el) v.el.append(this.eraserCursor);
    Object.assign(this.eraserCursor.style, { width: d + 'px', height: d + 'px',
      left: pt[0] * this.scale + 'px', top: pt[1] * this.scale + 'px' });
  }

  hideEraserCursor() {
    this.eraserCursor.remove();
  }

  hoverEraser(e) {
    const pageEl = this.tool === 'eraser' && ['pen', 'mouse'].includes(e.pointerType) && e.target.closest('.page');
    const page = pageEl && this.page(pageEl.dataset.id);
    if (page) this.showEraserCursor(page, this.pagePoint(page, e));
    else this.hideEraserCursor();
  }

  // A second finger turns the gesture into a zoom: the finger stroke is cancelled.
  abortFingerGesture() {
    const g = this.gesture;
    if (!g || g.pointerType !== 'touch') return;
    this.gesture = null;
    clearTimeout(g.holdTimer);
    if (g.type === 'erase') g.ids.forEach((id) => this.hiddenStrokes.delete(id));
    this.hideEraserCursor();
    this.drawInk(g.page);
  }

  // The eraser immediately hides the strokes it seems to touch (preview); the path
  // goes to the controller, which decides which strokes to really remove.
  eraseAt(pt) {
    const g = this.gesture;
    const { page, ids, path } = g;
    const last = path[path.length - 1];
    if (!last || Math.hypot(pt[0] - last[0], pt[1] - last[1]) >= GESTURE_POINT_DIST) path.push(pt);
    if (path.length >= GESTURE_MAX_POINTS) this.flushErase(g);
    const candidates = [...page.strokes, ...this.pendingOn(page)];
    let changed = false;
    for (const s of candidates) {
      if (!ids.has(s.id) && !this.hiddenStrokes.has(s.id) && touches(s, pt, g.radius)) {
        ids.add(s.id);
        this.hiddenStrokes.add(s.id);
        changed = true;
      }
    }
    if (changed) this.drawInk(page);
  }

  pageClick(e) {
    if (!['text', 'image'].includes(this.tool) || this.blocked || e.target.closest('.textbox, .imagebox, .selection')) return;
    const pageEl = e.target.closest('.page');
    const page = pageEl && this.page(pageEl.dataset.id);
    if (!page) return;
    if (document.activeElement?.tagName === 'TEXTAREA') { document.activeElement.blur(); return; }
    const [x, y] = this.pagePoint(page, e);
    if (this.tool === 'image') { this.pickImage({ page: page.id, x, y }); return; }
    this.focusNewText = true;  // the box created by the controller will receive the cursor
    this.send({ type: 'addText', page: page.id, x, y, color: this.color });
  }
}
