// VIEW — editor, drawing: PDF background in regions (strong zoom too), saved strokes and stroke preview.
// EditorView methods (see editor_view.js): here `this` is the editor.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { HIGHLIGHT_ALPHA, MAX_CANVAS_PIXELS, REGION_MARGINS, TAIL_BOX, CANVAS_BUDGET } from './shared.js';

export class RenderMethods {
  // Part of the page to draw, in CSS pixels relative to the page, and resolution
  // r (canvas pixels per CSS pixel). null = nothing to draw now.
  renderRegion(page, v) {
    const dpr = window.devicePixelRatio || 1;
    const W = page.w * this.scale, H = page.h * this.scale;
    if (W * H * dpr * dpr <= MAX_CANVAS_PIXELS) return { x: 0, y: 0, w: W, h: H, r: dpr, full: true };
    let region = null;
    for (const m of REGION_MARGINS) {
      region = this.visiblePart(page, v, m);
      if (!region) return null;
      if (region.w * region.h * dpr * dpr <= MAX_CANVAS_PIXELS) return { ...region, r: dpr, full: false };
    }
    // Even the visible part alone is too large: lower the resolution a little.
    return { ...region, r: Math.sqrt(MAX_CANVAS_PIXELS / (region.w * region.h)), full: false };
  }

  // Part of the page that is on screen, widened by the margin m.
  visiblePart(page, v, m = 0) {
    const pr = v.el.getBoundingClientRect(), vr = this.pagesEl.getBoundingClientRect();
    const W = page.w * this.scale, H = page.h * this.scale;
    const mx = vr.width * m, my = vr.height * m;
    const x0 = Math.max(0, Math.floor(vr.left - mx - pr.left)), y0 = Math.max(0, Math.floor(vr.top - my - pr.top));
    const x1 = Math.min(W, Math.ceil(vr.right + mx - pr.left)), y1 = Math.min(H, Math.ceil(vr.bottom + my - pr.top));
    return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
  }

  // Sizes a canvas to the region and positions it over that part of the page.
  placeCanvas(canvas, region) {
    if (!region) { canvas.width = canvas.height = 0; return; }
    canvas.width = Math.round(region.w * region.r);
    canvas.height = Math.round(region.h * region.r);
    Object.assign(canvas.style, { left: region.x + 'px', top: region.y + 'px', width: region.w + 'px', height: region.h + 'px' });
  }

