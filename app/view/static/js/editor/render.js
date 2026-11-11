// VIEW — editor, drawing: PDF background in regions (strong zoom too), saved strokes and stroke preview.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { HIGHLIGHT_ALPHA, MAX_CANVAS_PIXELS, REGION_SIDE, REGION_MAX_AHEAD, REGION_AHEAD_SHARE, REGION_GUARD,
  COARSE_PIXELS, TAIL_BOX, CANVAS_BUDGET } from './shared.js';

const strokeBounds = new WeakMap();   // points array → bounding box (see strokeTouches)

export class RenderMethods {
  // Part of the page to draw, in CSS pixels relative to the page, and resolution
  // r (canvas pixels per CSS pixel). null = nothing to draw now.
  // With strong zoom the whole page does not fit a canvas: the region is the
  // visible part plus a margin, as large as the canvas allows, mostly in the
  // direction the sheet is moving (see visiblePart).
  renderRegion(page, v) {
    const dpr = window.devicePixelRatio || 1;
    const W = page.w * this.scale, H = page.h * this.scale;
    if (W * H * dpr * dpr <= MAX_CANVAS_PIXELS) return { x: 0, y: 0, w: W, h: H, r: dpr, full: true };
    const vis = this.visiblePart(page, v);
    if (!vis) return null;
    const area = MAX_CANVAS_PIXELS / (dpr * dpr);       // CSS pixels the canvas can hold
    const vr = this.pagesEl.getBoundingClientRect();
    let mx = Math.round(vr.width * REGION_SIDE), my = 0;
    if ((vis.w + 2 * mx) * vis.h > area) mx = 0;
    if (vis.w * vis.h <= area) {
      my = Math.min(Math.round(vr.height * REGION_MAX_AHEAD), Math.floor((area / (vis.w + 2 * mx) - vis.h) / 2));
    }
    const region = this.visiblePart(page, v, mx, my);
    if (region.w * region.h <= area) return { ...region, r: dpr, full: false, mx, my };
    // Even the visible part alone is too large: lower the resolution a little.
    return { ...region, r: Math.sqrt(area / (region.w * region.h)) * dpr, full: false, mx, my };
  }

  // Part of the page that is on screen, widened by mx pixels at the sides and 2·my
  // pixels vertically: more ahead of the movement than behind it (dir, see bindInput).
  visiblePart(page, v, mx = 0, my = 0) {
    const pr = v.el.getBoundingClientRect(), vr = this.pagesEl.getBoundingClientRect();
    const W = page.w * this.scale, H = page.h * this.scale;
    const dir = this.scrollDir?.y || 0;
    const ahead = Math.round(2 * my * REGION_AHEAD_SHARE), behind = 2 * my - ahead;
    const above = dir < 0 ? ahead : dir > 0 ? behind : my, below = 2 * my - above;
    const x0 = Math.max(0, Math.floor(vr.left - mx - pr.left)), y0 = Math.max(0, Math.floor(vr.top - above - pr.top));
    const x1 = Math.min(W, Math.ceil(vr.right + mx - pr.left)), y1 = Math.min(H, Math.ceil(vr.bottom + below - pr.top));
    return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
  }

  // Sizes a canvas to the region and positions it over that part of the page.
  placeCanvas(canvas, region) {
    if (!region) { canvas.width = canvas.height = 0; return; }
    canvas.width = Math.round(region.w * region.r);
    canvas.height = Math.round(region.h * region.r);
    this.placeStyle(canvas, region);
  }

  placeStyle(canvas, region) {
    Object.assign(canvas.style, { left: region.x + 'px', top: region.y + 'px', width: region.w + 'px', height: region.h + 'px' });
  }

