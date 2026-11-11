// VIEW — editor, communication with the controller on the computer: operation queue, responses, notifications (listen) and model events.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { ApiError, NetworkError, apiGet, apiPost, reportError } from '../api.js';
import { LISTEN_TIMEOUT_MS, OP_TIMEOUT_MS, PDF_OPTIONS, RETRY_DELAY, SLOW_REQUEST_MS } from './shared.js';
import { tabId, renewTabId } from '../device.js';

export class SyncMethods {
  // =====================================================================
  // Communication with the controller on the computer
  // =====================================================================
  // Queues a request: requests leave in order, one at a time. If the network
  // does not answer, retry; if the computer closed the document for inactivity,
  // reopen it (from the current version) and send the request again.
  // Every request is sent with the session current when it leaves: after a reopening
  // the requests already queued (for example the second stroke of an "=", drawn
  // while the first one was reopening the document) go with the new session. Only
  // when another document is opened (or the editor is closed) are they dropped.
  // quiet: request that does not change the document (e.g. lasso selection).
  enqueue(request, { quiet = false } = {}) {
    if (this.blocked) return Promise.resolve();
    this.inFlight++;
    if (!quiet) this.setStatus('Modifiche…');
    const openId = this.openId;
    let reopened = false;
    this.queue = this.queue.then(async () => {
      while (openId === this.openId && this.session && !this.blocked) {
        const session = this.session;
        // A request that takes too long is shown, instead of a "Modifiche…" that never ends.
        const slow = setTimeout(() => this.setStatus('Il computer non risponde, attendo…', true), SLOW_REQUEST_MS);
        try {
          const result = await request(session);
          if (openId === this.openId && session === this.session) this.applyResult(result);
          return;
        } catch (e) {
          if (e instanceof ApiError && e.status === 410 && !reopened) {
            reopened = true;
            // Replaced by another tab with the same identifier (a duplicated tab):
            // this tab takes a new one, so the two do not keep replacing each other.
            if (e.data.reason === 'replaced') renewTabId();
            try {
              await this.reopen();
            } catch (err) {
              if (!(err instanceof NetworkError)) throw err;
              reopened = false;          // no network: try the reopening again shortly
              this.setStatus('Rete assente, riprovo…', true);
              await new Promise((r) => setTimeout(r, RETRY_DELAY));
            }
            continue;
          }
          if (e instanceof ApiError && e.status) { this.handleError(e); return; }
          if (!(e instanceof NetworkError)) {
            // Not a network problem (an error in the page): retrying would loop for
            // ever and block the queue, and leaving the editor with it.
            console.error(e);
            reportError(e?.message || e, 'editor queue', e?.stack);
            this.showBanner('Si è verificato un errore: ricarica il documento.');
            return;
          }
          this.setStatus('Rete assente, riprovo…', true);
          await new Promise((r) => setTimeout(r, RETRY_DELAY));
        } finally {
          clearTimeout(slow);
        }
      }
    }).catch((err) => console.error(err))  // an unexpected error must not stop the queue
      .finally(() => {
        this.inFlight--;
        this.showStatus(this.lastStatus);
      });
    return this.queue;
  }

  // Every operation gets a number, once: if the answer is lost and the operation
  // is sent again, the computer recognises it and does not apply it twice.
  send(op, options) {
    op.seq = this.opSeq = (this.opSeq || 0) + 1;
    return this.enqueue((session) => apiPost('/api/edit/op', { session, op }, { timeout: OP_TIMEOUT_MS }), options);
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
        const result = await apiGet('/api/edit/listen', { session }, { timeout: LISTEN_TIMEOUT_MS });
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

  // Reopens the document (closed by the computer after a long pause): the view
  // receives the current version from the controller, with the changes made
  // meanwhile by other devices or on the computer. The pages on screen stay where
  // they are and only what changed is drawn again: a stroke being written, the
  // strokes on their way and the position are kept (rebuilding everything lost the
  // stroke being written at that moment).
  async reopen() {
    const data = await apiPost('/api/open', { path: this.path, device: tabId() });
    if (data.view !== 'editor') throw new Error('Documento non più disponibile');
    this.session = data.session;
    await this.loadBackgrounds(data.backgrounds || {});      // only those this device lacks
    this.layout = data.layout;
    this.layouts = data.layouts || [];
    this.showLayout();
    this.syncPages(data.pages, null);
    const g = this.gesture;
    if (g?.page) g.page = this.page(g.page.id) || g.page;   // the stroke being written goes on
    this.setUndoState(data.canUndo, data.canRedo);
    this.showDevices(data.devices);
    this.lastStatus = data.status;
    this.listen(this.session);
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
        if (this.fitNewText && ev.text.text) {
          // Pasted text: the box takes the height the text needs on this screen.
          this.fitNewText = false;
          const el = this.textboxOf(page.id, ev.text.id);
          if (el) {
            const h = this.measureText(ev.text, el.querySelector('textarea'));
            if (Math.abs(h - ev.text.h) > 0.5) { ev.text.h = h; this.placeTextbox(el, ev.text); this.send({ type: 'changeText', page: page.id, id: ev.text.id, h }); }
          }
        }
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
        this.reloadBackground(ev.backgrounds || {});
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

  // The file was changed on the computer and merged: only the backgrounds of the
  // pages that changed are new (downloaded if this device does not have them).
  async reloadBackground(sizes) {
    const session = this.session;
    try {
      await this.loadBackgrounds(sizes);
    } catch (e) {
      if (session === this.session) this.showBanner(`Le pagine aggiornate non si sono scaricate (${e.message}).`);
      return;
    }
    if (session !== this.session) return;
    // The old backgrounds stay open (an "undo" may bring back a page that uses them):
    // they are closed when the editor is left.
    this.buildPages();
    this.notice('Unite le modifiche fatte sul PC');
  }
}
