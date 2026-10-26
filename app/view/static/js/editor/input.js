// VIEW — editor, input from Apple Pencil, finger and mouse; strokes, geometric shapes (press and hold), eraser.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { apiPost, reportError } from '../api.js';
import { COLORS, HIGHLIGHTER_FACTOR, MIN_POINT_DIST, STABILIZER, HOLD_MS, HOLD_MOVE_PX, SNAP_PX, SHAPE_MAX_POINTS, GESTURE_POINT_DIST, GESTURE_MAX_POINTS, uid, ERASER_PREF, touches, isStylus,
  widthFromSlider, TEXT_SIZE_PREF, TOOL_KEYS, PREDICT_MS, PREDICT_MAX_PX, STAB_FULL_PX, STAB_NONE_PX } from './shared.js';

export class InputMethods {
  // =====================================================================
  // Input: Pencil, mouse, finger, buttons, keyboard
  // =====================================================================
  bindInput() {
    document.querySelectorAll('.tool[data-tool]').forEach((b) => b.addEventListener('click', () => this.selectTool(b.dataset.tool)));
    COLORS.forEach((color) => {
      const b = document.createElement('button');
      b.style.background = color;
      b.title = color;
      b.dataset.color = color;
      b.addEventListener('click', () => {
        this.color = color;
        this.showColor();
        // With items selected (or a text box active), the chosen colour applies to them.
        if (this.hasSelection()) this.send({ type: 'recolorSelection', ...this.selectionPayload(), color });
        if (this.activeText) this.styleActiveText({ color });
      });
      this.colorsEl.append(b);
    });
    // Stroke thickness: standard sizes, or the slider (custom, for each tool).
    const widthInput = document.getElementById('width');
    widthInput.addEventListener('input', () => this.setCustomWidth(widthFromSlider(Number(widthInput.value)), false));
    widthInput.addEventListener('change', () => this.setCustomWidth(widthFromSlider(Number(widthInput.value)), true));
    document.querySelectorAll('#width-presets [data-width]').forEach((b) =>
      b.addEventListener('click', () => this.chooseWidth(b.dataset.width)));
    // Font size: of the active text box, and of the next ones created.
    const sizeInput = document.getElementById('text-size');
    sizeInput.addEventListener('input', () => {
      const size = Number(sizeInput.value);
      this.showTextSize(size);
      if (this.activeText) this.styleActiveText({ size }, false);
      else this.textSize = size;
    });
    sizeInput.addEventListener('change', () => {
      const size = Number(sizeInput.value);
      if (this.activeText) this.styleActiveText({ size });
      this.textSize = size;
      try { localStorage.setItem(TEXT_SIZE_PREF, String(size)); } catch { /* no storage available */ }
    });
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
      if (!this.session || this.element.hidden || document.querySelector('dialog[open]')) return;
      // Esc leaves the text box (and the lasso selection): then the letters choose the tools.
      if (e.key === 'Escape') {
        if (this.activeText || this.hasSelection()) e.preventDefault();
        this.deactivateText();
        this.clearSelection();
        return;
      }
      const t = e.target;
      if (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if ((key === 'delete' || key === 'backspace') && this.hasSelection()) {
        e.preventDefault();
        this.removeSelection();
      } else if (mod && key === 'z') { e.preventDefault(); this.send({ type: e.shiftKey ? 'redo' : 'undo' }); }
      else if (mod && key === 'y') { e.preventDefault(); this.send({ type: 'redo' }); }
      else if (!mod && !e.altKey && TOOL_KEYS[key]) { e.preventDefault(); this.selectTool(TOOL_KEYS[key]); }
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

    // An error while handling the Pencil must never leave a stroke "open" (the pen
    // would stop writing until the page is reloaded): the gesture is closed and
    // the editor goes on.
    const safe = (handler) => (e) => {
      try { handler.call(this, e); } catch (err) { this.recoverInput(err); }
    };
    this.pagesEl.addEventListener('pointerdown', safe(this.pointerDown));
    this.pagesEl.addEventListener('pointermove', safe(this.pointerMove));
    this.pagesEl.addEventListener('pointerup', safe(this.pointerUp));
    this.pagesEl.addEventListener('pointercancel', safe(this.pointerUp));
    // The pen side button is a "right click": no browser menu over the pages.
    this.pagesEl.addEventListener('contextmenu', (e) => e.preventDefault());
    // Safari can lose the pointer capture without sending "pointerup": the stroke
    // ends there instead of staying open.
    this.pagesEl.addEventListener('lostpointercapture', safe((e) => {
      if (this.gesture && e.pointerId === this.gesture.pointerId) this.pointerUp(e);
    }));
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
      resizeTimer = setTimeout(() => { if (this.ready) { this.computeScale(); this.buildPages(); } }, 200);
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

  // Point of the page under the pointer (PDF points). rect: the page's position,
  // read once per stroke (reading it for every Pencil sample slows the stroke down).
  pagePoint(page, e, rect = this.els.get(page.id).el.getBoundingClientRect()) {
    return [
      (e.clientX - rect.left) / this.scale,
      (e.clientY - rect.top) / this.scale,
      e.pressure > 0 ? Math.round(e.pressure * 1000) / 1000 : 0.5,
    ];
  }

  pointerDown(e) {
    // Side button of the pens that have one: eraser, and pressed again back to the
    // previous tool. For the browser it is a "right click" of the pen.
    if (e.pointerType === 'pen' && (e.button === 2 || (e.buttons & 2))) {
      e.preventDefault();
      if (!this.gesture) this.togglePenEraser();
      return;
    }
    // Eraser end of the pens that have one: it erases while it touches, then the
    // tool in use stays the same.
    const tool = e.pointerType === 'pen' && (e.button === 5 || (e.buttons & 32)) ? 'eraser' : this.tool;
    const pageEl = e.target.closest('.page');
    if (!pageEl || this.gesture || this.blocked || e.target.closest('.textbox, .imagebox, .selection')) return;
    if (['text', 'image'].includes(tool) || !this.acceptsPointer(e)) return;
    const page = this.page(pageEl.dataset.id);
    if (!page) return;
    e.preventDefault();
    try { pageEl.setPointerCapture(e.pointerId); } catch { /* the stroke goes on anyway */ }
    const rect = pageEl.getBoundingClientRect();
    const pt = this.pagePoint(page, e, rect);
    if (tool === 'eraser') {
      this.gesture = { type: 'erase', page, rect, pointerId: e.pointerId, pointerType: e.pointerType,
        ids: new Set(), newIds: new Set(), path: [], radius: this.eraserRadius };
      this.showEraserCursor(page, pt);
      this.eraseAt(pt);
    } else if (tool === 'lasso') {
      this.clearSelection();
      this.gesture = { type: 'lasso', page, rect, pointerId: e.pointerId, pointerType: e.pointerType, points: [pt] };
    } else {
      const tool = this.tool === 'highlighter' ? 'highlighter' : 'pen';   // "shapes" writes like the pen
      const stroke = { id: uid(), tool, color: this.color,
        width: tool === 'highlighter' ? this.width * HIGHLIGHTER_FACTOR : this.width, points: [pt] };
      this.gesture = { type: 'draw', page, rect, pointerId: e.pointerId, pointerType: e.pointerType, stroke,
        filtered: pt, lastRaw: pt, tip: pt, shapeTool: this.tool === 'shape', hold: { x: e.clientX, y: e.clientY },
        motion: { x: e.clientX, y: e.clientY, t: e.timeStamp, vx: 0, vy: 0 } };
      if (!this.gesture.shapeTool) this.armHold(this.gesture);
      this.startLive(this.gesture);
      this.drawLive(this.gesture);
    }
  }

  pointerMove(e) {
    const g = this.gesture;
    if (!g) { this.hoverEraser(e); return; }
    if (e.pointerId !== g.pointerId) return;
    e.preventDefault();
    const coalesced = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
    const samples = coalesced.length ? coalesced : [e];
    const points = samples.map((ev) => this.pagePoint(g.page, ev, g.rect));
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
    for (const raw of points) {
      g.lastRaw = raw;
      const f = g.filtered;
      const jump = Math.hypot(raw[0] - f[0], raw[1] - f[1]) * this.scale;   // on screen
      const k = STABILIZER * Math.min(1, Math.max(0, (STAB_NONE_PX - jump) / (STAB_NONE_PX - STAB_FULL_PX)));
      g.filtered = [f[0] + (raw[0] - f[0]) * (1 - k), f[1] + (raw[1] - f[1]) * (1 - k), raw[2]];
      const last = pts[pts.length - 1];
      if (Math.hypot(g.filtered[0] - last[0], g.filtered[1] - last[1]) >= MIN_POINT_DIST) {
        pts.push(g.filtered.map((n) => Math.round(n * 100) / 100));
      }
    }
    // The preview reaches the tip and a little beyond: where the browser predicts
    // the Pencil is going or, if it does not, where the current speed takes it in
    // a few milliseconds (at most a few pixels). This hides part of the delay of
    // the screen; the extra bit is redrawn at every movement and never saved.
    const predicted = e.getPredictedEvents ? e.getPredictedEvents() : [];
    if (predicted.length) {
      g.tip = this.pagePoint(g.page, predicted[predicted.length - 1], g.rect);
    } else {
      g.tip = this.predictTip(g, samples[samples.length - 1]);
    }
    this.drawLive(g);
  }

  // Pen side button: to the eraser, and back to the tool used before.
  togglePenEraser() {
    if (this.tool === 'eraser') {
      this.selectTool(this.toolBeforeEraser || 'pen');
      this.toolBeforeEraser = null;
    } else {
      this.toolBeforeEraser = this.tool;
      this.selectTool('eraser');
    }
  }

  // Tip a little ahead of the last sample, following the (smoothed) speed.
  predictTip(g, ev) {
    const m = g.motion;
    const dt = ev.timeStamp - m.t;
    if (dt > 0 && dt < 100) {
      const k = Math.min(1, dt / 16);          // speed smoothed over about one frame
      m.vx += ((ev.clientX - m.x) / dt - m.vx) * k;
      m.vy += ((ev.clientY - m.y) / dt - m.vy) * k;
    }
    m.x = ev.clientX; m.y = ev.clientY; m.t = ev.timeStamp;
    let dx = m.vx * PREDICT_MS, dy = m.vy * PREDICT_MS;
    const len = Math.hypot(dx, dy);
    if (len > PREDICT_MAX_PX) { dx *= PREDICT_MAX_PX / len; dy *= PREDICT_MAX_PX / len; }
    const raw = g.lastRaw;
    return [raw[0] + dx / this.scale, raw[1] + dy / this.scale, raw[2]];
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
      this.endLive(g.page);
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
      if (g.holdRequest === request && this.applyShape(g, shape)) {
        if (this.gesture === g) this.drawLive(g); else this.drawInk(g.page);
      }
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
  // The stroke takes its place in the queue at once, when the pen is lifted: an
  // eraser or undo that follows reaches the controller after it, even when the
  // shape recognition is still on its way (otherwise the eraser would find
  // nothing to erase and the stroke would reappear).
  finishStroke(g) {
    const request = g.shapeTool && g.stroke.points.length >= 2 ? this.recognize(g) : g.holdRequest;
    this.enqueue(async (session) => {
      // The recognition was queued before this request: here it is already answered.
      if (request && !g.converted && this.applyShape(g, await request)) this.drawInk(g.page);
      return apiPost('/api/edit/op', { session, op: { type: 'addStroke', page: g.page.id, stroke: g.stroke } });
    });
  }

  // Sends the eraser path to the controller (it decides which strokes to remove),
  // with the strokes already hidden here: it confirms them if the path really
  // reaches them (see ERASE_TOLERANCE in the controller).
  flushErase(g) {
    const path = g.path.map(([x, y]) => [x, y]);
    g.path = g.path.slice(-1);
    const ids = [...g.newIds];
    g.newIds.clear();
    return path.length ? this.send({ type: 'erase', page: g.page.id, path, radius: g.radius, ids }) : Promise.resolve();
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

  // Unexpected error during a gesture: it is closed without sending it, and the
  // page is redrawn from the data (what was already sent stays).
  recoverInput(err) {
    console.error(err);
    reportError(err?.message || err, 'editor input', err?.stack);
    const g = this.gesture;
    this.gesture = null;
    if (!g) return;
    clearTimeout(g.holdTimer);
    if (g.type === 'erase') g.ids.forEach((id) => this.hiddenStrokes.delete(id));
    try {
      if (g.type === 'draw') this.endLive(g.page);
      this.hideEraserCursor();
      this.drawInk(g.page);
    } catch (e) { console.error(e); }
  }

  // A second finger turns the gesture into a zoom: the finger stroke is cancelled.
  abortFingerGesture() {
    const g = this.gesture;
    if (!g || g.pointerType !== 'touch') return;
    this.gesture = null;
    clearTimeout(g.holdTimer);
    if (g.type === 'erase') g.ids.forEach((id) => this.hiddenStrokes.delete(id));
    if (g.type === 'draw') this.endLive(g.page);
    this.hideEraserCursor();
    this.drawInk(g.page);
  }

  // The eraser immediately hides the strokes it seems to touch (preview); the path
  // goes to the controller, which decides which strokes to really remove.
  eraseAt(pt) {
    const g = this.gesture;
    const { page, ids, path } = g;
    const last = path[path.length - 1];
    const far = !last || Math.hypot(pt[0] - last[0], pt[1] - last[1]) >= GESTURE_POINT_DIST;
    if (far) path.push(pt);
    const candidates = [...page.strokes, ...this.pendingOn(page)];
    let changed = false;
    for (const s of candidates) {
      if (!ids.has(s.id) && !this.hiddenStrokes.has(s.id) && touches(s, pt, g.radius)) {
        ids.add(s.id);
        g.newIds.add(s.id);
        this.hiddenStrokes.add(s.id);
        changed = true;
      }
    }
    // A point that touched something always goes to the controller, even if it is
    // close to the previous one: the stroke hidden here must be erased there too.
    if (changed && !far && (pt[0] !== last[0] || pt[1] !== last[1])) path.push(pt);
    if (path.length >= GESTURE_MAX_POINTS) this.flushErase(g);
    if (changed) this.drawInk(page);
  }

  pageClick(e) {
    if (!['text', 'image'].includes(this.tool) || this.blocked || e.target.closest('.textbox, .imagebox, .selection')) return;
    const pageEl = e.target.closest('.page');
    const page = pageEl && this.page(pageEl.dataset.id);
    if (!page) return;
    // A tap outside the active box leaves it (it does not create a new one).
    if (this.activeText || document.activeElement?.tagName === 'TEXTAREA') {
      this.deactivateText();
      document.activeElement?.blur?.();
      return;
    }
    const [x, y] = this.pagePoint(page, e);
    if (this.tool === 'image') { this.pickImage({ page: page.id, x, y }); return; }
    this.focusNewText = true;  // the box created by the controller will receive the cursor
    this.send({ type: 'addText', page: page.id, x, y, color: this.color, size: this.textSize });
  }

  selectTool(tool) {
    this.tool = tool;
    if (tool !== 'lasso') this.clearSelection();
    this.showTool();
  }
}
