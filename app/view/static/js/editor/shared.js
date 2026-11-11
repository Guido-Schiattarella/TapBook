// VIEW — editor: constants and functions shared by the editor modules.
import * as pdfjsLib from '/static/vendor/pdfjs/pdf.min.mjs';

export const VENDOR = '/static/vendor/pdfjs/';
pdfjsLib.GlobalWorkerOptions.workerSrc = VENDOR + 'pdf.worker.min.mjs';
export const PDF_OPTIONS = {
  standardFontDataUrl: VENDOR + 'standard_fonts/',
  cMapUrl: VENDOR + 'cmaps/',
  cMapPacked: true,
  wasmUrl: VENDOR + 'wasm/',
  isEvalSupported: false,
};

export const COLORS = ['#1d1d1f', '#1e5bd8', '#d62d20', '#1f8a3b', '#ffd400', '#ff7ac6'];
// The highlighter has a colour of its own (yellow to start with); pen, shapes and
// text share one (the same colour for writing and typing is handy). Remembered on this iPad.
export const HIGHLIGHTER_COLOR = '#ffd400';
export const COLORS_PREF = 'notes.colors';
// Copy and paste: what the lasso selected (or the active text box) is kept on this
// device, so it can be pasted on another page or in another document.
export const CLIPBOARD_PREF = 'notes.clipboard';
export const CLIPBOARD_MAX_BYTES = 3 * 1024 * 1024;
export const PASTE_OFFSET = 15;        // pasted on the same page: shifted down and right
// Palm rejection: a finger touch much larger than a fingertip is the hand resting
// on the screen, and a finger touching while the Pencil writes is the palm too:
// neither scrolls or zooms the page. Once the Pencil is lifted, fingers are free at once.
// iOS gives only the larger radius of each touch, so a thumb lying sideways (long
// contact) is told from a palm by size alone: the limits leave room for it.
export const PALM_RADIUS = 48;         // CSS pixels: one touch (a fingertip is 10-15, a thumb up to about 45 sideways, a palm 60 and more)
export const PALM_RADIUS_PINCH = 95;   // two touches together are a pinch unless one is huge
// A touch starting this close to where the Pencil has just touched (pointer event),
// this soon, is the Pencil even if Safari does not say so.
export const PEN_MATCH_MS = 120;
export const PEN_MATCH_PX = 24;
// The Pencil counts as still on the screen at most this long without any news from it.
export const PEN_LOST_MS = 1500;
// Gestures with one finger (when the finger does not draw): a quick horizontal
// swipe turns the page; two taps zoom in on that point and back.
export const SWIPE_MIN_PX = 70;
export const SWIPE_MAX_MS = 400;
export const SWIPE_RATIO = 1.8;        // horizontal movement at least this many times the vertical one
export const DOUBLE_TAP_MS = 320;
export const TAP_MOVE_PX = 24;
export const TAP_ZOOM = 2;             // zoom reached by the double tap
// Where the reader is: sent to the computer a moment after scrolling stops, so
// the document opens at the same page next time (on any device).
export const POSITION_DELAY_MS = 800;
export const THUMB_WIDTH = 132;        // CSS pixels of the thumbnails in the page chooser
// One finger scrolls with the browser's own scrolling; two fingers zoom and move (the app).
export const PINCH_MIN_MOVE = 0.02;      // zoom change under which two fingers only moved the sheet
// Holding a finger still on the page for LONG_PRESS_MS opens the menu (copy, paste…).
export const LONG_PRESS_MS = 500;
export const LONG_PRESS_MOVE_PX = 10;
// Copying items writes this mark to the system clipboard: pasting with Ctrl+V
// then knows the items are meant, not whatever text was copied before.
export const CLIP_MARK = 'tapbook-clipboard:';
export const HIGHLIGHT_ALPHA = 0.35;
export const HIGHLIGHTER_FACTOR = 6;  // the highlighter is 6 times wider than the pen
export const MIN_POINT_DIST = 0.4;    // PDF points between two consecutive samples
// Stroke stabilisation: every point moves towards the previous one by this fraction,
// so hand tremor disappears. Kept light so the stroke does not trail behind the
// tip; while writing, the preview also joins the last point to where the Pencil
// really is (see drawLive), and the last real point is added at the end.
export const STABILIZER = 0.25;
// The stabilisation is for hand tremor, i.e. small movements between two samples:
// full up to STAB_FULL_PX on screen, none beyond STAB_NONE_PX. Pens that send few
// samples (or a fast stroke) make big jumps: smoothing them would cut the curves,
// shrink the figure and leave shapes open.
export const STAB_FULL_PX = 1.5;
export const STAB_NONE_PX = 6;
// The preview runs a little ahead of the Pencil, where its speed takes it in
// PREDICT_MS (never more than PREDICT_MAX_PX on screen), to hide part of the
// display delay. Only the preview: the saved stroke has the real points.
export const PREDICT_MS = 12;
export const PREDICT_MAX_PX = 6;
export const TAIL_BOX = 160;          // side (CSS pixels) of the small canvas with the end of the stroke
// Stroke thickness (PDF points), chosen with a slider: its position (0-100) maps
// to the thickness on a logarithmic scale, so the thin end has fine steps.
export const WIDTH_MIN = 0.2;
export const WIDTH_MAX = 16;
export const WIDTH_DEFAULT = 2;
export const WIDTH_PREF = 'notes.penWidth';            // single thickness of earlier versions
export const WIDTHS_PREF = 'notes.widths';             // choices of each tool (see widths.js)
// Standard sizes, the same for every tool (the highlighter is HIGHLIGHTER_FACTOR times wider).
export const WIDTH_PRESETS = { small: 1, medium: 2, large: 4 };
export const WIDTH_TOOLS = ['pen', 'highlighter', 'shape'];   // tools with their own custom thickness
export const widthFromSlider = (v) => Math.round(WIDTH_MIN * (WIDTH_MAX / WIDTH_MIN) ** (v / 100) * 100) / 100;
export const sliderFromWidth = (w) => Math.round(100 * Math.log(w / WIDTH_MIN) / Math.log(WIDTH_MAX / WIDTH_MIN));
// Font size of text boxes (PDF points).
export const TEXT_SIZE_MIN = 6;
export const TEXT_SIZE_MAX = 72;
export const TEXT_SIZE_DEFAULT = 16;
export const TEXT_SIZE_PREF = 'notes.textSize';
export const TEXT_W_MIN = 20;          // narrowest text box (same limit as the controller)
// Keyboard shortcuts for the tools (outside text boxes).
export const TOOL_KEYS = { p: 'pen', h: 'highlighter', e: 'eraser', l: 'lasso', f: 'shape', t: 'text' };
// Geometric shapes: with the pen, holding the Pencil still (within HOLD_MOVE_PX pixels)
// for HOLD_MS at the end of a stroke turns the stroke into the matching shape.
export const HOLD_MS = 600;
export const HOLD_MOVE_PX = 4;
export const SNAP_PX = 14;            // distance (on screen) within which shape corners join
export const SHAPE_MAX_POINTS = 4000; // points sent for recognition
export const GESTURE_POINT_DIST = 1.5; // samples of the eraser and lasso paths
export const GESTURE_MAX_POINTS = 5000; // beyond this, the eraser path is sent in pieces
export const SELECTION_PAD = 6;       // margin of the selection box (PDF points)
export const TYPING_DELAY = 400;      // ms: typed text is sent in small chunks
export const RETRY_DELAY = 2000;      // ms: send again if the Wi-Fi network does not answer
export const SLOW_REQUEST_MS = 10000; // ms: beyond this a request is shown as "not answering"
// ms: beyond this an operation is sent again on a new connection (the computer
// recognises a repeated operation by its number and does not apply it twice)
export const OP_TIMEOUT_MS = 20000;
export const LISTEN_TIMEOUT_MS = 45000; // the computer keeps /listen open for up to 25 s
export const LEAVE_WAIT_MS = 8000;    // ms: leaving waits this long for the changes on their way
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 10;
// Maximum pixels of a canvas. Safari on the iPad stops drawing canvases larger
// than about 16 million pixels: beyond this threshold (strong zoom) only the
// visible part of the page is drawn, plus a margin, and redrawn while scrolling.
// This keeps strokes and layout visible and sharp at any zoom.
export const MAX_CANVAS_PIXELS = 8 * 1024 * 1024;
// Margin around the visible part, as a fraction of the screen: a share of the
// width at the sides, and all the pixels left under MAX_CANVAS_PIXELS above and
// below (up to REGION_MAX_AHEAD screens), mostly in the direction of the scrolling.
export const REGION_SIDE = 0.15;
export const REGION_MAX_AHEAD = 1.0;
export const REGION_AHEAD_SHARE = 0.7;     // share of the vertical margin put ahead of the movement
// The region is drawn again when the visible part comes this close (fraction of
// the margin) to its edge, before it leaves it.
export const REGION_GUARD = 0.4;
// Under the sharp regions, the whole page is kept at a low resolution (at most this
// many pixels): while scrolling with strong zoom there is never a white hole, just
// a slightly blurred background until the sharp one arrives.
export const COARSE_PIXELS = 1.5 * 1024 * 1024;
// Pixels of all the pages' canvases together (4 bytes each: 40 M ≈ 160 MB), well
// below the limit Safari on the iPad sets for a page's canvases.
export const CANVAS_BUDGET = 40 * 1024 * 1024;

