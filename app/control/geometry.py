"""CONTROL — eraser and lasso geometry.

The view only sends the gesture made with the Pencil (the eraser path, the
lasso outline); here the controller decides, on the model's data, which page
items the gesture touched or enclosed.
"""
import math

from PIL import Image, ImageDraw

from ..model.pdf_store import smooth_polyline

LASSO_SAMPLES = 64          # points of a stroke checked for the lasso
LASSO_MASK_MAX = 2000       # maximum side (pixels) of the lasso mask
MAX_DENSE_POINTS = 50000    # maximum number of intermediate points for an eraser path (computation limit)


def _dist_to_segment(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    t = ((px - ax) * dx + (py - ay) * dy) / len2 if len2 else 0.0
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _densify(path, step):
    """Adds intermediate points: when the Pencil moves fast the samples are far
    apart and the eraser would skip thin strokes in between.
    The number of added points is capped: a path with extremely distant points
    (unrealistic data) cannot keep the computer busy forever."""
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]))
    step = max(step, total / MAX_DENSE_POINTS)
    out = [path[0]]
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        n = int(math.hypot(bx - ax, by - ay) / step)
        for i in range(1, n + 1):
            out.append((ax + (bx - ax) * i / (n + 1), ay + (by - ay) * i / (n + 1)))
        out.append((bx, by))
    return out


def strokes_touched(strokes, path, radius) -> list:
    """Ids of the strokes touched by the eraser path (circle of radius `radius`).
    The distance is measured from the smooth curve the editor draws, not from
    the polyline of the samples: the eraser touches exactly what is visible."""
    if not path:
        return []
    path = _densify(path, max(radius / 2, 0.5))
    hit = []
    for s in strokes:
        limit = radius + s["width"] / 2
        raw = s["points"]
        # The curve lies inside the samples' bounding box: far strokes are discarded
        # first (fast), then the curve is computed only for the near ones.
        xs, ys = [p[0] for p in raw], [p[1] for p in raw]
        x0, x1, y0, y1 = min(xs) - limit, max(xs) + limit, min(ys) - limit, max(ys) + limit
        near = [(x, y) for x, y in path if x0 <= x <= x1 and y0 <= y <= y1]
        if not near:
            continue
        pts = [(p[0], p[1]) for p in raw]
        if not s.get("shape"):          # freehand strokes are drawn as smooth curves
            pts = smooth_polyline(pts)
        if len(pts) == 1:
            touched = any(math.hypot(x - pts[0][0], y - pts[0][1]) < limit for x, y in near)
        else:
            touched = any(_dist_to_segment(x, y, a[0], a[1], b[0], b[1]) < limit
                          for x, y in near for a, b in zip(pts, pts[1:]))
        if touched:
            hit.append(s["id"])
    return hit


def _lasso_inside(polygon, w, h):
    """Function (x, y) -> True if the point is inside the lasso outline.
    The outline is drawn on a mask: checking each point becomes instant even
    with long outlines and many strokes."""
    k = min(2.0, LASSO_MASK_MAX / max(w, h, 1))
    size = (max(1, math.ceil(w * k)), max(1, math.ceil(h * k)))
    mask = Image.new("1", size, 0)
    ImageDraw.Draw(mask).polygon([(x * k, y * k) for x, y in polygon], fill=1)
    px = mask.load()

    def inside(x, y):
        i, j = int(x * k), int(y * k)
        return 0 <= i < size[0] and 0 <= j < size[1] and px[i, j] != 0
    return inside


def lasso_select(page: dict, polygon) -> dict:
    """Items enclosed by the lasso: a stroke if at least half of its points are
    inside; a text if its centre or the start of its first line is; an image
    if its centre is."""
    inside = _lasso_inside(polygon, page["w"], page["h"])
    strokes = []
    for s in page["strokes"]:
        pts = s["points"]
        sample = pts[::max(1, len(pts) // LASSO_SAMPLES)]
        if sum(inside(p[0], p[1]) for p in sample) * 2 >= len(sample):
            strokes.append(s["id"])
    texts = [t["id"] for t in page["texts"]
             if inside(t["x"] + t["w"] / 2, t["y"] + t["h"] / 2)
             or inside(t["x"] + min(t["w"], 30), t["y"] + min(t["h"], 20) / 2)]
    images = [i["id"] for i in page.get("images", [])
              if inside(i["x"] + i["w"] / 2, i["y"] + i["h"] / 2)]
    return {"strokes": strokes, "texts": texts, "images": images}