  // Canvas that shows a finished background drawing, without copying it on the
  // main thread (copying millions of pixels there is what made the sheet stop
  // while scrolling with strong zoom): the worker's image is handed over to the
  // canvas as it is; a canvas drawn here (no worker) is used directly. null (white
  // page): an empty canvas, the page itself is white.
  canvasFor(image, region) {
    let c;
    if (image && typeof HTMLCanvasElement !== 'undefined' && image instanceof HTMLCanvasElement) {
      c = image;
    } else {
      c = document.createElement('canvas');
      if (image) {
        c.width = image.width;
        c.height = image.height;
        const ctx = c.getContext('bitmaprenderer');
        if (ctx) ctx.transferFromImageBitmap(image);
        else { c.getContext('2d').drawImage(image, 0, 0); image.close?.(); }
      } else {
        c.width = c.height = 0;
      }
    }
    this.placeStyle(c, region);
    return c;
  }

  // While a finger moves the sheet (or it slides on), drawing a page that is not
  // yet on screen waits until the movement stops: drawing the background and the
  // strokes takes the browser's attention, and the sheet would stop with it.
  // A page actually on screen is drawn at once (blank is worse than a pause).
  scrolling() {
    return !!this.finger?.moved || performance.now() - (this.lastScrollAt || 0) < 150;
  }

  // The sheet is moving, in any way (finger, sliding, mouse wheel, trackpad, the
  // pen's button): the strokes of a new region are drawn by their worker.
  movingSheet() {
    return this.scrolling() || this.gesture?.type === 'pan';
  }

  onScreen(v) {
    const r = v.el.getBoundingClientRect(), view = this.pagesEl.getBoundingClientRect();
    return r.bottom > view.top && r.top < view.bottom && r.right > view.left && r.left < view.right;
  }

  // Pages whose drawing was put off: drawn now (if still near the screen).
  flushDeferred() {
    const deferred = this.deferredRenders;
    if (deferred?.size) {
      this.deferredRenders = new Set();
      const view = this.pagesEl.getBoundingClientRect();
      for (const id of deferred) {
        const page = this.page(id), v = page && this.els.get(id);
        if (!v || v.rendered) continue;
        const r = v.el.getBoundingClientRect();
        if (r.bottom > view.top - 1200 && r.top < view.bottom + 1200) this.renderPage(page, v);
      }
    }
    this.checkRegions();
  }

  // Where the painter finds the background of a page: {key, index} or null (white page).
  async backgroundSource(page) {
    if (page.bg) {
      // Page of a background (downloaded once, then kept on this device).
      if (await this.bgDocs.get(page.bg.id)) return { key: 'bg:' + page.bg.id, index: page.bg.page };
    } else if (page.layout && page.layout !== 'blank') {
      // Untouched layout page (blank, lined…): drawn from the small layout page.
      const key = await this.layoutPdf(page);
      if (key) return { key, index: 0 };
    }
    return null;
  }

  // Draws the page (again): strokes at once, background when the painter is done.
  renderPage(page, v) {
    // With the painter on the main thread only (no worker), drawing while the
    // sheet moves would make it stutter: it waits (see scrolling).
    if (!this.painter.offThread && this.scrolling() && !this.onScreen(v)) {
      (this.deferredRenders ||= new Set()).add(page.id);
      return;
    }
    v.rendered = true;
    const region = this.renderRegion(page, v);
    this.moveInk(page, v, region);
    v.task?.cancel();                  // the background drawing in progress is for another zoom or position
    v.task = null;
    v.shown = null;                    // the base canvas still shows the old drawing, if any
    if (!region) { this.placeCanvas(v.base, null); this.placeCanvas(v.coarse, null); v.coarseScale = 0; return; }
    if (region.full) { this.placeCanvas(v.coarse, null); v.coarseScale = 0; }
    else if (v.coarseScale !== this.scale) this.renderCoarse(page, v);
    this.renderBase(page, v, region);
  }

