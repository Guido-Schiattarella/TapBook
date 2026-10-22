// VIEW — editor, communication with the controller on the computer: operation queue, responses, notifications (listen) and model events.
// EditorView methods (see editor_view.js): here `this` is the editor.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { ApiError, apiGet, apiPost } from '../api.js';
import { PDF_OPTIONS, RETRY_DELAY } from './shared.js';
import { tabId, renewTabId } from '../device.js';

export class SyncMethods {
  // =====================================================================
  // Communication with the controller on the computer
  // =====================================================================
  // Queues a request: requests leave in order, one at a time. If the network
  // does not answer, retry; if the computer closed the document for inactivity,
  // reopen it (from the current version) and send the request again.
  // quiet: request that does not change the document (e.g. lasso selection).
  enqueue(request, { quiet = false } = {}) {
    if (this.blocked) return Promise.resolve();
    this.inFlight++;
    if (!quiet) this.setStatus('Modifiche…');
    let session = this.session;
    let reopened = false;
    this.queue = this.queue.then(async () => {
      while (session === this.session && !this.blocked) {
        try {
          const result = await request(session);
          if (session === this.session) this.applyResult(result);
          return;
        } catch (e) {
          if (e instanceof ApiError && e.status === 410 && !reopened) {
            reopened = true;
            // Replaced by another tab with the same identifier (a duplicated tab):
            // this tab takes a new one, so the two do not keep replacing each other.
            if (e.data.reason === 'replaced') renewTabId();
            await this.reopen();
            session = this.session;
            continue;
          }
          if (e instanceof ApiError && e.status) { this.handleError(e); return; }
          this.setStatus('Rete assente, riprovo…', true);
          await new Promise((r) => setTimeout(r, RETRY_DELAY));
        }
      }
    }).catch((err) => console.error(err))  // an unexpected error must not stop the queue
      .finally(() => {
        this.inFlight--;
        this.showStatus(this.lastStatus);
      });
    return this.queue;
  }

  send(op, options) {
    return this.enqueue((session) => apiPost('/api/edit/op', { session, op }), options);
  }

  handleError(e) {
    // Operation rejected by the controller: go back to the computer's version.
    this.showBanner(e.message + ' — ricarica il documento.');
  }

  // Applies a controller response (to an operation or to /listen).
  applyResult(result) {
    for (const ev of result.events || []) this.applyEvent(ev);
    if (this.selection) this.showSelection();  // the selected items may have changed
    this.setUndoState(result.canUndo, result.canRedo);
    this.showDevices(result.devices);
    this.lastStatus = result.status;
    this.showStatus(result.status);
  }

  // Request always kept open towards the computer: it brings the changes made by
  // other devices or on the computer, and the save status.
  async listen(session) {
    while (session === this.session) {
      try {
        const result = await apiGet('/api/edit/listen', { session });
        if (session === this.session) this.applyResult(result);
      } catch (e) {
        if (session !== this.session) return;
        if (e instanceof ApiError && e.status === 410) {
          // Closed for inactivity: it reopens by itself at the next change.
          this.setStatus('In pausa — scrivi per riprendere');
          return;
        }
        await new Promise((r) => setTimeout(r, RETRY_DELAY));
      }
    }
  }

  // Reopens the document: the view receives the current version from the
  // controller (with the changes made meanwhile by other devices or on the computer).
  async reopen() {
    const data = await apiPost('/api/open', { path: this.path, device: tabId() });
    if (data.view !== 'editor') throw new Error('Documento non più disponibile');
    const { queue, inFlight, pendingStrokes } = this;
    await this.show(data);
    Object.assign(this, { queue, inFlight, pendingStrokes });  // changes on their way keep going
    this.pages.forEach((p) => this.drawInk(p));
    this.notice('Documento riaperto dalla versione attuale');
  }

  page(id) {
    return this.pages.find((p) => p.id === id);
  }

