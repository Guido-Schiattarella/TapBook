// VIEW — editor, copy and paste: the lasso selection (or the active text box) is
// copied onto this device and pasted on the page in view, also in another document.
// EditorView methods (see editor_view.js): here `this` is the editor.
//
// Inside a text box the keyboard shortcuts keep their usual meaning (copying
// the words); outside, Ctrl+C / Ctrl+X / Ctrl+V (Cmd on the iPad keyboard) work
// on the items. On the iPad without a keyboard: "Copia" and "Taglia" in the lasso
// menu, "Incolla" in the toolbar.
import { CLIPBOARD_PREF, CLIPBOARD_MAX_BYTES, PASTE_OFFSET, CLIP_MARK, uid } from './shared.js';

export class ClipboardMethods {
  loadClipboard() {
    this.clipboard = null;
    try {
      const c = JSON.parse(localStorage.getItem(CLIPBOARD_PREF) || 'null');
      if (c && Array.isArray(c.strokes) && Array.isArray(c.texts) && Array.isArray(c.images) && c.bounds) this.clipboard = c;
    } catch { /* no storage available, or not readable */ }
  }

  // What to copy: the lasso selection, or the text box being edited.
  copyable() {
    if (this.hasSelection()) {
      const s = this.selection, page = this.page(s.page);
      if (!page) return null;
      return { page, strokes: page.strokes.filter((x) => s.strokes.has(x.id)),
        texts: page.texts.filter((x) => s.texts.has(x.id)), images: page.images.filter((x) => s.images.has(x.id)) };
    }
    const data = this.activeTextData();
    if (data) {
      const ta = data.el?.querySelector('textarea');
      return { page: data.page, strokes: [], texts: [{ ...data.t, text: ta ? ta.value : data.t.text }], images: [] };
    }
    return null;
  }

  copy() {
    const items = this.copyable();
    if (!items) return false;
    const { page, strokes, texts, images } = items;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (ax, ay, bx, by) => { x0 = Math.min(x0, ax); y0 = Math.min(y0, ay); x1 = Math.max(x1, bx); y1 = Math.max(y1, by); };
    for (const st of strokes) for (const [x, y] of st.points) add(x - st.width / 2, y - st.width / 2, x + st.width / 2, y + st.width / 2);
    for (const t of texts) add(t.x, t.y, t.x + t.w, t.y + t.h);
    for (const i of images) add(i.x, i.y, i.x + i.w, i.y + i.h);
    if (x0 === Infinity) return false;
    this.clipboard = {
      doc: this.path, page: page.id,
      strokes: strokes.map((s) => ({ tool: s.tool, color: s.color, width: s.width, points: s.points, shape: s.shape })),
      texts: texts.map((t) => ({ x: t.x, y: t.y, w: t.w, h: t.h, size: t.size, color: t.color, text: t.text })),
      images: images.map((i) => ({ id: i.id, x: i.x, y: i.y, w: i.w, h: i.h })),
      bounds: { x: x0, y: y0, w: x1 - x0, h: y1 - y0 },
      mark: CLIP_MARK + uid(),
    };
    this.pasteCount = 0;
    // The mark goes to the system clipboard: Ctrl+V then pastes the items, not a
    // text copied earlier (and a text copied later wins over the items).
    try { navigator.clipboard?.writeText(this.clipboard.mark).catch(() => {}); } catch { /* not allowed */ }
    try {
      const json = JSON.stringify(this.clipboard);
      if (json.length <= CLIPBOARD_MAX_BYTES) localStorage.setItem(CLIPBOARD_PREF, json);
      else localStorage.removeItem(CLIPBOARD_PREF);   // too much for the storage: only this tab keeps it
    } catch { /* no storage available */ }
    this.showPaste();
    const n = strokes.length + texts.length + images.length;
    this.notice(n === 1 ? 'Copiato 1 elemento' : `Copiati ${n} elementi`);
    return true;
  }

  cut() {
    if (!this.hasSelection() || !this.copy()) return;
    this.removeSelection();
  }

  // Pasted at `target` ({page, x, y}: under the mouse, or where the menu was
  // opened), centred on that point; without a target, on the page in view, at
  // the same position if it is another page (or another document), shifted a
  // little if it is the page it was copied from. Everything stays inside the
  // page. The copies become the lasso selection, so they can be dragged right away.
  paste(target = null) {
    const c = this.clipboard;
    if (!c || !this.pages.length || this.blocked) return;
    const page = (target && this.page(target.page)) || this.pages[this.currentPageIndex()];
    const b = c.bounds;
    let dx = 0, dy = 0;
    if (target && this.page(target.page)) {
      dx = target.x - (b.x + b.w / 2);
      dy = target.y - (b.y + b.h / 2);
    } else if (c.doc === this.path && c.page === page.id) {
      this.pasteCount++;
      dx = dy = PASTE_OFFSET * this.pasteCount;
    }
    dx = Math.min(dx, page.w - (b.x + b.w)); dy = Math.min(dy, page.h - (b.y + b.h));
    dx = Math.max(dx, -b.x); dy = Math.max(dy, -b.y);
    this.deactivateText();
    this.selectTool('lasso');
    this.send({ type: 'paste', page: page.id, strokes: c.strokes, texts: c.texts,
      images: c.doc === this.path ? c.images : [], dx, dy });
    if (c.doc !== this.path && c.images.length) {
      this.showBanner('Le immagini si possono incollare solo nello stesso documento: incollato il resto.', { info: true });
    }
  }
}
