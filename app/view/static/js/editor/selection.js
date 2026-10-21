// VIEW — editor, lasso: selection, box, moving, colour, duplicating, deleting.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { SELECTION_PAD } from './shared.js';

export class SelectionMethods {
  // =====================================================================
  // Lasso: selection, moving, colour, copy, deletion
  // =====================================================================
  hasSelection() {
    const s = this.selection;
    return !!s && (s.strokes.size + s.texts.size + s.images.size) > 0;
  }

  selectionPayload() {
    const s = this.selection;
    return { page: s.page, strokes: [...s.strokes], texts: [...s.texts], images: [...s.images] };
  }

  clearSelection() {
    if (!this.selection) return;
    const page = this.page(this.selection.page);
    this.selection = null;
    this.showSelection();
    if (page) this.drawInk(page);
  }

  removeSelection() {
    this.send({ type: 'removeSelection', ...this.selectionPayload() });
    this.clearSelection();
  }

  // Dashed box around the selection, with the actions menu.
  // Dragging it moves the selected items.
  buildSelectionEl() {
    const el = document.createElement('div');
    el.className = 'selection';
    const menu = document.createElement('div');
    menu.className = 'selection-menu';
    const dup = document.createElement('button');
    dup.textContent = 'Duplica';
    dup.addEventListener('click', () => this.send({ type: 'duplicateSelection', ...this.selectionPayload() }));
    const del = document.createElement('button');
    del.textContent = 'Elimina';
    del.className = 'danger';
    del.addEventListener('click', () => this.removeSelection());
    menu.append(dup, del);
    el.append(menu);
    for (const b of [dup, del]) b.addEventListener('pointerdown', (e) => e.stopPropagation());
    el.addEventListener('pointerdown', (e) => this.dragSelection(e));
    return el;
  }

  // Bounds (PDF points) of the selected items, or null if none are left.
  selectionBounds(page) {
    const s = this.selection;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (ax, ay, bx, by) => { x0 = Math.min(x0, ax); y0 = Math.min(y0, ay); x1 = Math.max(x1, bx); y1 = Math.max(y1, by); };
    for (const st of page.strokes) {
      if (!s.strokes.has(st.id)) continue;
      const r = st.width / 2;
      for (const [x, y] of st.points) add(x - r, y - r, x + r, y + r);
    }
    for (const t of page.texts) if (s.texts.has(t.id)) add(t.x, t.y, t.x + t.w, t.y + t.h);
    for (const i of page.images) if (s.images.has(i.id)) add(i.x, i.y, i.x + i.w, i.y + i.h);
    return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  showSelection() {
    this.pagesEl.querySelectorAll('.selected').forEach((el) => el.classList.remove('selected'));
    const s = this.selection;
    const page = s && this.page(s.page);
    const v = page && this.els.get(page.id);
    if (s && page) {
      // Items removed in the meantime (also by other devices) leave the selection.
      s.strokes = new Set(page.strokes.filter((x) => s.strokes.has(x.id)).map((x) => x.id));
      s.texts = new Set(page.texts.filter((x) => s.texts.has(x.id)).map((x) => x.id));
      s.images = new Set(page.images.filter((x) => s.images.has(x.id)).map((x) => x.id));
    }
    const box = v && this.selectionBounds(page);
    if (!box) {
      this.selection = null;
      this.selectionEl.remove();
      if (page) this.drawInk(page);
      return;
    }
    v.texts.querySelectorAll('.textbox').forEach((el) => el.classList.toggle('selected', s.texts.has(el.dataset.id)));
    v.images.querySelectorAll('.imagebox').forEach((el) => el.classList.toggle('selected', s.images.has(el.dataset.id)));
    const k = this.scale, pad = SELECTION_PAD;
    Object.assign(this.selectionEl.style, {
      left: (box.x - pad) * k + 'px', top: (box.y - pad) * k + 'px',
      width: (box.w + 2 * pad) * k + 'px', height: (box.h + 2 * pad) * k + 'px', transform: '',
    });
    if (this.selectionEl.parentElement !== v.el) v.el.append(this.selectionEl);
    this.drawInk(page);
  }

  // Dragging the selection: during the gesture only the on-screen image moves;
  // at the end the move goes to the controller (one undo step).
  dragSelection(e) {
    if (!this.hasSelection()) return;
    e.preventDefault();
    e.stopPropagation();
    const el = this.selectionEl;
    try { el.setPointerCapture(e.pointerId); } catch { /* ignored */ }
    const s = this.selection;
    const page = this.page(s.page);
    const v = this.els.get(page.id);
    const moving = [...v.texts.querySelectorAll('.textbox.selected'), ...v.images.querySelectorAll('.imagebox.selected')];
    const start = { x: e.clientX, y: e.clientY };
    const move = (ev) => {
      s.dx = (ev.clientX - start.x) / this.scale;
      s.dy = (ev.clientY - start.y) / this.scale;
      const t = `translate(${s.dx * this.scale}px, ${s.dy * this.scale}px)`;
      el.style.transform = t;
      moving.forEach((m) => { m.style.transform = t; });
      this.drawInk(page);
    };
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
      const { dx, dy } = s;
      s.dx = s.dy = 0;
      moving.forEach((m) => { m.style.transform = ''; });
      if (this.selection !== s || (!dx && !dy)) { this.showSelection(); return; }
      // The new position is shown right away; the controller confirms it with its events.
      page.strokes = page.strokes.map((st) => (s.strokes.has(st.id)
        ? { ...st, points: st.points.map(([x, y, p]) => [x + dx, y + dy, p]) } : st));
      page.texts.forEach((t) => { if (s.texts.has(t.id)) { t.x += dx; t.y += dy; } });
      page.images.forEach((i) => { if (s.images.has(i.id)) { i.x += dx; i.y += dy; } });
      this.renderTexts(page);
      this.renderImages(page);
      this.showSelection();
      this.send({ type: 'moveSelection', ...this.selectionPayload(), dx, dy });
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  }
}
