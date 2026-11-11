// VIEW — editor, the menu on the page (right click of the mouse, or a finger held
// still) and pasting from the system clipboard: a copied text becomes a text box
// ready to be edited, a copied image a picture ready to be moved and resized;
// items copied with the lasso are pasted as such.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { CLIP_MARK } from './shared.js';

export class MenuMethods {
  buildMenuEl() {
    const el = document.createElement('div');
    el.className = 'ctx-menu';
    el.hidden = true;
    el.addEventListener('pointerdown', (e) => e.stopPropagation());
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    this.element.append(el);
    document.addEventListener('pointerdown', (e) => { if (!el.contains(e.target)) this.hideMenu(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hideMenu(); });
    this.pagesEl.addEventListener('scroll', () => this.hideMenu(), { passive: true });
    return el;
  }

  // Menu at (cx, cy) on screen; the actions refer to the page under that point.
  showMenu(cx, cy) {
    const el = this.menuEl;
    const page = this.pageAt(cx, cy);
    if (!page || this.blocked) return;
    const target = this.pointAt(page, cx, cy);
    const item = (label, action, { danger = false, disabled = false } = {}) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.disabled = disabled;
      if (danger) b.className = 'danger';
      b.addEventListener('click', () => { this.hideMenu(); action(); });
      return b;
    };
    const items = [];
    if (this.hasSelection() || this.activeText) items.push(item('Copia', () => this.copy()));
    if (this.hasSelection()) {
      items.push(item('Taglia', () => this.cut()));
      items.push(item('Duplica', () => this.send({ type: 'duplicateSelection', ...this.selectionPayload() })));
    }
    items.push(item('Incolla', () => this.pasteFromSystem(target)));
    if (this.hasSelection()) items.push(item('Elimina', () => this.removeSelection(), { danger: true }));
    el.replaceChildren(...items);
    el.hidden = false;
    // Inside the screen, near the point (the menu is fixed to the viewport).
    const w = el.offsetWidth, h = el.offsetHeight;
    el.style.left = Math.max(8, Math.min(cx + 2, window.innerWidth - w - 8)) + 'px';
    el.style.top = Math.max(8, Math.min(cy + 2, window.innerHeight - h - 8)) + 'px';
  }

  hideMenu() {
    if (this.menuEl && !this.menuEl.hidden) this.menuEl.hidden = true;
  }

  // Point of the page (PDF coordinates) under (cx, cy) on screen.
  pointAt(page, cx, cy) {
    const r = this.els.get(page.id).el.getBoundingClientRect();
    return { page: page.id, x: Math.max(0, Math.min(page.w, (cx - r.left) / this.scale)),
      y: Math.max(0, Math.min(page.h, (cy - r.top) / this.scale)) };
  }

  // Where to paste with the keyboard: under the mouse (or the hovering pen) if it
  // is over a page, otherwise the middle of the page in view.
  pointerTarget() {
    const p = this.pointer;
    const page = p && this.pageAt(p.x, p.y);
    if (page) return this.pointAt(page, p.x, p.y);
    const current = this.pages[this.currentPageIndex()];
    if (!current) return null;
    const r = this.els.get(current.id).el.getBoundingClientRect(), view = this.pagesEl.getBoundingClientRect();
    const midY = (Math.max(r.top, this.viewTop()) + Math.min(r.bottom, view.bottom)) / 2;
    return { page: current.id, x: current.w / 2, y: Math.max(0, Math.min(current.h, (midY - r.top) / this.scale)) };
  }

  // Pasting what a "paste" event (Ctrl+V) brings: dt is its DataTransfer.
  pasteData(dt, target) {
    if (!target) return;
    const files = dt ? [...dt.files].filter((f) => f.type.startsWith('image/')) : [];
    const text = dt ? dt.getData('text/plain') : '';
    if (text && text.startsWith(CLIP_MARK) && this.clipboard && text === this.clipboard.mark) { this.paste(target); return; }
    if (files.length) { this.pasteImage(target, files[0]); return; }
    if (text.trim()) { this.pasteText(target, text); return; }
    if (this.clipboard) this.paste(target);
    else this.notice('Niente da incollare');
  }

  // From the menu: the system clipboard is read with the browser's permission (the
  // iPad shows a small "Incolla" bubble to confirm). Browsers that do not allow it
  // fall back to our own copied items.
  async pasteFromSystem(target) {
    if (!target) return;
    let items = null;
    try {
      items = await navigator.clipboard.read();
    } catch {
      try {
        const text = await navigator.clipboard.readText();
        if (text) items = [{ types: ['text/plain'], getType: async () => new Blob([text], { type: 'text/plain' }) }];
      } catch { /* not allowed: our own items below */ }
    }
    if (items === null) {
      if (this.clipboard) this.paste(target);
      else this.notice('Il browser non lascia leggere gli appunti: usa Ctrl+V');
      return;
    }
    for (const it of items) {
      const image = it.types.find((t) => t.startsWith('image/'));
      if (image) {
        const blob = await it.getType(image);
        this.pasteImage(target, new File([blob], 'incollata.' + (image.split('/')[1] || 'png').replace('jpeg', 'jpg'), { type: image }));
        return;
      }
    }
    for (const it of items) {
      if (it.types.includes('text/plain')) {
        const text = await (await it.getType('text/plain')).text();
        if (text.startsWith(CLIP_MARK) && this.clipboard && text === this.clipboard.mark) { this.paste(target); return; }
        if (text.trim()) { this.pasteText(target, text); return; }
      }
    }
    if (this.clipboard) this.paste(target);
    else this.notice('Niente da incollare');
  }

  // A picture at the point, with the image tool so it can be moved and resized at once.
  pasteImage(target, file) {
    this.deactivateText();
    this.clearSelection();
    this.uploadImage(target, file);
  }

  // A text box with the text at the point, with the text tool and the cursor in it.
  pasteText(target, text) {
    this.deactivateText();
    this.selectTool('text');
    this.focusNewText = true;
    this.fitNewText = true;
    this.send({ type: 'addText', page: target.page, x: target.x, y: target.y, color: this.color, size: this.textSize,
      text: text.replace(/\r\n?/g, '\n').slice(0, 20000) });
  }
}
