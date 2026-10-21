// VIEW — editor, pages: adding, deleting, layout, page elements, position in the list.
// EditorView methods (see editor_view.js): here `this` is the editor.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { renderLayoutOptions } from '../layout_picker.js';
import { PDF_OPTIONS } from './shared.js';

export class PagesMethods {
  currentPageIndex() {
    const mid = this.pagesEl.getBoundingClientRect().top + this.pagesEl.clientHeight / 2;
    let best = 0, bestDist = Infinity;
    this.pages.forEach((p, i) => {
      const r = this.els.get(p.id).el.getBoundingClientRect();
      const d = Math.abs((r.top + r.bottom) / 2 - mid);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    return best;
  }

  addPage() {
    const index = this.currentPageIndex();
    this.navFocus = { type: 'added' };     // when the new page arrives, go to its top left
    this.send({ type: 'addPage', after: this.pages[index].id });
  }

  deletePage() {
    if (this.pages.length <= 1) return;
    const index = this.currentPageIndex();
    if (window.confirm(`Eliminare la pagina ${index + 1}? (si può annullare)`)) {
      this.navFocus = { type: 'removed', index };   // go to the page that takes its place
      this.send({ type: 'removePage', page: this.pages[index].id });
    }
  }

  // =====================================================================
  // Layout of the new pages
  // =====================================================================
  showLayout() {
    const current = this.layouts.find((l) => l.id === this.layout);
    document.getElementById('layout-label').textContent = current ? current.label : '—';
  }

  // The button shows the current layout; tapping it chooses the layout of the
  // pages that will be added. The choice goes to the controller (it applies to every device).
  chooseLayout() {
    renderLayoutOptions(document.getElementById('editor-layouts'), this.layouts, this.layout, 'editor-layout',
      (id) => {
        this.layoutDialog.close();
        if (id !== this.layout) this.send({ type: 'setLayout', layout: id });
      });
    this.layoutDialog.showModal();
    // Focus goes to the option already chosen (not to the first one, as the browser would do).
    this.layoutDialog.querySelector('#editor-layouts input:checked')?.focus({ preventScroll: true });
  }

  // Background of a page added in this session: the empty page with its layout,
  // drawn by the computer (one copy per layout and size).
  layoutPdf(page) {
    const key = `${page.layout}|${page.w}|${page.h}`;
    if (!this.layoutDocs.has(key)) {
      const session = this.session;
      this.layoutDocs.set(key, (async () => {
        const url = `/api/edit/layout?session=${encodeURIComponent(session)}&page=${encodeURIComponent(page.id)}`;
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) { this.layoutDocs.delete(key); return null; }
        return pdfjsLib.getDocument({ data: new Uint8Array(await resp.arrayBuffer()), ...PDF_OPTIONS }).promise;
      })());
    }
    return this.layoutDocs.get(key);
  }

  computeScale() {
    const maxW = Math.max(...this.pages.map((p) => p.w));
    const avail = Math.min(this.pagesEl.clientWidth - 32, 1400);
    this.scale = (avail / maxW) * this.zoom;
  }

  // Elements of a page: background (PDF), images, strokes, text boxes, number.
  createPageEl(page) {
    page.images = page.images || [];
    const el = document.createElement('div');
    el.className = 'page';
    el.style.width = page.w * this.scale + 'px';
    el.style.height = page.h * this.scale + 'px';
    el.dataset.id = page.id;
    const base = document.createElement('canvas');
    const images = document.createElement('div');   // below the strokes: you can write on photos
    images.className = 'images';
    const ink = document.createElement('canvas');
    ink.className = 'ink';
    const texts = document.createElement('div');
    texts.className = 'texts';
    const label = document.createElement('span');
    label.className = 'label';
    el.append(base, images, ink, texts, label);
    const v = { el, base, images, ink, texts, label, w: page.w, h: page.h, rendered: false, task: null };
    this.els.set(page.id, v);
    this.renderImages(page);
    this.renderTexts(page);
    this.observer.observe(el);
    return v;
  }

  updateLabels() {
    this.pages.forEach((page, index) => { this.els.get(page.id).label.textContent = `${index + 1} / ${this.pages.length}`; });
    document.getElementById('btn-del-page').disabled = this.pages.length <= 1;
  }

  // Full rebuild (opening, background changed on the computer, window resized).
  // Keeps the point of the document that was being looked at.
  buildPages() {
    const anchor = this.els.size ? this.topAnchor() : null;
    this.observer?.disconnect();
    this.observer = new IntersectionObserver((entries) => this.onVisibility(entries),
      { root: this.pagesEl, rootMargin: '1200px 0px' });
    this.els.forEach((v) => v.task?.cancel());
    this.els.clear();
    this.innerEl.replaceChildren();
    for (const page of this.pages) this.innerEl.append(this.createPageEl(page).el);
    this.updateLabels();
    if (anchor) this.restoreTopAnchor(anchor);
    if (this.selection) this.showSelection();
  }

  // Pages added, removed or moved: only the changed ones are updated (the others
  // stay drawn, no flashes). focus: "added" (page added from here: go to the top
  // left of the new page), "removed" (go to the page that takes its place);
  // otherwise (other devices, undo) stay where you were.
  syncPages(pages, focus) {
    const anchor = this.topAnchor();
    const oldIds = new Set(this.pages.map((p) => p.id));
    this.pages = pages;
    const keep = new Set(pages.map((p) => p.id));
    for (const [id, v] of this.els) {
      if (!keep.has(id)) { v.task?.cancel(); this.observer.unobserve(v.el); v.el.remove(); this.els.delete(id); }
    }
    for (const page of pages) {
      let v = this.els.get(page.id);
      if (v && (v.w !== page.w || v.h !== page.h)) {   // size changed: rebuild it
        this.observer.unobserve(v.el); v.el.remove(); this.els.delete(page.id); v = null;
      }
      if (!v) v = this.createPageEl(page);
      else { this.renderTexts(page); this.renderImages(page); if (v.rendered) this.drawInk(page); }
      this.innerEl.append(v.el);   // moving an element does not wipe its drawing
    }
    this.updateLabels();
    const added = pages.find((p) => !oldIds.has(p.id));
    if (focus?.type === 'added' && added) this.scrollToPageStart(added.id);
    else if (focus?.type === 'removed') this.scrollToPageStart(pages[Math.min(focus.index, pages.length - 1)].id);
    else this.restoreTopAnchor(anchor);
    if (this.selection) this.showSelection();
    this.showNav();
  }

  // Top edge of the visible area (below the toolbar).
  viewTop() {
    return this.pagesEl.getBoundingClientRect().top + this.toolbarEl.offsetHeight;
  }

  // First visible page and how far it has been scrolled.
  topAnchor() {
    const top = this.viewTop();
    for (let i = 0; i < this.pages.length; i++) {
      const v = this.els.get(this.pages[i].id);
      const r = v?.el.getBoundingClientRect();
      if (r && r.bottom > top) return { id: this.pages[i].id, index: i, offset: (top - r.top) / this.scale };
    }
    return null;
  }

  restoreTopAnchor(anchor) {
    if (!anchor) return;
    const page = this.els.has(anchor.id) ? anchor.id : this.pages[Math.min(anchor.index, this.pages.length - 1)]?.id;
    const v = page && this.els.get(page);
    if (!v) return;
    const offset = page === anchor.id ? anchor.offset * this.scale : 0;
    this.pagesEl.scrollTop += v.el.getBoundingClientRect().top + offset - this.viewTop();
  }

  // Top left of a page (immediately, without animation).
  scrollToPageStart(id) {
    const v = this.els.get(id);
    if (!v) return;
    const r = v.el.getBoundingClientRect(), view = this.pagesEl.getBoundingClientRect();
    this.pagesEl.scrollTop += r.top - this.viewTop() - 12;
    this.pagesEl.scrollLeft += r.left - view.left - 12;
  }


  // Pages are drawn when they come near the screen and released when they move
  // away (Safari's memory on the iPad is limited).
  onVisibility(entries) {
    for (const entry of entries) {
      const page = this.page(entry.target.dataset.id);
      const v = page && this.els.get(page.id);
      if (!v) continue;
      if (entry.isIntersecting && !v.rendered) this.renderPage(page, v);
      else if (!entry.isIntersecting && v.rendered) this.releasePage(v);
    }
  }
}