  // The strokes canvas moves to a new region. While the sheet is scrolling, the
  // strokes of the new region are drawn by their worker (see ink_worker.js) and
  // shown when ready, like the background: drawing them here would stop the
  // sheet. Otherwise (and while the page is being written on, or without the
  // worker) they are drawn here at once.
  moveInk(page, v, region) {
    v.inkTask?.cancel();
    v.inkTask = null;
    if (region && this.movingSheet() && !this.inkBusy(page)) {
      const { strokes, points } = this.packInk(page, region);
      const scale = this.scale;
      const task = this.painter.ink({ x: region.x, y: region.y, w: region.w, h: region.h, r: region.r, scale,
        alpha: HIGHLIGHT_ALPHA, strokes, points });
      if (task) {
        const version = v.inkVersion || 0;
        v.inkTask = task;
        task.promise.then((bitmap) => {
          if (v.inkTask !== task) { bitmap.close?.(); return; }
          v.inkTask = null;
          // Strokes changed meanwhile (drawn here in the old region), or a new zoom:
          // the image is out of date; the next check asks for a new one.
          if (!v.rendered || (v.inkVersion || 0) !== version || this.scale !== scale || this.els.get(page.id) !== v) {
            bitmap.close?.();
            if (v.rendered) this.checkRegions(v);
            return;
          }
          const next = this.canvasFor(bitmap, region);
          next.className = 'ink';
          this.freeCanvas(v.ink);
          v.ink.replaceWith(next);
          v.ink = next;
          v.inkBitmap = true;          // an image: drawn again here before any change (see drawInk)
          v.region = region;
          this.checkRegions(v);        // the sheet may have moved on meanwhile
        }, (err) => {
          if (v.inkTask !== task) return;
          v.inkTask = null;
          if (!err?.cancelled) { console.error(err); this.placeInk(page, v, region); }
        });
        return;
      }
    }
    this.placeInk(page, v, region);
  }

  // The page is being worked on (a stroke, the eraser, the lasso, a selection):
  // its strokes are drawn here, where the changes are.
  inkBusy(page) {
    return this.selection?.page === page.id || (this.gesture?.page && this.gesture.page.id === page.id);
  }

  // Strokes of the region for the worker: their style, and all the points in one
  // array that moves to the worker without being copied.
  packInk(page, region) {
    const k = this.scale;
    const box = region.full ? null : { x0: region.x / k, y0: region.y / k, x1: (region.x + region.w) / k, y1: (region.y + region.h) / k };
    const list = [];
    let total = 0;
    for (const st of [...page.strokes, ...this.pendingOn(page)]) {
      if (this.hiddenStrokes.has(st.id) || (box && !this.strokeTouches(st, box))) continue;
      list.push(st);
      total += st.points.length;
    }
    const points = new Float32Array(total * 2);
    let o = 0;
    const strokes = list.map((st) => {
      for (const pt of st.points) { points[o++] = pt[0]; points[o++] = pt[1]; }
      return { n: st.points.length, color: st.color, width: st.width, hl: st.tool === 'highlighter', shape: !!st.shape };
    });
    return { strokes, points };
  }

  // The strokes canvas covers the region at once, drawn here.
  // The canvas is resized only when the region's size changes (a new size means new
  // memory and a cleared canvas); otherwise it is just moved and drawn again.
  placeInk(page, v, region) {
    v.inkTask?.cancel();
    v.inkTask = null;
    v.region = region;
    if (!region) { this.placeCanvas(v.ink, null); return; }
    if (v.inkBitmap) this.inkCanvas(v);
    const w = Math.round(region.w * region.r), h = Math.round(region.h * region.r);
    if (v.ink.width !== w || v.ink.height !== h) { v.ink.width = w; v.ink.height = h; }
    this.placeStyle(v.ink, region);
    this.drawInk(page);
  }