export const uid = () => (crypto.randomUUID
  ? crypto.randomUUID().replaceAll('-', '')
  : Math.random().toString(36).slice(2) + Date.now().toString(36)).slice(0, 16);

export function distToSegment(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

export const ERASER_DEFAULT = 7;        // eraser radius (PDF points): Fine 3, Medium 7, Large 14
export const ERASER_PREF = 'notes.eraserRadius';

// Smooth curve of the stroke as the editor draws it, in dense points (like
// smooth_polyline in the model): used by the eraser preview. Computed once per stroke.
export const smoothCache = new WeakMap();
export function smoothPoints(stroke) {
  if (stroke.shape) return stroke.points;
  let out = smoothCache.get(stroke);
  if (out) return out;
  const p = stroke.points;
  if (p.length < 3) {
    out = p;
  } else {
    out = [p[0]];
    let start = p[0];
    for (let i = 1; i < p.length - 1; i++) {
      const c = p[i], end = [(c[0] + p[i + 1][0]) / 2, (c[1] + p[i + 1][1]) / 2];
      const len = Math.abs(c[0] - start[0]) + Math.abs(c[1] - start[1]) + Math.abs(end[0] - c[0]) + Math.abs(end[1] - c[1]);
      const steps = Math.max(1, Math.min(8, Math.floor(len / 1.5)));
      for (let k = 1; k <= steps; k++) {
        const t = k / steps, a = (1 - t) ** 2, b = 2 * (1 - t) * t, cc = t * t;
        out.push([a * start[0] + b * c[0] + cc * end[0], a * start[1] + b * c[1] + cc * end[1]]);
      }
      start = end;
    }
    out.push(p[p.length - 1]);
  }
  smoothCache.set(stroke, out);
  return out;
}

// Geometric shapes are drawn with straight segments between their points (sharp corners).
// Preview only: the controller picks the strokes really touched.
export function touches(stroke, pt, radius) {
  const limit = radius + stroke.width / 2;
  const pts = smoothPoints(stroke);
  if (pts.length === 1) return Math.hypot(pt[0] - pts[0][0], pt[1] - pts[0][1]) < limit;
  for (let j = 1; j < pts.length; j++) if (distToSegment(pt, pts[j - 1], pts[j]) < limit) return true;
  return false;
}

export const isStylus = (touchList) => [...touchList].some((t) => t.touchType === 'stylus');
