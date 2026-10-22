// VIEW — editor.
//
// Shows the document received from the controller on the computer and collects
// the input (Apple Pencil, mouse, finger, keyboard, photos). Every change is sent
// to the controller as an operation; the response holds the events notified by
// the model, which the view applies to its own display copy and redraws.
// A request always kept open towards the computer (/api/edit/listen) brings the
// changes made by other devices or on the computer.
// The rules (history, saving, validation) all live on the computer.
//
// Only presentation is handled here: chosen tool and colour, zoom (pinch too),
// stroke preview while the pen moves, eraser and lasso previews, palm
// rejection. Which strokes the eraser touches and what the lasso encloses is
// decided by the controller on the computer.
//
// The code is split by area in static/js/editor/: each module adds its methods
// to EditorView (at the end of this file); shared.js holds shared constants and functions.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { apiGetBinary, apiPost } from './api.js';
import { PDF_OPTIONS, COLORS, ERASER_DEFAULT, ERASER_PREF, WIDTH_DEFAULT, WIDTH_MIN, WIDTH_MAX, WIDTH_PREF,
  TEXT_SIZE_DEFAULT, TEXT_SIZE_MIN, TEXT_SIZE_MAX, TEXT_SIZE_PREF } from './editor/shared.js';
import { SyncMethods } from './editor/sync.js';
import { InputMethods } from './editor/input.js';
import { PagesMethods } from './editor/pages.js';
import { SelectionMethods } from './editor/selection.js';
import { ImagesMethods } from './editor/images.js';
import { ZoomMethods } from './editor/zoom.js';
import { ToolbarMethods } from './editor/toolbar.js';
import { RenderMethods } from './editor/render.js';
import { TextsMethods } from './editor/texts.js';