  // The background of the region is drawn on a new canvas and replaces the old one
  // only when finished: the previous drawing stays visible meanwhile.
  async renderBase(page, v, region) {
    const id = (v.renderId = (v.renderId || 0) + 1);
    const task = { region, cancel: () => { task.inner?.cancel(); } };
    v.task = task;
    let source = null;
    try { source = await this.backgroundSource(page); } catch (err) { console.error(err); }
    if (v.renderId !== id || !v.rendered || this.els.get(page.id) !== v) return;  // superseded by a newer drawing
    let image = null;
    if (source) {
      try {
        task.inner = this.painter.render(source.key, source.index, { scale: this.scale, x: region.x, y: region.y, w: region.w, h: region.h, r: region.r });
        image = await task.inner.promise;
      } catch (err) {
        if (!err?.cancelled) console.error(err);
        return;
      }
    }
    if (v.renderId !== id || !v.rendered) { image?.close?.(); return; }
    const next = this.canvasFor(image, region);
    this.freeCanvas(v.base);
    v.base.replaceWith(next);
    v.base = next;
    v.shown = region;
    v.task = null;
    this.enforceCanvasBudget(v);
    this.firstDrawn?.();          // the first page is visible: the opening progress bar finishes
    this.firstDrawn = null;
    if (!region.full) this.checkRegions(v);   // the sheet may have moved on meanwhile
  }

  // Whole page at a low resolution, under the sharp regions (strong zoom only).
  async renderCoarse(page, v) {
    const scale = this.scale;
    v.coarseScale = scale;
    const W = page.w * scale, H = page.h * scale;
    const region = { x: 0, y: 0, w: W, h: H, r: Math.min(window.devicePixelRatio || 1, Math.sqrt(COARSE_PIXELS / (W * H))) };
    let source = null;
    try { source = await this.backgroundSource(page); } catch (err) { console.error(err); }
    if (v.coarseScale !== scale || !v.rendered || this.els.get(page.id) !== v) return;
    let image = null;
    if (source) {
      try {
        v.coarseTask?.cancel();
        v.coarseTask = this.painter.render(source.key, source.index, { scale, x: 0, y: 0, w: W, h: H, r: region.r });
        image = await v.coarseTask.promise;
      } catch (err) {
        if (!err?.cancelled) console.error(err);
        return;
      }
    }
    if (v.coarseScale !== scale || !v.rendered || this.els.get(page.id) !== v) { image?.close?.(); return; }
    const next = this.canvasFor(image, region);
    next.className = 'coarse';
    this.freeCanvas(v.coarse);
    v.coarse.replaceWith(next);
    v.coarse = next;
  }

  // Scrolling with strong zoom: when the visible part comes close to the edge of
  // the drawn region (or leaves it), the strokes are moved at once and a new
  // background is asked for. A background drawing already under way is left to
  // finish (cancelling it at every movement would never show anything): the
  // check runs again when it is done. Runs during the scrolling too, once per frame.
  checkRegions(only = null) {
    for (const page of this.pages) {
      const v = this.els.get(page.id);
      if (!v?.rendered || v.region?.full || (only && v !== only)) continue;
      const r = v.region;
      if (!r) { if (!v.inkTask && !v.task && this.onScreen(v)) this.renderPage(page, v); continue; }
      const want = this.visiblePart(page, v, Math.round(r.mx * REGION_GUARD), Math.round(r.my * REGION_GUARD));
      if (!want) continue;
      const inside = (a) => a && want.x >= a.x && want.y >= a.y && want.x + want.w <= a.x + a.w && want.y + want.h <= a.y + a.h;
      if (inside(r) && (inside(v.shown) || v.task)) continue;
      const region = this.renderRegion(page, v);
      if (!region) continue;
      if (!inside(r) && !v.inkTask) this.moveInk(page, v, region);
      if (!v.task) this.renderBase(page, v, region);
    }
  }

  releasePage(v) {
    v.rendered = false;
    v.region = null;
    v.shown = null;
    v.coarseScale = 0;
    v.renderId = (v.renderId || 0) + 1;
    v.task?.cancel();
    v.task = null;
    v.coarseTask?.cancel();
    v.inkTask?.cancel();
    v.inkTask = null;
    for (const c of [v.base, v.coarse, v.ink, v.live]) this.freeCanvas(c);
  }

