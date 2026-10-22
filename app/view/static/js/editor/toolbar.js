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
    if (this.tool !== 'text') this.deactivateText();
    if (document.activeElement?.tagName === 'TEXTAREA') document.activeElement.blur();
    document.querySelectorAll('.tool[data-tool]').forEach((b) => b.classList.toggle('active', b.dataset.tool === this.tool));
    this.pagesEl.classList.toggle('tool-text', this.tool === 'text');
    this.pagesEl.classList.toggle('tool-image', this.tool === 'image');
    this.pagesEl.classList.toggle('tool-lasso', this.tool === 'lasso');
    // With the eraser, its sizes appear in place of colours and thickness; with
    // text, the font size in place of the thickness.
    const eraser = this.tool === 'eraser', text = this.tool === 'text';
    this.colorsEl.hidden = eraser;
    document.getElementById('width-control').hidden = eraser || text;
    document.getElementById('text-size-control').hidden = !text;
    document.getElementById('eraser-sizes').hidden = !eraser;
    document.querySelectorAll('#eraser-sizes .size').forEach((b) =>
      b.classList.toggle('active', Number(b.dataset.radius) === this.eraserRadius));
    if (!eraser) this.hideEraserCursor();
  }

  // Thickness next to the slider: value in points and a dot as thick as the stroke.
  showWidth() {
    const w = this.width;
    document.getElementById('width-value').textContent = (w < 1 ? w.toFixed(2) : w.toFixed(1)).replace('.', ',');
    const d = Math.max(1, Math.min(22, w * this.scale));
    Object.assign(document.getElementById('width-preview').style, { width: d + 'px', height: d + 'px' });
  }

  // Font size shown in the toolbar: of the active box, or of the next new one.
  showTextSize(size) {
    document.getElementById('text-size').value = Math.round(size);
    document.getElementById('text-size-value').textContent = Math.round(size) + ' pt';
  }

  showColor() {
    this.colorsEl.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.color === this.color));
  }
}
