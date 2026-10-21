// VIEW — editor, text boxes: position, size, writing in chunks.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { TYPING_DELAY } from './shared.js';

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

  updateTextbox(page, t) {
    const el = this.els.get(page.id)?.texts.querySelector(`.textbox[data-id="${t.id}"]`);
    if (!el) return;
    const ta = el.querySelector('textarea');
    if (!this.isEditing(t.id) && ta.value !== t.text) ta.value = t.text;  // e.g. after an "undo"
    this.placeTextbox(el, t);
  }

  focusText(id) {
    this.pagesEl.querySelector(`.textbox[data-id="${id}"] textarea`)?.focus();
  }

  placeTextbox(el, t) {
    const k = this.scale;
    Object.assign(el.style, { left: t.x * k + 'px', top: t.y * k + 'px', width: t.w * k + 'px', height: t.h * k + 'px' });
    const ta = el.querySelector('textarea');
    ta.style.fontSize = t.size * k + 'px';
    ta.style.color = t.color;
  }

  // Height (in PDF points) needed to show all the text.
  measureText(t, ta) {
    ta.style.height = 'auto';
    const needed = ta.scrollHeight / this.scale;
    ta.style.height = '';
    return Math.max(t.size * 1.6, needed + 4);
  }

  textboxEl(page, t) {
    const el = document.createElement('div');
    el.className = 'textbox';
    el.dataset.id = t.id;
    const ta = document.createElement('textarea');
    ta.value = t.text;
    ta.spellcheck = false;
    const handle = document.createElement('button');
    handle.className = 'handle';
    handle.textContent = '✥ sposta';
    const remove = document.createElement('button');
    remove.className = 'remove';
    remove.textContent = '✕';
    el.append(handle, remove, ta);
    this.placeTextbox(el, t);

    let typingTimer = null;
    let typed = false;  // text changed since the box received the cursor
    const sendText = (commit) => {
      clearTimeout(typingTimer);
      t.text = ta.value;
      this.send({ type: 'editText', page: page.id, id: t.id, text: ta.value, h: t.h, commit });
    };
    ta.addEventListener('focus', () => { typed = false; });
    ta.addEventListener('input', () => {
      typed = true;
      t.h = this.measureText(t, ta);  // the box grows right away, the text goes to the computer in chunks
      this.placeTextbox(el, t);
      clearTimeout(typingTimer);
      typingTimer = setTimeout(() => sendText(false), TYPING_DELAY);
    });
    ta.addEventListener('blur', () => {
      if (!el.isConnected || !this.session) return;
      clearTimeout(typingTimer);
      // End of editing: an empty box is removed; otherwise it becomes an "undo" step.
      if (!ta.value.trim()) this.send({ type: 'discardText', page: page.id, id: t.id });
      else if (typed) sendText(true);
    });
    remove.addEventListener('click', () => this.send({ type: 'removeText', page: page.id, id: t.id }));
    // Dragging by the handle: it moves here right away, the final position goes to the computer.
    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      try { handle.setPointerCapture(e.pointerId); } catch { /* ignored */ }
      const start = { x: e.clientX, y: e.clientY, tx: t.x, ty: t.y };
      const move = (ev) => {
        t.x = start.tx + (ev.clientX - start.x) / this.scale;
        t.y = start.ty + (ev.clientY - start.y) / this.scale;
        this.placeTextbox(el, t);
      };
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        if (t.x !== start.tx || t.y !== start.ty) this.send({ type: 'moveText', page: page.id, id: t.id, x: t.x, y: t.y });
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
    return el;
  }
}