  // Page taken off the screen for good (removed, or pages rebuilt): its canvases
  // are freed at once.
  discardPage(v) {
    v.task?.cancel();
    v.coarseTask?.cancel();
    v.inkTask?.cancel();
    v.inkTask = null;
    v.renderId = (v.renderId || 0) + 1;
    for (const c of [v.base, v.coarse, v.ink, v.live, v.tail]) this.freeCanvas(c);
  }

  // Memory limit for the pages' canvases: Safari on the iPad reloads (or blanks)
  // a page whose canvases together use too much memory. When the drawn pages
  // exceed CANVAS_BUDGET pixels, those off the screen are released, the
  // farthest first (they are drawn again when they come back near).
  enforceCanvasBudget(keep) {
    const drawn = [...this.els.values()].filter((v) => v.rendered);
    const pixels = (v) => v.base.width * v.base.height + v.ink.width * v.ink.height + v.coarse.width * v.coarse.height;
    let total = drawn.reduce((sum, v) => sum + pixels(v), 0);
    if (total <= CANVAS_BUDGET) return;
    const view = this.pagesEl.getBoundingClientRect();
    const centre = (view.top + view.bottom) / 2;
    const far = drawn.filter((v) => v !== keep).map((v) => {
      const r = v.el.getBoundingClientRect();
      return { v, onScreen: r.bottom > view.top && r.top < view.bottom, dist: Math.abs((r.top + r.bottom) / 2 - centre) };
    }).filter((x) => !x.onScreen).sort((a, b) => b.dist - a.dist);
    for (const { v } of far) {
      if (total <= CANVAS_BUDGET) break;
      total -= pixels(v);
      this.releasePage(v);
    }
  }

  // The strokes canvas shows an image from the worker: it becomes a normal canvas
  // again (of the region's size) to be drawn on here.
  // copy: the image is copied onto it (quick), instead of drawing all the strokes again.
  inkCanvas(v, copy = false) {
    const c = document.createElement('canvas');
    c.className = 'ink';
    c.width = Math.round(v.region.w * v.region.r);
    c.height = Math.round(v.region.h * v.region.r);
    this.placeStyle(c, v.region);
    if (copy) c.getContext('2d').drawImage(v.ink, 0, 0);
    this.freeCanvas(v.ink);
    v.ink.replaceWith(c);
    v.ink = c;
    v.inkBitmap = false;
  }

  // Context of the strokes canvas, with coordinates in PDF points.
  inkContext(v) {
    const ctx = v.ink.getContext('2d');
    const { x, y, r } = v.region;
    const k = this.scale * r;
    ctx.setTransform(k, 0, 0, k, -x * r, -y * r);
    return ctx;
  }