  applyEvent(ev) {
    const page = ev.page && this.page(ev.page);
    if (ev.page && !page) return;
    switch (ev.event) {
      case 'strokeAdded': {
        // Confirmation of a stroke of this iPad, added at the end: it is already on
        // screen exactly like that (as "pending"), so the page is not redrawn
        // (with many strokes, redrawing could make the next stroke stutter).
        const own = this.pendingStrokes.has(ev.stroke.id) && ev.index === page.strokes.length;
        if (!page.strokes.some((s) => s.id === ev.stroke.id)) page.strokes.splice(ev.index, 0, ev.stroke);
        this.pendingStrokes.delete(ev.stroke.id);
        if (!own) this.drawInk(page);
        break;
      }
      case 'strokeChanged': {
        const i = page.strokes.findIndex((s) => s.id === ev.stroke.id);
        if (i >= 0) { page.strokes[i] = ev.stroke; this.drawInk(page); }
        break;
      }
      case 'strokeRemoved':
        page.strokes = page.strokes.filter((s) => s.id !== ev.id);
        this.hiddenStrokes.delete(ev.id);
        this.drawInk(page);
        break;
      case 'textAdded':
        page.texts.splice(ev.index, 0, ev.text);
        this.renderTexts(page);
        if (this.focusNewText) { this.focusNewText = false; this.focusText(ev.text.id); }
        break;
      case 'textRemoved':
        page.texts = page.texts.filter((t) => t.id !== ev.id);
        if (this.activeText?.id === ev.id) { this.activeText = null; this.showTextSize(this.textSize); }
        this.renderTexts(page);
        break;
      case 'textChanged': {
        const t = page.texts.find((x) => x.id === ev.text.id);
        if (!t) break;
        // While the box is being written, the local copy is newer than the confirmation.
        if (this.isEditing(t.id)) Object.assign(t, { x: ev.text.x, y: ev.text.y });
        else Object.assign(t, ev.text);
        this.updateTextbox(page, t);
        break;
      }
      case 'imageAdded':
        page.images.splice(ev.index, 0, ev.image);
        this.renderImages(page);
        break;
      case 'imageRemoved':
        page.images = page.images.filter((i) => i.id !== ev.id);
        this.renderImages(page);
        break;
      case 'imageChanged': {
        const img = page.images.find((i) => i.id === ev.image.id);
        if (img) { Object.assign(img, ev.image); this.renderImages(page); }
        break;
      }
      case 'pagesChanged':
        // Page added or removed by this device: go there; otherwise stay where you were.
        this.syncPages(ev.pages, this.navFocus);
        this.navFocus = null;
        break;
      case 'backgroundChanged':
        // The PDF was changed on the computer and the controller merged the changes:
        // download the background again and redraw everything.
        this.pages = ev.pages;
        this.reloadBackground();
        break;
      case 'selection':
        // Lasso response: the controller says what was enclosed.
        if (this.tool !== 'lasso') break;
        this.selection = { page: ev.page, strokes: new Set(ev.strokes), texts: new Set(ev.texts),
          images: new Set(ev.images), dx: 0, dy: 0 };
        this.showSelection();
        break;
      case 'layoutChanged':
        this.layout = ev.layout;
        this.showLayout();
        break;
      case 'notice':
        this.showBanner(ev.message, { info: true });
        break;
      case 'devices':
        this.showDevices(ev.count);
        break;
      default:
        break;
    }
  }

  async reloadBackground() {
    const session = this.session;
    const resp = await fetch('/api/edit/background?session=' + encodeURIComponent(session), { credentials: 'same-origin' });
    if (!resp.ok || session !== this.session) return;
    const pdf = await pdfjsLib.getDocument({ data: new Uint8Array(await resp.arrayBuffer()), ...PDF_OPTIONS }).promise;
    if (session !== this.session) { pdf.destroy(); return; }
    const old = this.pdf;
    this.pdf = pdf;
    this.buildPages();
    old?.destroy();
    this.notice('Unite le modifiche fatte sul PC');
  }
}
