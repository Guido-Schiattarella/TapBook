// VIEW — editor, text boxes: position, size, font size, writing in chunks.
// EditorView methods (see editor_view.js): here `this` is the editor.
//
// In text mode, tapping a box enters it: it becomes the active box, highlighted,
// with the handles to move, resize and delete it, and the toolbar shows its font
// size. Esc (or a tap elsewhere on the page) leaves it: it is no longer
// highlighted, and if it was left empty it disappears.
import { TYPING_DELAY, TEXT_W_MIN, TEXT_LAYOUT_SCALE } from './shared.js';

export class TextsMethods {
  // =====================================================================
  // Text boxes
  // =====================================================================
  renderTexts(page) {
    const v = this.els.get(page.id);
    if (v) v.texts.replaceChildren(...page.texts.map((t) => this.textboxEl(page, t)));
  }

  isEditing(textId) {
    return document.activeElement?.closest?.('.textbox')?.dataset.id === textId;
  }

  textboxOf(pageId, textId) {
    return this.els.get(pageId)?.texts.querySelector(`.textbox[data-id="${textId}"]`) || null;
  }

  updateTextbox(page, t) {
    const el = this.textboxOf(page.id, t.id);
    if (!el) return;
    const ta = el.querySelector('textarea');
    if (!this.isEditing(t.id) && ta.value !== t.text) ta.value = t.text;  // e.g. after an "undo"
    this.placeTextbox(el, t);
    if (this.activeText?.id === t.id) this.showTextSize(t.size);
  }

  focusText(id) {
    this.pagesEl.querySelector(`.textbox[data-id="${id}"] textarea`)?.focus();
  }

  // The box (with its handles) follows the zoom; the text inside is laid out always
  // at the same scale (TEXT_LAYOUT_SCALE pixels per PDF point) and only enlarged or
  // reduced on screen. Laid out at the zoom's own size, the browser rounded lines
  // and letters differently at every zoom (Safari rounds each line's height to
  // whole pixels): the text moved up or down over the page, and a word could even
  // wrap differently. Now lines and wrapping are the same at any zoom.
  placeTextbox(el, t) {
    const k = this.scale, b = TEXT_LAYOUT_SCALE;
    Object.assign(el.style, { left: t.x * k + 'px', top: t.y * k + 'px', width: t.w * k + 'px', height: t.h * k + 'px' });
    const ta = el.querySelector('textarea');
    Object.assign(ta.style, { width: t.w * b + 'px', height: t.h * b + 'px', fontSize: t.size * b + 'px',
      transform: `scale(${k / b})`, color: t.color });
  }

  // Height (in PDF points) needed to show all the text at the box's current width
  // (measured in the fixed layout, so the same at any zoom).
  measureText(t, ta) {
    const height = ta.style.height;
    ta.style.height = 'auto';
    const needed = ta.scrollHeight / TEXT_LAYOUT_SCALE;
    ta.style.height = height;
    return Math.max(t.size * 1.6, needed + 4);
  }

  // --- active box -------------------------------------------------------------------
  activeTextData() {
    const a = this.activeText;
    const page = a && this.page(a.page);
    const t = page?.texts.find((x) => x.id === a.id);
    return t ? { page, t, el: this.textboxOf(page.id, t.id) } : null;
  }

  activateText(page, t) {
    if (this.activeText?.id === t.id) return;
    this.deactivateText();
    this.activeText = { page: page.id, id: t.id };
    this.textboxOf(page.id, t.id)?.classList.add('active');
    this.showTextSize(t.size);
  }

  // Leaves the active box: the cursor goes away, the box is no longer highlighted
  // and, if it was left empty, it is removed.
  deactivateText() {
    const data = this.activeTextData();
    this.activeText = null;
    if (!data) return;
    const { page, t, el } = data;
    el?.classList.remove('active');
    const ta = el?.querySelector('textarea');
    if (ta && document.activeElement === ta) ta.blur();     // sends what was typed
    if (!(ta ? ta.value : t.text).trim()) this.send({ type: 'discardText', page: page.id, id: t.id });
    this.showTextSize(this.textSize);
  }

  // Font size or colour chosen in the toolbar for the active box. `final` false =
  // the slider is still moving: only the box on screen changes.
  styleActiveText(changes, final = true) {
    const data = this.activeTextData();
    if (!data?.el) return;
    const { page, t, el } = data;
    Object.assign(t, changes);
    this.placeTextbox(el, t);
    if ('size' in changes) {
      t.h = this.measureText(t, el.querySelector('textarea'));   // the box fits the new size
      this.placeTextbox(el, t);
    }
    if (final) {
      const op = { type: 'changeText', page: page.id, id: t.id, ...changes };
      if ('size' in changes) op.h = t.h;
      this.send(op);
    }
  }