  strokeStyle(ctx, s) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.width;
    ctx.globalAlpha = s.tool === 'highlighter' ? HIGHLIGHT_ALPHA : 1;
    ctx.globalCompositeOperation = s.tool === 'highlighter' ? 'multiply' : 'source-over';
  }

  // The stroke goes through the points with smooth curves (quadratic Béziers
  // between the midpoints of consecutive samples), not straight segments: no "corners" in curves.
  drawStroke(ctx, s) {
    this.strokeStyle(ctx, s);
    const pts = s.points;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    if (s.shape) {                     // geometric shape: straight segments, sharp corners
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.stroke();
      return;
    }
    if (pts.length === 1) ctx.lineTo(pts[0][0] + 0.01, pts[0][1] + 0.01);
    for (let i = 1; i < pts.length - 1; i++) {
      ctx.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2);
    }
    if (pts.length > 1) ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
    ctx.stroke();
  }

  // Whether the stroke's bounding box (kept with its points, which never change
  // once the stroke is finished) overlaps the box, in PDF points.
  strokeTouches(s, box) {
    let b = strokeBounds.get(s.points);
    if (!b) {
      b = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
      for (const [x, y] of s.points) {
        if (x < b.x0) b.x0 = x; if (x > b.x1) b.x1 = x;
        if (y < b.y0) b.y0 = y; if (y > b.y1) b.y1 = y;
      }
      strokeBounds.set(s.points, b);
    }
    const pad = s.width / 2 + 4;
    return b.x1 + pad >= box.x0 && b.x0 - pad <= box.x1 && b.y1 + pad >= box.y0 && b.y0 - pad <= box.y1;
  }

  pendingOn(page) {
    return [...this.pendingStrokes.values()].filter((p) => p.page === page.id).map((p) => p.stroke);
  }

  // Redraws the page's strokes: confirmed + pending (the one in progress is on
  // its own layer, see drawLive).
  drawInk(page) {
    const v = this.els.get(page.id);
    if (!v?.rendered || !v.region) return;
    if (v.inkBitmap) this.inkCanvas(v);
    v.inkVersion = (v.inkVersion || 0) + 1;     // an image of the strokes on its way is now out of date
    const ctx = this.inkContext(v);
    ctx.clearRect(0, 0, page.w, page.h);
    const sel = this.selection?.page === page.id ? this.selection : null;
    // With strong zoom only the strokes that touch the drawn region are drawn: a
    // page full of strokes is redrawn quickly while the sheet scrolls.
    const r = v.region, k = this.scale;
    const box = r.full ? null : { x0: r.x / k, y0: r.y / k, x1: (r.x + r.w) / k, y1: (r.y + r.h) / k };
    for (const s of [...page.strokes, ...this.pendingOn(page)]) {
      if (this.hiddenStrokes.has(s.id)) continue;
      if (box && !sel?.strokes.has(s.id) && !this.strokeTouches(s, box)) continue;
      if (sel?.strokes.has(s.id)) {
        // Selected stroke: light-blue halo, and it follows the finger while dragging.
        ctx.save();
        ctx.translate(sel.dx, sel.dy);
        this.drawStroke(ctx, { ...s, tool: 'pen', color: '#b9d3ff', width: s.width + 6 });
        this.drawStroke(ctx, s);
        ctx.restore();
      } else {
        this.drawStroke(ctx, s);
      }
    }
    const g = this.gesture;
    // The pen stroke in progress is drawn on this canvas (see drawLive): a redraw
    // during the stroke (e.g. a change from another device) keeps it.
    if (g?.type === 'draw' && g.page.id === page.id && !g.onLive) this.drawStroke(ctx, g.stroke);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  // Lasso outline while it is being drawn: a dashed line on a layer of its own
  // above the page (SVG, in PDF points), to which every movement only adds its
  // points. Drawing it on the strokes canvas meant drawing all the page's strokes
  // again at every movement of the pen, and with many strokes (strong zoom above
  // all) the outline lagged behind the pen.
  startLasso(g) {
    const v = this.els.get(g.page.id);
    if (!v) return;
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'lasso');
    svg.setAttribute('viewBox', `0 0 ${g.page.w} ${g.page.h}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    const line = document.createElementNS(NS, 'polyline');
    line.setAttribute('vector-effect', 'non-scaling-stroke');   // width and dashes in screen pixels, at any zoom
    svg.append(line);
    v.el.append(svg);
    Object.assign(g, { svg, line, shown: 0 });
    this.drawLasso(g);
  }

  drawLasso(g) {
    const { svg, line } = g;
    if (!line) return;
    const list = line.points;
    for (; g.shown < g.points.length; g.shown++) {
      const [x, y] = g.points[g.shown];
      if (list?.appendItem && svg.createSVGPoint) {
        const p = svg.createSVGPoint();
        p.x = x; p.y = y;
        list.appendItem(p);
      } else {
        line.setAttribute('points', `${line.getAttribute('points') || ''} ${x},${y}`);
      }
    }
  }

  endLasso(g) {
    g.svg?.remove();
    g.svg = g.line = null;
  }

  // Preview of the stroke while the pen moves (immediately, without waiting for
  // the computer). The curve is drawn a piece at a time as the points arrive
  // (never redrawn whole, so long strokes cost as little as short ones): the pen
  // directly on the strokes canvas; the highlighter on a canvas of its own above
  // it, drawn opaque and made transparent by the canvas itself (the pieces
  // overlap without darker joints).
  // The last stretch, from the end of the curve to the tip of the Pencil (and a
  // little ahead, see input.js), is on a small canvas that follows the tip:
  // it is erased and redrawn at every movement, so the line is always under the
  // tip. Being small, it costs almost no memory (Safari on the iPad has a limit
  // for all the canvases of a page together).
  startLive(g) {
    const v = this.els.get(g.page.id);
    if (!v?.rendered || !v.region) return;
    const dpr = window.devicePixelRatio || 1;
    if (!v.tail) {
      v.tail = document.createElement('canvas');
      v.tail.className = 'live tail';
      // A normal canvas, not a "low latency" one (desynchronized): Chrome and the
      // browsers based on it can show that on a separate plane of the graphics
      // card, which ignores the opacity and may keep showing an old drawing.
      v.tailCtx = v.tail.getContext('2d');
      v.el.append(v.tail);
    }
    v.tail.width = v.tail.height = Math.round(TAIL_BOX * dpr);
    Object.assign(v.tail.style, { width: TAIL_BOX + 'px', height: TAIL_BOX + 'px' });
    const highlighter = g.stroke.tool === 'highlighter';
    // The strokes canvas shows an image from the worker: copied onto a normal canvas,
    // so the stroke can be drawn on it (copying is quick, drawing all the strokes is not).
    if (v.inkBitmap) this.inkCanvas(v, true);
    // The pen draws straight on the strokes canvas, the highlighter on a canvas of its own.
    g.onLive = highlighter;
    if (g.onLive) {
      if (!v.live) {
        v.live = document.createElement('canvas');
        v.live.className = 'live';
        v.liveCtx = v.live.getContext('2d');
        v.ink.after(v.live);
      }
      this.placeCanvas(v.live, v.region);
      v.live.style.opacity = highlighter ? String(HIGHLIGHT_ALPHA) : '';   // highlighter: drawn opaque, made transparent here
      this.liveStyle(v.liveCtx, v, g.stroke);
    }
    v.tail.style.opacity = highlighter ? String(HIGHLIGHT_ALPHA) : '';
    g.curveCtx = g.onLive ? v.liveCtx : this.inkContext(v);
    g.region = v.region;               // finishLive checks that the canvas did not move meanwhile
    if (!g.onLive) this.liveStyle(g.curveCtx, v, g.stroke);
    g.drawn = 1;          // points of the curve already drawn
  }

  liveStyle(ctx, v, stroke) {
    const { x, y, r } = v.region;
    const k = this.scale * r;
    ctx.setTransform(k, 0, 0, k, -x * r, -y * r);
    this.strokeStyle(ctx, stroke);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  drawLive(g) {
    const v = this.els.get(g.page.id);
    if (!v?.tail || !v.region || !g.curveCtx) return;
    const s = g.stroke, pts = s.points, n = pts.length;
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const ctx = g.curveCtx;
    if (s.shape) {
      // Turned into a geometric shape: drawn whole, once, without the tail.
      if (g.drawn !== Infinity) {
        if (g.onLive) {
          ctx.clearRect(0, 0, g.page.w, g.page.h);
          this.drawStroke(ctx, s);
          this.liveStyle(ctx, v, s);
        } else {
          this.drawInk(g.page);     // the freehand version disappears, the shape is drawn
        }
        v.tail.style.visibility = 'hidden';
        g.drawn = Infinity;
      }
      return;
    }
    // New pieces of the curve: the same quadratic curves as the final drawing
    // (drawStroke); point j completes the curve through point j-1. The style is
    // set every time: a redraw of the page in the meantime may have changed it.
    this.liveStyle(ctx, v, s);
    for (let j = Math.max(2, g.drawn); j < n; j++) {
      const start = j === 2 ? pts[0] : mid(pts[j - 2], pts[j - 1]);
      const end = mid(pts[j - 1], pts[j]);
      ctx.beginPath();
      ctx.moveTo(start[0], start[1]);
      ctx.quadraticCurveTo(pts[j - 1][0], pts[j - 1][1], end[0], end[1]);
      ctx.stroke();
    }
    g.drawn = Math.max(g.drawn, n);
    // Tail, on the small canvas centred on the last point.
    const last = pts[n - 1];
    const tip = g.tip || last;
    const from = n >= 2 ? (n === 2 ? pts[0] : mid(pts[n - 2], last)) : last;
    const dpr = window.devicePixelRatio || 1;
    const left = Math.round(last[0] * this.scale - TAIL_BOX / 2), top = Math.round(last[1] * this.scale - TAIL_BOX / 2);
    v.tail.style.transform = `translate(${left}px, ${top}px)`;
    v.tail.style.visibility = 'visible';
    const t = v.tailCtx;
    t.setTransform(1, 0, 0, 1, 0, 0);
    t.clearRect(0, 0, v.tail.width, v.tail.height);
    const k = this.scale * dpr;
    t.setTransform(k, 0, 0, k, -left * dpr, -top * dpr);
    this.strokeStyle(t, s);
    t.globalAlpha = 1;
    t.globalCompositeOperation = 'source-over';
    t.beginPath();
    t.moveTo(from[0], from[1]);
    t.quadraticCurveTo(last[0], last[1], (last[0] + tip[0]) / 2 + 0.005, (last[1] + tip[1]) / 2 + 0.005);
    t.lineTo(tip[0] + 0.01, tip[1] + 0.01);
    t.stroke();
  }

  // Pen lifted: the stroke is completed where it is, without drawing the page again
  // (with strong zoom and many strokes that took the browser long enough to hold the
  // sheet still right after writing). The last piece, from the end of the curve to
  // the last point, is the one drawStroke ends with; the highlighter, drawn on its
  // own canvas until now, goes onto the strokes canvas as one stroke. Anything out of
  // the ordinary (a shape, the page drawn again meanwhile) draws the page again.
  finishLive(g) {
    const v = this.els.get(g.page.id);
    const s = g.stroke, pts = s.points, n = pts.length;
    if (!v?.rendered || !v.region || v.inkBitmap || s.shape || !g.curveCtx || g.region !== v.region) {
      this.drawInk(g.page);
      return;
    }
    v.inkVersion = (v.inkVersion || 0) + 1;     // an image of the strokes on its way is now out of date
    const ctx = this.inkContext(v);
    if (g.onLive) {
      this.drawStroke(ctx, s);                // the highlighter, transparent and multiplied as on the page
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      return;
    }
    this.liveStyle(ctx, v, s);
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    for (let j = Math.max(2, g.drawn); j < n; j++) {      // pieces not drawn yet (same as drawLive)
      const start = j === 2 ? pts[0] : mid(pts[j - 2], pts[j - 1]);
      const end = mid(pts[j - 1], pts[j]);
      ctx.beginPath();
      ctx.moveTo(start[0], start[1]);
      ctx.quadraticCurveTo(pts[j - 1][0], pts[j - 1][1], end[0], end[1]);
      ctx.stroke();
    }
    const from = n === 1 ? pts[0] : n === 2 ? pts[0] : mid(pts[n - 2], pts[n - 1]);
    const to = n === 1 ? [pts[0][0] + 0.01, pts[0][1] + 0.01] : pts[n - 1];
    ctx.beginPath();
    ctx.moveTo(from[0], from[1]);
    ctx.lineTo(to[0], to[1]);
    ctx.stroke();
  }

  endLive(page) {
    const v = this.els.get(page.id);
    if (v?.live) v.live.width = v.live.height = 0;       // frees its memory right away
    if (v?.tail) v.tail.style.visibility = 'hidden';
  }

  // Frees a canvas's memory right away (Safari on the iPad would keep it until it
  // cleans up, and the limit for all the canvases of a page is low).
  freeCanvas(c) {
    // A canvas holding a worker image releases it too: a new size replaces its bitmap.
    if (c) c.width = c.height = 0;
  }
}