export class EditorView {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('editor-view');
    this.pagesEl = document.getElementById('pages');
    this.innerEl = document.createElement('div');   // container of the pages (used by zoom)
    this.innerEl.className = 'pages-inner';
    this.pagesEl.append(this.innerEl);
    this.statusEl = document.getElementById('status');
    this.devicesEl = document.getElementById('devices');
    this.bannerEl = document.getElementById('banner');
    this.undoBtn = document.getElementById('btn-undo');
    this.redoBtn = document.getElementById('btn-redo');
    this.colorsEl = document.getElementById('colors');
    this.toolbarEl = document.getElementById('toolbar');
    this.imageInput = document.getElementById('image-input');
    this.layoutBtn = document.getElementById('btn-layout');
    this.layoutDialog = document.getElementById('layout-dialog');
    this.selectionEl = this.buildSelectionEl();
    this.navEl = document.createElement('div');          // page and zoom indicator
    this.navEl.className = 'nav-indicator';
    this.element.append(this.navEl);
    this.eraserCursor = document.createElement('div');   // circle showing where the eraser erases
    this.eraserCursor.className = 'eraser-cursor';
    this.eraserRadius = ERASER_DEFAULT;                   // the user's choice, remembered on this iPad
    try { this.eraserRadius = Number(localStorage.getItem(ERASER_PREF)) || ERASER_DEFAULT; } catch { /* no storage available */ }
    // the user's choices (presentation)
    this.tool = 'pen';
    this.color = COLORS[0];
    this.width = this.storedNumber(WIDTH_PREF, WIDTH_DEFAULT, WIDTH_MIN, WIDTH_MAX);
    this.textSize = this.storedNumber(TEXT_SIZE_PREF, TEXT_SIZE_DEFAULT, TEXT_SIZE_MIN, TEXT_SIZE_MAX);
    this.fingerDraw = false;
    this.zoom = 1;
    this.scale = 1;
    this.noticeTimer = null;
    this.reset();
    this.bindInput();
    new ResizeObserver(() => {
      document.documentElement.style.setProperty('--toolbar-h', this.toolbarEl.offsetHeight + 'px');
    }).observe(this.toolbarEl);
  }

  reset() {
    this.session = null;
    this.path = '';
    this.pdf = null;
    this.pages = [];            // display copy received from the controller
    this.els = new Map();       // page id -> DOM elements
    this.pendingStrokes = new Map();  // strokes sent, waiting for confirmation
    this.hiddenStrokes = new Set();   // strokes erased with the eraser, waiting for confirmation
    this.gesture = null;
    this.pinch = null;
    this.queue = Promise.resolve();   // operations leave one at a time, in order
    this.inFlight = 0;
    this.blocked = false;
    this.lastStatus = 'saved';
    this.focusNewText = false;
    this.selection = null;      // items enclosed by the lasso (chosen by the controller)
    this.activeText = null;     // text box being edited: { page, id }
    this.layout = null;         // layout of the next pages (of the document)
    this.layouts = [];
    this.layoutDocs?.forEach((p) => p.then((d) => d?.destroy()).catch(() => {}));
    this.layoutDocs = new Map(); // backgrounds of new pages, per layout and size
    this.selectionEl?.remove();
    this.observer?.disconnect();
  }

  // =====================================================================
  // Showing / hiding the view (decided by the controller)
  // =====================================================================
  async show(data) {
    this.reset();
    this.session = data.session;
    this.path = data.path;
    this.pages = data.pages;
    this.layout = data.layout;
    this.layouts = data.layouts || [];
    this.showLayout();
    this.bannerEl.hidden = true;
    document.getElementById('doc-title').textContent = data.path.split('/').pop().replace(/\.pdf$/i, '');
    document.getElementById('doc-dot').style.background = data.color?.dot || '';
    document.title = data.path.split('/').pop() + ' · TapBook';
    this.setUndoState(data.canUndo, data.canRedo);
    this.showDevices(data.devices);
    this.setStatus('Caricamento…');
    this.showTool();
    this.showColor();
    this.showWidth();
    this.showTextSize(this.textSize);
    // Last part of the progress bar (if the opening is showing it): preparing the
    // PDF and drawing the first page.
    const progress = this.app.progress;
    const session = this.session;
    // The PDF is downloaded separately, as a binary file: measured progress, no
    // conversion to text, less data and less memory on the iPad.
    let bytes;
    try {
      bytes = await apiGetBinary('/api/edit/background', { session },
        (loaded, total) => progress.transfer('Scaricamento', loaded, total, 0.05, 0.85));
    } catch (e) {
      progress.fail();
      if (session === this.session) this.showBanner(`Il documento non si è scaricato (${e.message}).`);
      return;
    }
    if (session !== this.session) return;     // something else was opened in the meantime
    progress.set(0.88, 'Preparazione delle pagine…');
    this.firstPage = new Promise((resolve) => { this.firstDrawn = resolve; setTimeout(resolve, 3000); });
    this.firstPage.then(() => progress.done());
    this.pdf = await pdfjsLib.getDocument({ data: bytes, ...PDF_OPTIONS }).promise;
    progress.set(0.95);
    this.computeScale();
    this.buildPages();
    // Opened from a search result: go to the matching page.
    const start = data.startPage != null && this.pages[data.startPage];
    if (start) this.els.get(start.id).el.scrollIntoView({ block: 'start' });
    this.showStatus(data.status);
    this.listen(this.session);
  }

  // A choice remembered on this iPad, if valid; otherwise the default.
  storedNumber(key, fallback, min, max) {
    let n = NaN;
    try { n = Number(localStorage.getItem(key)); } catch { /* no storage available */ }
    return Number.isFinite(n) && n >= min && n <= max ? n : fallback;
  }

  hide() {
    this.els.forEach((v) => v.task?.cancel());
    this.innerEl.replaceChildren();
    this.pdf?.destroy();
    this.reset();
  }

  // Leaving: wait until the changes have reached the controller, then ask it to
  // close (saves right away) and switch to the view it names.
  async leave() {
    this.deactivateText();
    document.activeElement?.blur();
    await this.queue;
    if (!this.session) return;
    try {
      await this.app.request('/api/edit/close', { session: this.session });
    } catch (e) {
      this.app.navigate(this.path.split('/').slice(0, -1).join('/'));
    }
  }

  async close() {
    await this.queue;
    if (this.session) await apiPost('/api/edit/close', { session: this.session }).catch(() => {});
  }
}

// Methods of the individual areas, added to the class as they are.
for (const area of [SyncMethods, InputMethods, PagesMethods, SelectionMethods, ImagesMethods, ZoomMethods, ToolbarMethods, RenderMethods, TextsMethods]) {
  for (const name of Object.getOwnPropertyNames(area.prototype)) {
    if (name !== 'constructor') {
      Object.defineProperty(EditorView.prototype, name, Object.getOwnPropertyDescriptor(area.prototype, name));
    }
  }
}
