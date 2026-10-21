// VIEW — editor, drawing: PDF background in regions (strong zoom too), saved strokes and stroke preview.
// EditorView methods (see editor_view.js): here `this` is the editor.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { HIGHLIGHT_ALPHA, MAX_CANVAS_PIXELS, REGION_MARGINS } from './shared.js';

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
    v.base.replaceWith(next);
    v.base = next;
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
    v.base.width = v.base.height = v.ink.width = v.ink.height = 0;
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

  // Redraws the page's strokes: confirmed + pending + the one in progress.
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
    if (g?.type === 'draw' && g.page.id === page.id) this.drawStroke(ctx, g.stroke);
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

  // Preview of the stroke while the pen moves (immediately, without waiting for the computer).
  drawLive(page, stroke, from) {
    const v = this.els.get(page.id);
    if (!v?.rendered || !v.region) return;
    if (stroke.tool === 'highlighter') { this.drawInk(page); return; }  // semi-transparent: redraw everything
    const ctx = this.inkContext(v);
    if (from === 0) { this.drawStroke(ctx, { ...stroke, points: [stroke.points[0]] }); from = 1; }
    this.strokeStyle(ctx, stroke);
    const pts = stroke.points;
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    // Same curve as the final drawing, one piece at a time: point j arriving
    // completes the curve through point j-1 (the last half segment is drawn
    // when the pen is lifted).
    for (let j = Math.max(2, from); j < pts.length; j++) {
      const start = j === 2 ? pts[0] : mid(pts[j - 2], pts[j - 1]);
      const end = mid(pts[j - 1], pts[j]);
      ctx.beginPath();
      ctx.moveTo(start[0], start[1]);
      ctx.quadraticCurveTo(pts[j - 1][0], pts[j - 1][1], end[0], end[1]);
      ctx.stroke();
    }
  }
}
