// VIEW — editor, the "painter": draws the PDF backgrounds, preferably in a worker
// (render_worker.js) so that scrolling and writing never wait for a drawing; on a
// browser without workers with canvases, on the main thread as before.
// Same interface either way:
//   open(key, bytes) → Promise      close(key)
//   render(key, pageIndex, {scale, x, y, w, h, r}) → { promise: Promise<image>, cancel() }
//     image: an ImageBitmap (worker) or a canvas (main thread), round(w*r) × round(h*r)
//     pixels, the part of the page from (x, y) CSS pixels at `scale`, resolution r.
//   ink({x, y, w, h, r, scale, alpha, strokes, points}) → { promise: Promise<ImageBitmap>, cancel() } or
//     null when the strokes cannot be drawn away from the page (then render.js draws them itself).
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';
import { PDF_OPTIONS } from './shared.js';

const WORKER_URL = '/static/js/editor/render_worker.js';
const INK_WORKER_URL = '/static/js/editor/ink_worker.js';
const READY_TIMEOUT_MS = 4000;

class Cancelled extends Error {
  constructor() { super('Disegno annullato'); this.cancelled = true; }
}

// --- in a worker ---------------------------------------------------------------------------
class WorkerPainter {
  constructor(worker) {
    this.worker = worker;
    this.offThread = true;
    this.opens = new Map();      // key -> {resolve, reject}
    this.jobs = new Map();       // token -> {resolve, reject}
    this.token = 0;
    worker.addEventListener('message', (e) => this.onMessage(e.data));
    worker.addEventListener('error', (e) => this.fail(e.message || 'worker error'));
  }

  onMessage(m) {
    if (m.type === 'opened' || m.type === 'openFailed') {
      const p = this.opens.get(m.key);
      this.opens.delete(m.key);
      if (m.type === 'opened') p?.resolve(m.pages); else p?.reject(new Error(m.message));
    } else if (m.type === 'rendered' || m.type === 'renderFailed') {
      const j = this.jobs.get(m.token);
      this.jobs.delete(m.token);
      if (!j) { m.bitmap?.close?.(); return; }
      if (m.type === 'rendered') j.resolve(m.bitmap);
      else j.reject(m.cancelled ? new Cancelled() : new Error(m.message));
    }
  }

  // The worker died: everything waiting fails (the pages are drawn again later).
  fail(message) {
    for (const p of this.opens.values()) p.reject(new Error(message));
    for (const j of this.jobs.values()) j.reject(new Error(message));
    this.opens.clear();
    this.jobs.clear();
  }

  open(key, bytes) {
    return new Promise((resolve, reject) => {
      this.opens.set(key, { resolve, reject });
      // The bytes move to the worker (no copy): the caller must not use them afterwards.
      const buffer = bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes.buffer : bytes.slice().buffer;
      this.worker.postMessage({ type: 'open', key, buffer }, [buffer]);
    });
  }

  close(key) {
    this.worker.postMessage({ type: 'close', key });
  }

  render(key, page, region) {
    const token = ++this.token;
    const promise = new Promise((resolve, reject) => {
      this.jobs.set(token, { resolve, reject });
      this.worker.postMessage({ type: 'render', token, key, page, ...region });
    });
    return { promise, cancel: () => { if (this.jobs.has(token)) this.worker.postMessage({ type: 'cancel', token }); } };
  }

  destroy() {
    this.worker.terminate();
    this.fail('painter closed');
  }
}

// --- on the main thread ------------------------------------------------------------------------
class LocalPainter {
  constructor() {
    this.offThread = false;
    this.docs = new Map();
  }

  open(key, bytes) {
    const opening = pdfjsLib.getDocument({ data: bytes, ...PDF_OPTIONS }).promise;
    this.docs.set(key, opening);
    return opening.then((d) => d.numPages, (e) => { this.docs.delete(key); throw e; });
  }

  close(key) {
    const doc = this.docs.get(key);
    this.docs.delete(key);
    doc?.then((d) => d.destroy()).catch(() => {});
  }

