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
import { apiGetBinary, apiPost } from './api.js';
import { getBackground, putBackground, dropBackground } from './bgcache.js';
import { ERASER_DEFAULT, ERASER_PREF, LEAVE_WAIT_MS,
  TEXT_SIZE_DEFAULT, TEXT_SIZE_MIN, TEXT_SIZE_MAX, TEXT_SIZE_PREF } from './editor/shared.js';
import { Painter } from './editor/painter.js';
import { SyncMethods } from './editor/sync.js';
import { InputMethods } from './editor/input.js';
import { PagesMethods } from './editor/pages.js';
import { SelectionMethods } from './editor/selection.js';
import { ImagesMethods } from './editor/images.js';
import { ZoomMethods } from './editor/zoom.js';
import { ToolbarMethods } from './editor/toolbar.js';
import { RenderMethods } from './editor/render.js';
import { TextsMethods } from './editor/texts.js';
import { WidthMethods } from './editor/widths.js';
import { NavigationMethods } from './editor/navigation.js';
import { ClipboardMethods } from './editor/clipboard.js';
import { TouchMethods } from './editor/touch.js';
import { MenuMethods } from './editor/menu.js';

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
    this.painter = new Painter();                         // draws the PDF backgrounds, in a worker when it can
    this.layoutBtn = document.getElementById('btn-layout');
    this.layoutDialog = document.getElementById('layout-dialog');
    this.pageDialog = document.getElementById('page-dialog');
    this.selectionEl = this.buildSelectionEl();
    this.menuEl = this.buildMenuEl();                     // right click / long press (menu.js)
    this.navEl = document.createElement('button');       // page and zoom indicator (tap: page chooser)
    this.navEl.className = 'nav-indicator';
    this.navEl.type = 'button';
    this.navEl.title = 'Scegli la pagina';
    this.element.append(this.navEl);
    this.eraserCursor = document.createElement('div');   // circle showing where the eraser erases
    this.eraserCursor.className = 'eraser-cursor';
    this.eraserRadius = ERASER_DEFAULT;                   // the user's choice, remembered on this iPad
    try { this.eraserRadius = Number(localStorage.getItem(ERASER_PREF)) || ERASER_DEFAULT; } catch { /* no storage available */ }
    // the user's choices (presentation)
    this.tool = 'pen';
    this.loadColors();                                    // colour of each tool (toolbar.js)
    this.loadWidths();                                    // thickness of each tool (widths.js)
    this.loadClipboard();                                 // what was copied (clipboard.js)
    this.penLast = 0;                                     // when the Pencil last touched the page
    this.toolBeforeEraser = null;
    this.textSize = this.storedNumber(TEXT_SIZE_PREF, TEXT_SIZE_DEFAULT, TEXT_SIZE_MIN, TEXT_SIZE_MAX);
    this.fingerDraw = false;
    this.zoom = 1;
    this.scale = 1;
    this.noticeTimer = null;
    this.reset();
    this.bindInput();
    // Page reloaded or closed: the computer is told right away that this tab
    // leaves the document (otherwise it would count as connected until it goes idle).
    window.addEventListener('pagehide', () => this.closeOnExit());
    new ResizeObserver(() => {
      document.documentElement.style.setProperty('--toolbar-h', this.toolbarEl.offsetHeight + 'px');
    }).observe(this.toolbarEl);
  }

  reset() {
    this.openId = (this.openId || 0) + 1;   // a new document (or none): operations queued for the old one are dropped
    this.session = null;
    this.path = '';
    this.ready = false;
    this.bgDocs = new Map();    // background id -> Promise<true> once the painter has it, see loadBackgrounds
    this.pages = [];            // display copy received from the controller
    this.els = new Map();       // page id -> DOM elements
    this.pendingStrokes = new Map();  // strokes sent, waiting for confirmation
    this.hiddenStrokes = new Set();   // strokes erased with the eraser, waiting for confirmation
    this.gesture = null;
    this.pinch = null;
    this.finger = null;         // finger scrolling the sheet (touch.js)
    this.pencilIds = new Set(); // touch identifiers that are the Pencil (touch.js)
    this.penDown = false;       // the Pencil is touching the screen (input.js, touch.js)
    this.penHold = null;        // scroll position held while the Pencil is down (input.js, holdSheet)
    this.scrollDir = null;      // last direction of the scrolling (render.js draws further that way)
    this.deferredRenders = new Set();   // pages to draw once the sheet stops (render.js)
    this.cancelLongPress?.();
    this.longPressed = false;
    this.hideMenu?.();
    this.fitNewText = false;
    this.queue = Promise.resolve();   // operations leave one at a time, in order
    this.inFlight = 0;
    this.blocked = false;
    this.lastStatus = 'saved';
    this.focusNewText = false;
    this.selection = null;      // items enclosed by the lasso (chosen by the controller)
    this.activeText = null;     // text box being edited: { page, id }
    this.layout = null;         // layout of the next pages (of the document)
    this.layouts = [];
    this.layoutDocs?.forEach((_, key) => this.painter.close('layout:' + key));
    this.layoutDocs = new Map(); // backgrounds of new pages, per layout and size -> Promise<painter key|null>
    this.pasteCount = 0;        // pastes on the same page since the copy (each one shifted a little more)
    this.position = null;       // last page/offset reported to the computer
    this.startAt = null;
    clearTimeout(this.positionTimer);
    this.positionTimer = null;
    this.selectionEl?.remove();
    this.observer?.disconnect();
    this.thumbObserver?.disconnect();
    this.thumbObserver = null;
  }

  // =====================================================================
  // Showing / hiding the view (decided by the controller)
  // =====================================================================
  async show(data) {
    // Shown again (reopening after a pause): the previous PDF and its pages are
    // freed first, otherwise every reopening would keep one more copy in memory.
    this.els?.forEach((v) => this.discardPage(v));
    this.destroyBackgrounds();
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
    this.showPaste();
    this.showTextSize(this.textSize);
    // Last part of the progress bar (if the opening is showing it): the backgrounds
    // (PDF without the notes) this device does not have yet, then the first page.
    const progress = this.app.progress;
    const session = this.session;
    try {
      await this.loadBackgrounds(data.backgrounds || {}, (loaded, total) =>
        progress.transfer('Scaricamento', loaded, total, 0.05, 0.85));
    } catch (e) {
      progress.fail();
      if (session === this.session) this.showBanner(`Il documento non si è scaricato (${e.message}).`);
      return;
    }
    if (session !== this.session) return;     // something else was opened in the meantime
    progress.set(0.9, 'Preparazione delle pagine…');
    this.firstPage = new Promise((resolve) => { this.firstDrawn = resolve; setTimeout(resolve, 3000); });
    this.firstPage.then(() => progress.done());
    this.ready = true;
    this.computeScale();
    this.buildPages();
    // Opened from a search result, or where the reader stopped last time: go there.
    const start = data.startPage != null && this.pages[data.startPage];
    if (start) this.goToPage(data.startPage, { offset: data.startOffset || 0 });
    this.position = start ? { page: data.startPage, offset: data.startOffset || 0 } : null;
    this.showPageButton();
    this.showStatus(data.status);
    this.listen(this.session);
  }

  // Backgrounds of the document: those already on this device are taken from its
  // cache, the others downloaded (all together in the progress) and kept for next
  // time. sizes: {background id: bytes}, from the controller.
  async loadBackgrounds(sizes, onProgress) {
    const user = this.app.user;
    const missing = [];
    for (const id of Object.keys(sizes)) {
      if (this.bgDocs.has(id)) continue;
      const bytes = await getBackground(user, id);
      if (bytes) this.bgDocs.set(id, this.openBackground(id, bytes, true));
      else missing.push(id);
    }
    const total = missing.reduce((t, id) => t + (sizes[id] || 0), 0);
    let done = 0;
    for (const id of missing) {
      const bytes = await apiGetBinary('/api/edit/background', { session: this.session, id },
        (loaded) => onProgress?.(done + loaded, total));
      done += bytes.length;
      putBackground(user, id, bytes.slice());   // kept for next time (a copy: pdf.js takes the bytes)
      this.bgDocs.set(id, this.openBackground(id, bytes, false));
    }
  }

  // Hands a background to the painter. If one taken from the cache cannot be read,
  // it is removed from the cache and downloaded again.
  openBackground(id, bytes, cached) {
    const opening = this.painter.open('bg:' + id, bytes).then(() => true);
    if (!cached) return opening;
    return opening.catch(async () => {
      await dropBackground(this.app.user, id);
      const fresh = await apiGetBinary('/api/edit/background', { session: this.session, id });
      putBackground(this.app.user, id, fresh.slice());
      return this.painter.open('bg:' + id, fresh).then(() => true);
    });
  }

  // Backgrounds no longer used by any page (keep: ids still needed) are closed.
  destroyBackgrounds(keep = new Set()) {
    for (const id of [...(this.bgDocs?.keys() || [])]) {
      if (keep.has(id)) continue;
      this.painter.close('bg:' + id);
      this.bgDocs.delete(id);
    }
  }

  // A choice remembered on this iPad, if valid; otherwise the default.
  storedNumber(key, fallback, min, max) {
    let n = NaN;
    try { n = Number(localStorage.getItem(key)); } catch { /* no storage available */ }
    return Number.isFinite(n) && n >= min && n <= max ? n : fallback;
  }

  hide() {
    this.els.forEach((v) => this.discardPage(v));
    this.innerEl.replaceChildren();
    this.destroyBackgrounds();
    this.reset();
  }

  // Leaving: wait until the changes have reached the controller, then ask it to
  // close (saves right away) and switch to the view it names.
  async leave() {
    this.deactivateText();
    document.activeElement?.blur();
    // The changes on their way are waited for, but never for ever: if the computer
    // does not answer, the user decides whether to leave anyway.
    const drained = await this.queueDrained();
    if (!drained && !window.confirm('Il computer non risponde e le ultime modifiche non sono ancora arrivate.\n'
        + 'Uscire comunque? Quelle modifiche potrebbero andare perse.')) return;
    if (!drained) {
      this.abandoned = true;      // close() does not wait for the queue again
      this.app.navigate(this.path.split('/').slice(0, -1).join('/'));
      return;
    }
    if (!this.session) return;
    // The computer saves and answers with the view to show; if it does not answer
    // in time (or answers with an error), go back to the folder anyway.
    // Closing also tells where the reader stopped (see position in navigation.js).
    const closing = this.app.request('/api/edit/close', { session: this.session, ...this.currentPosition() })
      .then(() => true, () => false);
    const answered = await Promise.race([closing, new Promise((r) => setTimeout(() => r(false), 2 * LEAVE_WAIT_MS))]);
    if (!answered) {
      this.abandoned = true;
      this.app.navigate(this.path.split('/').slice(0, -1).join('/'));
    }
  }

  closeOnExit() {
    if (!this.session) return;
    clearTimeout(this.positionTimer);
    try {
      fetch('/api/edit/close', {
        method: 'POST', credentials: 'same-origin', keepalive: true,
        headers: { 'X-Requested-With': 'notes-app', 'Content-Type': 'application/json' },
        body: JSON.stringify({ session: this.session, ...this.currentPosition() }),
      }).catch(() => {});
    } catch { /* leaving anyway */ }
  }

  // True when the changes on their way have reached the computer, false if it does
  // not answer within LEAVE_WAIT_MS.
  queueDrained() {
    return Promise.race([this.queue.then(() => true),
      new Promise((r) => setTimeout(() => r(false), LEAVE_WAIT_MS))]);
  }

  // Leaving the editor for another view: never waits for ever.
  async close() {
    clearTimeout(this.positionTimer);
    if (!this.abandoned) await this.queueDrained();
    this.abandoned = false;
    if (!this.session) return;
    const closing = apiPost('/api/edit/close', { session: this.session, ...this.currentPosition() }).catch(() => {});
    await Promise.race([closing, new Promise((r) => setTimeout(r, LEAVE_WAIT_MS))]);
  }
}

// Methods of the individual areas, added to the class as they are.
for (const area of [SyncMethods, InputMethods, PagesMethods, SelectionMethods, ImagesMethods, ZoomMethods, ToolbarMethods, RenderMethods, TextsMethods, WidthMethods, NavigationMethods, ClipboardMethods, TouchMethods, MenuMethods]) {
  for (const name of Object.getOwnPropertyNames(area.prototype)) {
    if (name !== 'constructor') {
      Object.defineProperty(EditorView.prototype, name, Object.getOwnPropertyDescriptor(area.prototype, name));
    }
  }
}
