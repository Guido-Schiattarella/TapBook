// VIEW — editor, drawing of the strokes in a worker (a thread of its own).
// While the sheet scrolls with strong zoom, the strokes of the part of the page
// that comes into view are drawn here, not on the main thread: drawing hundreds
// of strokes on a large canvas takes the browser long enough to make the sheet
// stop. The strokes arrive packed (points in one Float32Array) and go back as an
// image (ImageBitmap), ready to show. The strokes are drawn exactly as on the
// page (render.js, drawStroke): smooth curves through the midpoints, straight
// segments for shapes, the highlighter transparent and multiplied.
// Protocol (postMessage):
//   in   ink {token, x, y, w, h, r, scale, alpha, strokes: [{n, color, width, hl, shape}], points}
//   out  ready {ok}   inked {token, bitmap} | inkFailed {token, message}

function draw(ctx, s, pts, o, alpha) {
  const n = s.n;
  const X = (i) => pts[o + 2 * i], Y = (i) => pts[o + 2 * i + 1];
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = s.color;
  ctx.lineWidth = s.width;
  ctx.globalAlpha = s.hl ? alpha : 1;
  ctx.globalCompositeOperation = s.hl ? 'multiply' : 'source-over';
  ctx.beginPath();
  ctx.moveTo(X(0), Y(0));
  if (s.shape) {
    for (let i = 1; i < n; i++) ctx.lineTo(X(i), Y(i));
    ctx.stroke();
    return;
  }
  if (n === 1) ctx.lineTo(X(0) + 0.01, Y(0) + 0.01);
  for (let i = 1; i < n - 1; i++) ctx.quadraticCurveTo(X(i), Y(i), (X(i) + X(i + 1)) / 2, (Y(i) + Y(i + 1)) / 2);
  if (n > 1) ctx.lineTo(X(n - 1), Y(n - 1));
  ctx.stroke();
}

function ink({ token, x, y, w, h, r, scale, alpha, strokes, points }) {
  try {
    const canvas = new OffscreenCanvas(Math.max(1, Math.round(w * r)), Math.max(1, Math.round(h * r)));
    const ctx = canvas.getContext('2d');
    const k = scale * r;
    ctx.setTransform(k, 0, 0, k, -x * r, -y * r);
    let o = 0;
    for (const s of strokes) {
      draw(ctx, s, points, o, alpha);
      o += 2 * s.n;
    }
    const bitmap = canvas.transferToImageBitmap();
    self.postMessage({ type: 'inked', token, bitmap }, [bitmap]);
  } catch (e) {
    self.postMessage({ type: 'inkFailed', token, message: e?.message || String(e) });
  }
}

self.addEventListener('message', (e) => {
  if (e.data?.type === 'ink') ink(e.data);
});

let ok = false;
try { ok = !!new OffscreenCanvas(1, 1).getContext('2d'); } catch { ok = false; }
self.postMessage({ type: 'ready', ok });