  render(key, page, { scale, x, y, w, h, r }) {
    let task = null, cancelled = false;
    const promise = (async () => {
      const doc = await this.docs.get(key);
      if (!doc) throw new Error('Documento non aperto');
      const pdfPage = await doc.getPage(page + 1);
      if (cancelled) throw new Cancelled();
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(w * r));
      canvas.height = Math.max(1, Math.round(h * r));
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      task = pdfPage.render({ canvasContext: ctx, viewport: pdfPage.getViewport({ scale: scale * r }),
        annotationMode: pdfjsLib.AnnotationMode.ENABLE, transform: [1, 0, 0, 1, -x * r, -y * r] });
      try {
        await task.promise;
      } catch (e) {
        if (e?.name === 'RenderingCancelledException') throw new Cancelled();
        throw e;
      }
      return canvas;
    })();
    return { promise, cancel: () => { cancelled = true; task?.cancel(); } };
  }

  destroy() {
    for (const key of [...this.docs.keys()]) this.close(key);
  }
}

// --- strokes in a worker of their own ---------------------------------------------------------
// Separate from the backgrounds' worker: a long background drawing never delays the strokes.
class InkWorker {
  constructor(worker) {
    this.worker = worker;
    this.jobs = new Map();       // token -> {resolve, reject}
    this.token = 0;
    worker.addEventListener('message', (e) => {
      const m = e.data;
      if (m.type !== 'inked' && m.type !== 'inkFailed') return;
      const j = this.jobs.get(m.token);
      this.jobs.delete(m.token);
      if (!j) { m.bitmap?.close?.(); return; }
      if (m.type === 'inked') j.resolve(m.bitmap); else j.reject(new Error(m.message));
    });
    worker.addEventListener('error', (e) => {
      for (const j of this.jobs.values()) j.reject(new Error(e.message || 'worker error'));
      this.jobs.clear();
    });
  }

  ink(job) {
    const token = ++this.token;
    const promise = new Promise((resolve, reject) => {
      this.jobs.set(token, { resolve, reject });
      this.worker.postMessage({ type: 'ink', token, ...job }, [job.points.buffer]);   // the points move, no copy
    });
    // Drawing strokes is quick: a result no longer wanted is simply dropped.
    return { promise, cancel: () => { const j = this.jobs.get(token); this.jobs.delete(token); j?.reject(new Cancelled()); } };
  }

  destroy() {
    this.worker.terminate();
    for (const j of this.jobs.values()) j.reject(new Error('painter closed'));
    this.jobs.clear();
  }
}

async function startWorker(url) {
  let worker;
  try { worker = new Worker(url, { type: 'module' }); } catch { return null; }
  const ok = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), READY_TIMEOUT_MS);
    worker.addEventListener('message', (e) => { if (e.data?.type === 'ready') { clearTimeout(timer); resolve(!!e.data.ok); } }, { once: true });
    worker.addEventListener('error', () => { clearTimeout(timer); resolve(false); }, { once: true });
  });
  if (!ok) { worker.terminate(); return null; }
  return worker;
}

// --- choice ----------------------------------------------------------------------------------------
// The worker is tried first; if it cannot draw (or does not answer), the main thread
// is used. Calls made before the choice wait for it.
export class Painter {
  constructor() {
    this.offThread = false;
    this.inkWorker = null;       // strokes drawn away from the page, once its worker is ready
    this.backend = this.choose();
    this.backend.then((b) => { this.offThread = b.offThread; });
    this.inkReady = typeof Worker === 'undefined' || typeof OffscreenCanvas === 'undefined' ? Promise.resolve(null)
      : startWorker(INK_WORKER_URL).then((w) => (this.inkWorker = w && new InkWorker(w)));
  }

  async choose() {
    if (typeof Worker === 'undefined' || typeof OffscreenCanvas === 'undefined') return new LocalPainter();
    const worker = await startWorker(WORKER_URL);
    return worker ? new WorkerPainter(worker) : new LocalPainter();
  }

  // Strokes drawn in their worker; null when it is not available (yet).
  ink(job) {
    return this.inkWorker ? this.inkWorker.ink(job) : null;
  }

  async open(key, bytes) {
    return (await this.backend).open(key, bytes);
  }

  close(key) {
    this.backend.then((b) => b.close(key));
  }

  render(key, page, region) {
    let inner = null, cancelled = false;
    const promise = this.backend.then((b) => {
      if (cancelled) throw new Cancelled();
      inner = b.render(key, page, region);
      return inner.promise;
    });
    return { promise, cancel: () => { cancelled = true; inner?.cancel(); } };
  }
}
