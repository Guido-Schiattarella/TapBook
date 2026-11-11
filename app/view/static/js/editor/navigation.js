// VIEW — editor, moving around the document: going to a page, the page chooser
// (thumbnails), the reading position remembered by the computer, zoom by tapping.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { apiPost } from '../api.js';
import { POSITION_DELAY_MS, THUMB_WIDTH, TAP_ZOOM } from './shared.js';

export class NavigationMethods {
  // Top of a page (offset: how far down it, as a fraction of its height).
  goToPage(index, { offset = 0, smooth = false } = {}) {
    const page = this.pages[Math.max(0, Math.min(index, this.pages.length - 1))];
    const v = page && this.els.get(page.id);
    if (!v) return;
    const r = v.el.getBoundingClientRect();
    const top = this.pagesEl.scrollTop + r.top - this.viewTop() - 12 + offset * page.h * this.scale;
    if (smooth) this.pagesEl.scrollTo({ top, behavior: 'smooth' });
    else this.pagesEl.scrollTop = top;
    this.showNav();
  }

  nextPage(step = 1) {
    const index = this.currentPageIndex() + step;
    if (index < 0 || index >= this.pages.length) return;
    this.goToPage(index, { smooth: true });
  }

  // Page under the point (cx, cy) on screen, or null (the gap between pages).
  pageAt(cx, cy) {
    for (const page of this.pages) {
      const r = this.els.get(page.id)?.el.getBoundingClientRect();
      if (r && cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) return page;
    }
    return null;
  }

  // Two taps with one finger: zoom in on that point, or back to the page width.
  toggleZoomAt(cx, cy) {
    if (this.zoom > 1.01) this.setZoom(1, this.anchorAt(cx, cy), cx, cy);
    else this.setZoom(TAP_ZOOM, this.anchorAt(cx, cy), cx, cy);
  }

  // --- reading position -------------------------------------------------------------------
  // Where the reader is (first page in view and how far down it): sent to the
  // computer a moment after the scrolling stops, and when leaving.
  currentPosition() {
    const anchor = this.ready && this.pages.length ? this.topAnchor() : null;
    if (!anchor) return null;
    const page = this.pages[anchor.index];
    const offset = Math.max(0, Math.min(1, anchor.offset / page.h));
    return { page: anchor.index, offset: Math.round(offset * 1000) / 1000 };
  }

  schedulePosition() {
    if (!this.session || !this.ready) return;
    clearTimeout(this.positionTimer);
    this.positionTimer = setTimeout(() => { this.positionTimer = null; this.flushPosition(); }, POSITION_DELAY_MS);
  }

  // Sent only if it changed since the last time. When leaving, the position travels
  // with the closing request instead (editor_view.js), so it can never arrive late.
  flushPosition() {
    clearTimeout(this.positionTimer);
    this.positionTimer = null;
    // Not while the fingers move the sheet: sent once they stop (nothing to wait for).
    if (this.gesturing()) { this.schedulePosition(); return; }
    if (!this.session || !this.ready) return;
    const pos = this.currentPosition();
    if (!pos || (this.position && this.position.page === pos.page && Math.abs(this.position.offset - pos.offset) < 0.02)) return;
    this.position = pos;
    apiPost('/api/edit/position', { session: this.session, ...pos }).catch(() => {});   // not worth retrying or reporting
  }

  // --- page chooser -----------------------------------------------------------------------
  // Thumbnails of all the pages (drawn as they come into view), the current one
  // highlighted; tapping one goes there. Also a field to type the page number.
  openPageChooser() {
    if (!this.pages.length) return;
    const grid = document.getElementById('page-grid');
    const current = this.currentPageIndex();
    this.thumbObserver?.disconnect();
    this.thumbObserver = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        this.thumbObserver.unobserve(e.target);
        const page = this.page(e.target.dataset.id);
        if (page) this.drawThumbnail(page, e.target.querySelector('canvas'));
      }
    }, { root: grid, rootMargin: '300px 0px' });
    grid.replaceChildren(...this.pages.map((page, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'page-thumb' + (i === current ? ' current' : '');
      b.dataset.id = page.id;
      const c = document.createElement('canvas');
      const h = Math.round(THUMB_WIDTH * page.h / page.w);
      Object.assign(c.style, { width: THUMB_WIDTH + 'px', height: h + 'px' });
      const n = document.createElement('span');
      n.textContent = String(i + 1);
      b.append(c, n);
      b.addEventListener('click', () => { this.pageDialog.close(); this.goToPage(i); });
      this.thumbObserver.observe(b);
      return b;
    }));
    const input = document.getElementById('page-number');
    input.max = String(this.pages.length);
    input.value = String(current + 1);
    document.getElementById('page-count').textContent = `di ${this.pages.length}`;
    this.pageDialog.showModal();
    grid.querySelector('.current')?.scrollIntoView({ block: 'center' });
  }

  bindPageChooser() {
    const form = document.getElementById('page-form');
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const n = Number(document.getElementById('page-number').value);
      this.pageDialog.close();
      if (Number.isInteger(n) && n >= 1 && n <= this.pages.length) this.goToPage(n - 1);
    });
    document.getElementById('page-cancel').addEventListener('click', () => this.pageDialog.close());
    this.pageDialog.addEventListener('close', () => {
      this.thumbObserver?.disconnect();
      this.thumbObserver = null;
      document.getElementById('page-grid').querySelectorAll('canvas').forEach((c) => { c.width = c.height = 0; });
    });
  }

  // Small picture of a page: background (from the PDF already on this device, or
  // the layout) and the strokes; text boxes as light grey blocks.
  async drawThumbnail(page, canvas) {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const k = THUMB_WIDTH / page.w;
    canvas.width = Math.round(THUMB_WIDTH * dpr);
    canvas.height = Math.round(THUMB_WIDTH * page.h / page.w * dpr);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    try {
      const source = await this.backgroundSource(page);
      if (!canvas.isConnected || !canvas.width) return;        // the chooser was closed meanwhile
      if (source) {
        const image = await this.painter.render(source.key, source.index,
          { scale: k, x: 0, y: 0, w: THUMB_WIDTH, h: THUMB_WIDTH * page.h / page.w, r: dpr }).promise;
        if (!canvas.isConnected || !canvas.width) { image.close?.(); return; }
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(image, 0, 0);
        image.close?.();
      }
    } catch (e) {
      if (!e?.cancelled) console.error(e);
    }
    if (!canvas.isConnected || !canvas.width) return;
    ctx.setTransform(k * dpr, 0, 0, k * dpr, 0, 0);
    ctx.fillStyle = 'rgba(120, 140, 180, .18)';
    for (const t of page.texts) ctx.fillRect(t.x, t.y, t.w, t.h);
    for (const s of page.strokes) this.drawStroke(ctx, { ...s, width: Math.max(s.width, 1.5 / k) });
  }
}