  textboxEl(page, t) {
    const el = document.createElement('div');
    el.className = 'textbox';
    el.dataset.id = t.id;
    if (this.activeText?.id === t.id) el.classList.add('active');
    const ta = document.createElement('textarea');
    ta.value = t.text;
    ta.spellcheck = false;
    const handle = document.createElement('button');
    handle.className = 'handle';
    handle.textContent = '✥ sposta';
    handle.title = 'Trascina per spostare la casella';
    const remove = document.createElement('button');
    remove.className = 'remove';
    remove.textContent = '✕';
    remove.title = 'Elimina la casella';
    const resize = document.createElement('button');
    resize.className = 'resize';
    resize.title = 'Trascina per ridimensionare la casella';
    el.append(handle, remove, ta, resize);
    this.placeTextbox(el, t);

    let typingTimer = null;
    let typed = false;  // text changed since the box received the cursor
    const sendText = (commit) => {
      clearTimeout(typingTimer);
      t.text = ta.value;
      this.send({ type: 'editText', page: page.id, id: t.id, text: ta.value, h: t.h, commit });
    };
    ta.addEventListener('focus', () => { typed = false; this.activateText(page, t); });
    ta.addEventListener('input', () => {
      typed = true;
      // The box grows right away (it never shrinks below the size given by hand),
      // the text goes to the computer in chunks.
      t.h = Math.max(t.h, this.measureText(t, ta));
      this.placeTextbox(el, t);
      clearTimeout(typingTimer);
      typingTimer = setTimeout(() => sendText(false), TYPING_DELAY);
    });
    ta.addEventListener('blur', () => {
      if (!el.isConnected || !this.session) return;
      clearTimeout(typingTimer);
      // End of the edit: it becomes an "undo" step. The box stays active (the
      // toolbar or its handles may have taken the focus): it is left with Esc
      // or by tapping elsewhere, and only then removed if empty.
      if (typed && ta.value.trim()) sendText(true);
      typed = false;
    });
    remove.addEventListener('click', () => {
      if (this.activeText?.id === t.id) this.activeText = null;
      this.showTextSize(this.textSize);
      this.send({ type: 'removeText', page: page.id, id: t.id });
    });
    // Dragging by the handle: it moves here right away, the final position goes to
    // the computer. Dropped on another page, the box moves to that page (otherwise
    // it would stay on this one, drawn over the other, where it could no longer be tapped).
    this.dragTextHandle(handle, (start, dx, dy) => {
      t.x = start.x + dx;
      t.y = start.y + dy;
      this.placeTextbox(el, t);
    }, (start, ev) => {
      const target = this.dropPage(page, el, ev);
      if (target) {
        this.deactivateText();
        this.send({ type: 'moveText', page: page.id, id: t.id, x: target.x, y: target.y, toPage: target.page.id });
      } else if (t.x !== start.x || t.y !== start.y) {
        this.send({ type: 'moveText', page: page.id, id: t.id, x: t.x, y: t.y });
      }
    }, t);
    // Bottom-right corner: width and height. The height never goes below what the text needs.
    this.dragTextHandle(resize, (start, dx, dy) => {
      t.w = Math.max(TEXT_W_MIN, start.w + dx);
      this.placeTextbox(el, t);
      t.h = Math.max(this.measureText(t, ta), start.h + dy);
      this.placeTextbox(el, t);
    }, (start) => {
      if (t.w !== start.w || t.h !== start.h) this.send({ type: 'changeText', page: page.id, id: t.id, w: t.w, h: t.h });
    }, t);
    return el;
  }

  // Page under the pointer when a box or an image is released, if it is another
  // page: { page, x, y } with the item's top-left corner in that page's coordinates.
  dropPage(page, el, ev) {
    const target = ev && this.pageAt(ev.clientX, ev.clientY);
    const v = target && target.id !== page.id && this.els.get(target.id);
    if (!v) return null;
    const r = el.getBoundingClientRect(), tr = v.el.getBoundingClientRect();
    return { page: target, x: (r.left - tr.left) / this.scale, y: (r.top - tr.top) / this.scale };
  }

  // Dragging one of the box's handles: move(start, dx, dy) while dragging (in PDF
  // points), done(start) when released.
  dragTextHandle(button, move, done, t) {
    button.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      try { button.setPointerCapture(e.pointerId); } catch { /* ignored */ }
      const start = { cx: e.clientX, cy: e.clientY, x: t.x, y: t.y, w: t.w, h: t.h };
      let last = e;
      const onMove = (ev) => { last = ev; move(start, (ev.clientX - start.cx) / this.scale, (ev.clientY - start.cy) / this.scale); };
      const onUp = () => {
        button.removeEventListener('pointermove', onMove);
        button.removeEventListener('pointerup', onUp);
        button.removeEventListener('pointercancel', onUp);
        done(start, last);
      };
      button.addEventListener('pointermove', onMove);
      button.addEventListener('pointerup', onUp);
      button.addEventListener('pointercancel', onUp);
    });
  }
}
