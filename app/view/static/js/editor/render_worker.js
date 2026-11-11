// VIEW — editor, drawing of the PDF backgrounds in a worker (a thread of its own).
// The page scrolls on the main thread; drawing a page there would stop the
// scrolling for as long as the drawing takes. Here the backgrounds are drawn
// on OffscreenCanvas and sent back as images (ImageBitmap), ready to show.
// Protocol (postMessage):
//   in   open {key, buffer}   close {key}   render {token, key, page, scale, x, y, w, h, r}   cancel {token}
//   out  ready {ok}   opened {key, pages} | openFailed {key, message}
//        rendered {token, bitmap} | renderFailed {token, message, cancelled}
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';

const VENDOR = '/static/vendor/pdfjs/';
// pdf.js reads document.baseURI when it fetches its fonts and character maps:
// a worker has no document, so it gets this one (nothing else of it is used:
// canvases and filters come from our factories, fonts are drawn as paths).
globalThis.document ??= { baseURI: self.location.href };
// pdf.js parses the PDF in a worker of its own; a worker inside a worker is not
// available everywhere: then pdf.js parses here (still away from the page).
try {
  pdfjsLib.GlobalWorkerOptions.workerPort = new Worker(VENDOR + 'pdf.worker.min.mjs', { type: 'module' });
} catch {
  pdfjsLib.GlobalWorkerOptions.workerSrc = VENDOR + 'pdf.worker.min.mjs';
}

// Canvases without a document: OffscreenCanvas.
class OffscreenCanvasFactory {
  create(width, height) {
    if (width <= 0 || height <= 0) throw new Error('Invalid canvas size');
    const canvas = new OffscreenCanvas(width, height);
    return { canvas, context: canvas.getContext('2d') };
  }
  reset(pair, width, height) {
    if (width <= 0 || height <= 0) throw new Error('Invalid canvas size');
    pair.canvas.width = width;
    pair.canvas.height = height;
  }
  destroy(pair) {
    pair.canvas.width = pair.canvas.height = 0;
    pair.canvas = null;
    pair.context = null;
  }
}
// Filters (SVG) need a document: none here (they only matter for high-contrast modes).
class NoFilterFactory {
  addFilter() { return 'none'; }
  addHCMFilter() { return 'none'; }
  addAlphaFilter() { return 'none'; }
  addLuminosityFilter() { return 'none'; }
  addHighlightHCMFilter() { return 'none'; }
  destroy() {}
}

const OPTIONS = {
  standardFontDataUrl: VENDOR + 'standard_fonts/',
  cMapUrl: VENDOR + 'cmaps/',
  cMapPacked: true,
  wasmUrl: VENDOR + 'wasm/',
  isEvalSupported: false,
  CanvasFactory: OffscreenCanvasFactory,
  FilterFactory: NoFilterFactory,
  disableFontFace: true,       // glyphs drawn as paths: no document to load fonts into
  useSystemFonts: false,
};

const docs = new Map();        // key -> Promise<PDFDocumentProxy>
const tasks = new Map();       // token -> render task (to cancel)

async function open(key, buffer) {
  const opening = pdfjsLib.getDocument({ data: new Uint8Array(buffer), ...OPTIONS }).promise;
  docs.set(key, opening);
  try {
    const doc = await opening;
    self.postMessage({ type: 'opened', key, pages: doc.numPages });
  } catch (e) {
    docs.delete(key);
    self.postMessage({ type: 'openFailed', key, message: e?.message || String(e) });
  }
}

function close(key) {
  const doc = docs.get(key);
  docs.delete(key);
  doc?.then((d) => d.destroy()).catch(() => {});
}

async function render({ token, key, page, scale, x, y, w, h, r }) {
  try {
    const doc = await docs.get(key);
    if (!doc) throw new Error('Documento non aperto');
    const pdfPage = await doc.getPage(page + 1);
    const canvas = new OffscreenCanvas(Math.max(1, Math.round(w * r)), Math.max(1, Math.round(h * r)));
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const task = pdfPage.render({ canvasContext: ctx, viewport: pdfPage.getViewport({ scale: scale * r }),
      annotationMode: pdfjsLib.AnnotationMode.ENABLE, transform: [1, 0, 0, 1, -x * r, -y * r] });
    tasks.set(token, task);
    await task.promise;
    tasks.delete(token);
    const bitmap = canvas.transferToImageBitmap();
    self.postMessage({ type: 'rendered', token, bitmap }, [bitmap]);
  } catch (e) {
    tasks.delete(token);
    self.postMessage({ type: 'renderFailed', token, message: e?.message || String(e),
      cancelled: e?.name === 'RenderingCancelledException' });
  }
}

self.addEventListener('message', (e) => {
  const m = e.data;
  if (m.type === 'open') open(m.key, m.buffer);
  else if (m.type === 'close') close(m.key);
  else if (m.type === 'render') render(m);
  else if (m.type === 'cancel') tasks.get(m.token)?.cancel();
});

// Tells the page whether drawing here is possible at all.
let ok = false;
try { ok = !!new OffscreenCanvas(1, 1).getContext('2d'); } catch { ok = false; }
self.postMessage({ type: 'ready', ok });
