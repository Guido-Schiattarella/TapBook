// VIEW — editor, toolbar and messages: save status, connected devices, notices, tool and colour.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { icon } from '../format.js';

export class ToolbarMethods {
  // =====================================================================
  // Presentation
  // =====================================================================
  setStatus(text, error = false) {
    this.statusEl.textContent = text;
    this.statusEl.classList.toggle('error', error);
  }

  showStatus(status) {
    if (this.inFlight > 0 || this.noticeTimer) return;
    if (status === 'error') this.setStatus('Errore di salvataggio, riprovo…', true);
    else if (status === 'pending') this.setStatus('Modifiche…');
    else this.setStatus('Salvato');
  }

  showDevices(count) {
    if (count === undefined) return;
    this.devicesEl.hidden = count < 2;
    this.devicesEl.replaceChildren(icon('devices'), String(count));
    this.devicesEl.title = `Documento aperto su ${count} dispositivi`;
  }

  // Temporary message in place of the status.
  notice(text) {
    clearTimeout(this.noticeTimer);
    this.noticeTimer = null;
    this.setStatus(text);
    this.noticeTimer = setTimeout(() => { this.noticeTimer = null; this.showStatus(this.lastStatus); }, 3000);
  }

  // info: just a notice to read (OK button); otherwise a reload is needed.
  showBanner(text, { info = false } = {}) {
    this.bannerEl.replaceChildren();
    const span = document.createElement('span');
    span.textContent = text;
    const button = document.createElement('button');
    button.textContent = info ? 'OK' : 'Ricarica';
    button.addEventListener('click', () => (info ? (this.bannerEl.hidden = true) : location.reload()));
    this.bannerEl.append(span, button);
    this.bannerEl.hidden = false;
  }

  setUndoState(canUndo, canRedo) {
    this.undoBtn.disabled = !canUndo;
    this.redoBtn.disabled = !canRedo;
  }

  showTool() {
    if (document.activeElement?.tagName === 'TEXTAREA') document.activeElement.blur();
    document.querySelectorAll('.tool[data-tool]').forEach((b) => b.classList.toggle('active', b.dataset.tool === this.tool));
    this.pagesEl.classList.toggle('tool-text', this.tool === 'text');
    this.pagesEl.classList.toggle('tool-image', this.tool === 'image');
    this.pagesEl.classList.toggle('tool-lasso', this.tool === 'lasso');
    // With the eraser, its sizes appear in place of colours and thickness.
    const eraser = this.tool === 'eraser';
    this.colorsEl.hidden = eraser;
    document.getElementById('width').hidden = eraser;
    document.getElementById('eraser-sizes').hidden = !eraser;
    document.querySelectorAll('#eraser-sizes .size').forEach((b) =>
      b.classList.toggle('active', Number(b.dataset.radius) === this.eraserRadius));
    if (!eraser) this.hideEraserCursor();
  }

  showColor() {
    this.colorsEl.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.color === this.color));
  }
}