  async renderPage(page, v) {
    v.rendered = true;
    const region = this.renderRegion(page, v);
    const id = (v.renderId = (v.renderId || 0) + 1);
    v.region = region;
    v.task?.cancel();
    this.placeCanvas(v.ink, region);
    this.drawInk(page);
    if (!region) { this.placeCanvas(v.base, null); return; }
    let pdfPage = null;
    if (page.render == null) {
      // Page added in this session: background with its layout (unless it is blank).
      if (page.layout && page.layout !== 'blank') {
        const doc = await this.layoutPdf(page);
        if (doc) pdfPage = await doc.getPage(1);
      }
    } else {
      pdfPage = await this.pdf.getPage(page.render + 1);
    }
    if (v.renderId !== id || !v.rendered || this.els.get(page.id) !== v) return;  // superseded by a newer drawing
    // The background is drawn on a new canvas and replaces the old one only when
    // finished: scrolling with strong zoom never shows an empty page.
    const next = document.createElement('canvas');
    this.placeCanvas(next, region);
    const ctx = next.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, next.width, next.height);
    if (pdfPage) {
      const viewport = pdfPage.getViewport({ scale: this.scale * region.r });
      try {
        v.task = pdfPage.render({ canvasContext: ctx, viewport, annotationMode: pdfjsLib.AnnotationMode.ENABLE,
          transform: [1, 0, 0, 1, -region.x * region.r, -region.y * region.r] });
        await v.task.promise;
      } catch (err) {
        if (err?.name !== 'RenderingCancelledException') console.error(err);
        return;
      }
    }
    if (v.renderId !== id || !v.rendered) return;
    this.freeCanvas(v.base);
    v.base.replaceWith(next);
    v.base = next;
    this.enforceCanvasBudget(v);
    this.firstDrawn?.();          // the first page is visible: the opening progress bar finishes
    this.firstDrawn = null;
  }

  // Scrolling with strong zoom: if the visible part leaves the drawn one, redraw it.
  checkRegions() {
    for (const page of this.pages) {
      const v = this.els.get(page.id);
      if (!v?.rendered || v.region?.full) continue;
      const want = this.visiblePart(page, v);
      const r = v.region;
      if (want && (!r || want.x < r.x || want.y < r.y || want.x + want.w > r.x + r.w || want.y + want.h > r.y + r.h)) {
        this.renderPage(page, v);
      }
    }
  }

  releasePage(v) {
    v.rendered = false;
    v.region = null;
    v.renderId = (v.renderId || 0) + 1;
    v.task?.cancel();
    for (const c of [v.base, v.ink, v.live]) this.freeCanvas(c);
  }

  // Page taken off the screen for good (removed, or pages rebuilt): its canvases
  // are freed at once.
  discardPage(v) {
    v.task?.cancel();
    v.renderId = (v.renderId || 0) + 1;
    for (const c of [v.base, v.ink, v.live, v.tail]) this.freeCanvas(c);
  }

  // Memory limit for the pages' canvases: Safari on the iPad reloads (or blanks)
  // a page whose canvases together use too much memory. When the drawn pages
  // exceed CANVAS_BUDGET pixels, those off the screen are released, the
  // farthest first (they are drawn again when they come back near).
  enforceCanvasBudget(keep) {
    const drawn = [...this.els.values()].filter((v) => v.rendered);
    const pixels = (v) => v.base.width * v.base.height + v.ink.width * v.ink.height;
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

  pendingOn(page) {
    return [...this.pendingStrokes.values()].filter((p) => p.page === page.id).map((p) => p.stroke);
  }

  // Redraws the page's strokes: confirmed + pending (the one in progress is on
  // its own layer, see drawLive).
  drawInk(page) {
    const v = this.els.get(page.id);
    if (!v?.rendered || !v.region) return;
    const ctx = this.inkContext(v);
    ctx.clearRect(0, 0, page.w, page.h);
    const sel = this.selection?.page === page.id ? this.selection : null;
    for (const s of [...page.strokes, ...this.pendingOn(page)]) {
      if (this.hiddenStrokes.has(s.id)) continue;
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
    if (g?.type === 'draw' && g.page.id === page.id && g.stroke.tool !== 'highlighter') this.drawStroke(ctx, g.stroke);
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    if (g?.type === 'lasso' && g.page.id === page.id) {
      // Lasso outline while it is being drawn.
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = '#1e5bd8';
      ctx.beginPath();
      g.points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
      ctx.restore();
    }
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
      v.tailCtx = v.tail.getContext('2d', { desynchronized: true });   // lower latency where supported
      v.el.append(v.tail);
    }
    v.tail.width = v.tail.height = Math.round(TAIL_BOX * dpr);
    Object.assign(v.tail.style, { width: TAIL_BOX + 'px', height: TAIL_BOX + 'px' });
    const highlighter = g.stroke.tool === 'highlighter';
    if (highlighter) {
      if (!v.live) {
        v.live = document.createElement('canvas');
        v.live.className = 'live';
        v.liveCtx = v.live.getContext('2d', { desynchronized: true });
        v.ink.after(v.live);
      }
      this.placeCanvas(v.live, v.region);
      this.liveStyle(v.liveCtx, v, g.stroke);
    }
    v.tail.style.opacity = highlighter ? String(HIGHLIGHT_ALPHA) : '';
    g.curveCtx = highlighter ? v.liveCtx : this.inkContext(v);
    if (!highlighter) this.liveStyle(g.curveCtx, v, g.stroke);
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
        if (s.tool === 'highlighter') {
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

  endLive(page) {
    const v = this.els.get(page.id);
    if (v?.live) v.live.width = v.live.height = 0;       // frees its memory right away
    if (v?.tail) v.tail.style.visibility = 'hidden';
  }

  // Frees a canvas's memory right away (Safari on the iPad would keep it until it
  // cleans up, and the limit for all the canvases of a page is low).
  freeCanvas(c) {
    if (c) c.width = c.height = 0;
  }
}
