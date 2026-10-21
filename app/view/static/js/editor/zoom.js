// VIEW — editor, zoom: pinch, buttons, fixed point under the fingers, page/zoom indicator.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { ZOOM_MIN, ZOOM_MAX, touches } from './shared.js';

export class ZoomMethods {
  // =====================================================================
  // Pinch zoom (two fingers)
  // =====================================================================
  startPinch(e) {
    this.abortFingerGesture();
    this.hideEraserCursor();
    const [a, b] = e.touches;
    const mid = { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
    const inner = this.innerEl.getBoundingClientRect();
    this.pinch = {
      dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1,
      mid,
      origin: { x: mid.x - inner.left, y: mid.y - inner.top },
      anchor: this.anchorAt(mid.x, mid.y),   // point of the document under the fingers
      factor: 1,
      now: mid,
    };
    this.innerEl.style.transformOrigin = `${this.pinch.origin.x}px ${this.pinch.origin.y}px`;
  }

  movePinch(e) {
    if (e.touches.length < 2) return;
    const [a, b] = e.touches;
    const p = this.pinch;
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
    p.factor = Math.min(ZOOM_MAX / this.zoom, Math.max(ZOOM_MIN / this.zoom, dist / p.dist));
    p.now = { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
    // During the gesture the image already drawn is scaled (fast); at the end the
    // pages are redrawn at the new resolution.
    this.innerEl.style.transform =
      `translate(${p.now.x - p.mid.x}px, ${p.now.y - p.mid.y}px) scale(${p.factor})`;
    this.showNav(this.zoom * p.factor);
  }

  endPinch() {
    const p = this.pinch;
    this.pinch = null;
    this.innerEl.style.transform = '';
    if (Math.abs(p.factor - 1) < 0.02) {          // two-finger panning only
      this.pagesEl.scrollLeft -= p.now.x - p.mid.x;
      this.pagesEl.scrollTop -= p.now.y - p.mid.y;
      return;
    }
    // The document point that was under the fingers at the start ends up under the fingers now.
    this.setZoom(this.zoom * p.factor, p.anchor, p.now.x, p.now.y);
  }

  // Zoom from the buttons: the centre of the screen stays put.
  zoomBy(factor) {
    const r = this.pagesEl.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = (this.viewTop() + r.bottom) / 2;
    this.setZoom(this.zoom * factor, this.anchorAt(cx, cy), cx, cy);
  }

  // Document point (page and PDF coordinates) found at (cx, cy) on the screen.
  anchorAt(cx, cy) {
    let best = null, bestDist = Infinity;
    for (const page of this.pages) {
      const r = this.els.get(page.id)?.el.getBoundingClientRect();
      if (!r) continue;
      const d = cy < r.top ? r.top - cy : cy > r.bottom ? cy - r.bottom : 0;
      if (d < bestDist) { bestDist = d; best = { id: page.id, x: (cx - r.left) / this.scale, y: (cy - r.top) / this.scale }; }
    }
    return best;
  }

  // New zoom without rebuilding the pages: they are resized (the current drawing stays
  // visible, enlarged, until the sharp one is ready) and scrolled so that the
  // document point `anchor` is at (cx, cy).
  setZoom(zoom, anchor, cx, cy) {
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom));
    if (Math.abs(zoom - this.zoom) < 1e-3) return;
    const old = this.scale;
    this.zoom = zoom;
    this.computeScale();
    const k = this.scale / old;
    this.hideEraserCursor();
    for (const page of this.pages) {
      const v = this.els.get(page.id);
      v.el.style.width = page.w * this.scale + 'px';
      v.el.style.height = page.h * this.scale + 'px';
      for (const c of [v.base, v.ink]) {
        if (!c.style.width) continue;
        for (const prop of ['left', 'top', 'width', 'height']) c.style[prop] = parseFloat(c.style[prop]) * k + 'px';
      }
      v.texts.querySelectorAll('.textbox').forEach((el) => {
        const t = page.texts.find((x) => x.id === el.dataset.id);
        if (t) this.placeTextbox(el, t);
      });
      v.images.querySelectorAll('.imagebox').forEach((el) => {
        const img = page.images.find((x) => x.id === el.dataset.id);
        if (img) this.placeImage(el, img);
      });
    }
    if (anchor && this.els.has(anchor.id)) {
      const r = this.els.get(anchor.id).el.getBoundingClientRect();
      this.pagesEl.scrollLeft += r.left + anchor.x * this.scale - cx;
      this.pagesEl.scrollTop += r.top + anchor.y * this.scale - cy;
    }
    // Sharp redraw of the pages already drawn (the others when they come near).
    for (const page of this.pages) {
      const v = this.els.get(page.id);
      if (v.rendered) this.renderPage(page, v);
    }
    if (this.selection) this.showSelection();
    this.showNav();
  }

  // "Pagina 3 di 8 · 150%" indicator: shown while scrolling or zooming.
  showNav(zoom = this.zoom) {
    if (!this.pages.length || !this.els.size) return;
    this.navEl.textContent = `Pagina ${this.currentPageIndex() + 1} di ${this.pages.length} · ${Math.round(zoom * 100)}%`;
    this.navEl.classList.add('visible');
    clearTimeout(this.navTimer);
    this.navTimer = setTimeout(() => this.navEl.classList.remove('visible'), 1200);
  }
}
