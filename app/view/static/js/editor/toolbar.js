// VIEW — editor, toolbar and messages: save status, connected devices, notices, tool and colour.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { icon } from '../format.js';
import { COLORS, HIGHLIGHTER_COLOR, COLORS_PREF } from './shared.js';

export class ToolbarMethods {
  // =====================================================================
  // Presentation
  // =====================================================================
  // While a finger moves the sheet (or two fingers zoom) the status waits: the
  // gesture is never disturbed by news from the computer, which arrive on their own
  // (nothing here waits for them). It is shown as soon as the fingers are lifted.
  setStatus(text, error = false) {
    if (this.gesturing()) { this.laterStatus = [text, error]; return; }
    this.laterStatus = null;
    this.statusEl.textContent = text;
    this.statusEl.classList.toggle('error', error);
  }

  gesturing() {
    return !!(this.finger?.moved || this.pinch);
  }

  // Fingers lifted: the latest status received meanwhile is shown.
  flushStatus() {
    const later = this.laterStatus;
    if (later) this.setStatus(...later);
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
    document.getElementById('width-presets').hidden = eraser || text;
    if (!eraser && !text) this.showWidth();      // each tool has its own thickness
    document.getElementById('text-size-control').hidden = !text;
    document.getElementById('eraser-sizes').hidden = !eraser;
    document.querySelectorAll('#eraser-sizes .size').forEach((b) =>
      b.classList.toggle('active', Number(b.dataset.radius) === this.eraserRadius));
    if (!eraser) this.hideEraserCursor();
  }

  // Font size shown in the toolbar: of the active box, or of the next new one.
  showTextSize(size) {
    document.getElementById('text-size').value = Math.round(size);
    document.getElementById('text-size-value').textContent = Math.round(size) + ' pt';
  }

  showColor() {
    this.colorsEl.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.color === this.color));
  }

  // --- colour of each tool -------------------------------------------------------------
  // The highlighter keeps its own colour; pen, shapes and text share one.
  colorKey() {
    return this.tool === 'highlighter' ? 'highlighter' : 'ink';
  }

  get color() {
    return this.colors[this.colorKey()];
  }

  set color(value) {
    this.colors[this.colorKey()] = value;
    try { localStorage.setItem(COLORS_PREF, JSON.stringify(this.colors)); } catch { /* no storage available */ }
  }

  loadColors() {
    const valid = (c) => typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c);
    let stored = {};
    try { stored = JSON.parse(localStorage.getItem(COLORS_PREF) || '{}') || {}; } catch { /* defaults */ }
    this.colors = { ink: valid(stored.ink) ? stored.ink : COLORS[0],
      highlighter: valid(stored.highlighter) ? stored.highlighter : HIGHLIGHTER_COLOR };
  }

  // "Incolla" is available only when something was copied.
  showPaste() {
    const has = !!this.clipboard;
    document.getElementById('btn-paste').disabled = !has;
    document.getElementById('btn-paste').title = has ? 'Incolla (Ctrl+V) sulla pagina in vista' : 'Niente da incollare: cerchia con il lazzo e scegli Copia';
  }

  // Page button in the toolbar: "3 / 8" (tapping it opens the page chooser).
  showPageButton(index = this.currentPageIndex()) {
    document.getElementById('pages-label').textContent = this.pages.length ? `${index + 1} / ${this.pages.length}` : '';
  }
}
