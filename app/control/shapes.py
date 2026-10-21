"""CONTROL — recognition of geometric shapes.

The view sends the freehand stroke; here we decide which shape it is and
compute its "clean" version:

  open      straight line, or curve (a Bézier curve following the stroke)
  closed    circle, ellipse, triangle, square, rectangle
            (a non-rectangular quadrilateral stays a quadrilateral)

Method: the stroke is resampled at a constant step. If it is open, we look at
how far it strays from the line between its ends. If it is closed, we compare
how well an ellipse and the best triangle and quadrilateral fit it (mean
distance of the points from the figure): the closest figure wins, and on a tie
the one with fewer corners. Finally the shape is "straightened": rectangles,
ellipses and lines that are almost axis-aligned become aligned, almost equal
sides become equal (square, circle).

Line ends and shape corners "snap" to the corners of nearby existing shapes,
so sides meet without gaps.
"""
import math

SAMPLES = 96              # points of the resampled stroke
MIN_LENGTH = 6.0          # shorter strokes (PDF points) do not become shapes
CLOSED_GAP = 0.18         # ends closer than this fraction of the length: closed shape
LINE_DEVIATION = 0.075    # maximum distance from the straight line (fraction of the length) for a line
AXIS_SNAP_DEG = 7.0       # within these degrees of horizontal/vertical, straighten
EQUAL_RATIO = 0.86        # sides (or axes) more similar than this become equal: square, circle
RIGHT_ANGLE_TOL = 15.0    # tolerance in degrees for a quadrilateral to be a rectangle
FLAT_ANGLE = 145.0        # a "corner" flatter than this lies on a side: the quadrilateral is a triangle
MAX_RETRACE = 1.3         # stroke longer than 1.3 times the figure outline: retraced, not a shape
TRIANGLE_PREFERENCE = 1.6 # the triangle wins if its error is at most 1.6 times the quadrilateral's
MAX_FIT_ERROR = 0.035     # beyond this (mean error / perimeter) a closed stroke is not a recognisable shape
MAX_CURVE_ERROR = 0.03    # an open stroke is a "curve" only if a smooth curve follows it this closely
MAX_CURVE_RETRACE = 1.25  # ...and if it is not much longer than the curve (handwriting or a zig-zag is: it stays freehand)
CURVE_REFINE = 4          # refinement passes of the curve fit
ELLIPSE_POINTS = 72
CURVE_POINTS = 48

SHAPE_KINDS = ("line", "curve", "circle", "ellipse", "triangle", "square", "rectangle", "polygon")
SNAP_KINDS = ("line", "triangle", "square", "rectangle", "polygon")   # shapes with corners


# --- basic geometry -----------------------------------------------------------------
def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _length(pts):
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def _resample(pts, n):
    """n equally spaced points along the stroke."""
    total = _length(pts)
    if total == 0:
        return [pts[0]] * n
    step = total / (n - 1)
    out, acc = [pts[0]], 0.0
    prev = pts[0]
    i = 1
    while i < len(pts) and len(out) < n - 1:
        d = _dist(prev, pts[i])
        if acc + d >= step:
            t = (step - acc) / d
            prev = (prev[0] + (pts[i][0] - prev[0]) * t, prev[1] + (pts[i][1] - prev[1]) * t)
            out.append(prev)
            acc = 0.0
        else:
            acc += d
            prev = pts[i]
            i += 1
    while len(out) < n:
        out.append(pts[-1])
    return out


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _polygon_error(pts, verts):
    edges = list(zip(verts, verts[1:] + verts[:1]))
    return sum(min(_seg_dist(p, a, b) for a, b in edges) for p in pts) / len(pts)


def _best_polygon(pts, k):
    """Best polygon with k corners chosen among the stroke's points: start from the
    two farthest points and add, each time, the point farthest from the polygon."""
    n = len(pts)
    i0 = max(range(n), key=lambda i: _dist(pts[i], pts[0]))
    i1 = max(range(n), key=lambda i: _dist(pts[i], pts[i0]))
    idx = sorted({i0, i1})
    while len(idx) < k:
        verts = [pts[i] for i in idx]
        edges = list(zip(verts, verts[1:] + verts[:1]))
        best = max((i for i in range(n) if i not in idx),
                   key=lambda i: min(_seg_dist(pts[i], a, b) for a, b in edges))
        idx = sorted(idx + [best])
    verts = [pts[i] for i in idx]
    return verts, _polygon_error(pts, verts)


def _rotate(p, ang, c=(0.0, 0.0)):
    ca, sa = math.cos(ang), math.sin(ang)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * ca - y * sa, c[1] + x * sa + y * ca)


def _snap_angle(ang, period):
    """Angle snapped to a multiple of `period` when it is close to one."""
    k = round(ang / period)
    return k * period if abs(ang - k * period) <= math.radians(AXIS_SNAP_DEG) else ang


# --- ellipse ------------------------------------------------------------------------------
def _fit_ellipse(pts):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - cx) ** 2 for p in pts) / len(pts)
    syy = sum((p[1] - cy) ** 2 for p in pts) / len(pts)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts) / len(pts)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)         # direction of the major axis
    local = [_rotate(p, -ang, (cx, cy)) for p in pts]
    u2 = [(p[0] - cx) ** 2 for p in local]
    v2 = [(p[1] - cy) ** 2 for p in local]
    # u²/a² + v²/b² = 1 by least squares (unknowns 1/a², 1/b²)
    s11, s12, s22 = sum(a * a for a in u2), sum(a * b for a, b in zip(u2, v2)), sum(b * b for b in v2)
    r1, r2 = sum(u2), sum(v2)
    det = s11 * s22 - s12 * s12
    if det <= 0:
        return None
    ia, ib = (r1 * s22 - r2 * s12) / det, (s11 * r2 - s12 * r1) / det
    if ia <= 0 or ib <= 0:
        return None
    a, b = 1 / math.sqrt(ia), 1 / math.sqrt(ib)
    err = 0.0
    for (x, y) in local:
        t = math.atan2((y - cy) / b, (x - cx) / a)
        err += math.hypot(x - cx - a * math.cos(t), y - cy - b * math.sin(t))
    return {"c": (cx, cy), "a": a, "b": b, "ang": ang, "err": err / len(pts)}


def _ellipse_perimeter(a, b):
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def _perimeter(verts):
    return _length(verts + verts[:1])


def _ellipse_points(e):
    a, b, ang = e["a"], e["b"], e["ang"]
    if min(a, b) / max(a, b) >= EQUAL_RATIO:     # almost round: circle
        a = b = (a + b) / 2
        ang = 0.0
        kind = "circle"
    else:
        kind = "ellipse"
        ang = _snap_angle(ang, math.pi / 2)
    pts = [_rotate((e["c"][0] + a * math.cos(t), e["c"][1] + b * math.sin(t)), ang, e["c"])
           for t in (2 * math.pi * i / ELLIPSE_POINTS for i in range(ELLIPSE_POINTS))]
    return kind, pts + [pts[0]]


# --- quadrilaterals ----------------------------------------------------------------------
def _angle_at(a, b, c):
    v1, v2 = (a[0] - b[0], a[1] - b[1]), (c[0] - b[0], c[1] - b[1])
    n = math.hypot(*v1) * math.hypot(*v2)
    return 180.0 if n == 0 else math.degrees(math.acos(max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / n))))


def _quadrilateral(verts, pts):
    angles = [_angle_at(verts[i - 1], verts[i], verts[(i + 1) % 4]) for i in range(4)]
    if not all(abs(a - 90) <= RIGHT_ANGLE_TOL for a in angles):
        return "polygon", verts
    # Rectangle: mean orientation of the sides, then the stroke's bounding box in that direction.
    dirs = [math.atan2(b[1] - a[1], b[0] - a[0]) % (math.pi / 2) for a, b in zip(verts, verts[1:] + verts[:1])]
    ang = math.atan2(sum(math.sin(4 * d) for d in dirs), sum(math.cos(4 * d) for d in dirs)) / 4
    ang = _snap_angle(ang, math.pi / 2)
    c = (sum(p[0] for p in verts) / 4, sum(p[1] for p in verts) / 4)
    local = [_rotate(p, -ang, c) for p in verts]
    x0, x1 = min(p[0] for p in local), max(p[0] for p in local)
    y0, y1 = min(p[1] for p in local), max(p[1] for p in local)
    # Sides: average of the corners' box and the stroke's box (less sensitive to errors).
    lp = [_rotate(p, -ang, c) for p in pts]
    x0 = (x0 + sorted(p[0] for p in lp)[len(lp) // 20]) / 2
    x1 = (x1 + sorted(p[0] for p in lp)[-1 - len(lp) // 20]) / 2
    y0 = (y0 + sorted(p[1] for p in lp)[len(lp) // 20]) / 2
    y1 = (y1 + sorted(p[1] for p in lp)[-1 - len(lp) // 20]) / 2
    w, h = x1 - x0, y1 - y0
    kind = "rectangle"
    if min(w, h) / max(w, h) >= EQUAL_RATIO:
        kind = "square"
        side = (w + h) / 2
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        x0, x1, y0, y1 = mx - side / 2, mx + side / 2, my - side / 2, my + side / 2
    rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return kind, [_rotate(p, ang, c) for p in rect]


# --- open curves -----------------------------------------------------------------------
def _bezier_point(c, t):
    b0, b1, b2, b3 = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
    return (b0 * c[0][0] + b1 * c[1][0] + b2 * c[2][0] + b3 * c[3][0],
            b0 * c[0][1] + b1 * c[1][1] + b2 * c[2][1] + b3 * c[3][1])


def _bezier_solve(pts, ts):
    """Inner control points of the cubic with fixed ends, by least squares."""
    p0, p3 = pts[0], pts[-1]
    c11 = c12 = c22 = 0.0
    x1, x2 = [0.0, 0.0], [0.0, 0.0]
    for t, p in zip(ts, pts):
        b0, b1, b2, b3 = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
        c11 += b1 * b1
        c12 += b1 * b2
        c22 += b2 * b2
        for k in range(2):
            r = p[k] - b0 * p0[k] - b3 * p3[k]
            x1[k] += b1 * r
            x2[k] += b2 * r
    det = c11 * c22 - c12 * c12
    if abs(det) < 1e-9:
        return None
    p1 = tuple((x1[k] * c22 - x2[k] * c12) / det for k in range(2))
    p2 = tuple((c11 * x2[k] - c12 * x1[k]) / det for k in range(2))
    return [p0, p1, p2, p3]


def _bezier_fit(pts):
    """Cubic Bézier curve with the same ends that follows the stroke: a first fit
    with parameters proportional to the distance travelled, then a few passes in
    which each point is assigned the nearest point of the curve."""
    d = [0.0]
    for a, b in zip(pts, pts[1:]):
        d.append(d[-1] + _dist(a, b))
    ts = [x / d[-1] for x in d] if d[-1] else [i / (len(pts) - 1) for i in range(len(pts))]
    ctrl = _bezier_solve(pts, ts)
    if ctrl is None:
        return [pts[0], pts[-1]]
    grid = [i / 200 for i in range(201)]
    for _ in range(CURVE_REFINE):
        samples = [_bezier_point(ctrl, t) for t in grid]
        ts = [grid[min(range(len(grid)), key=lambda j: _dist(p, samples[j]))] for p in pts]
        ts[0], ts[-1] = 0.0, 1.0
        better = _bezier_solve(pts, ts)
        if better is None:
            break
        ctrl = better
    return [_bezier_point(ctrl, i / CURVE_POINTS) for i in range(CURVE_POINTS + 1)]


# --- snapping to nearby corners -----------------------------------------------------------
def snap_targets(strokes) -> list:
    """Corners of the shapes already on the page (line ends and corners)."""
    targets = []
    for s in strokes:
        if s.get("shape") in SNAP_KINDS:
            pts = [(p[0], p[1]) for p in s["points"]]
            targets.extend(pts if s["shape"] != "line" else [pts[0], pts[-1]])
    return targets


def _snap(p, targets, tolerance):
    best = min(targets, key=lambda t: _dist(p, t), default=None)
    return (best, True) if best is not None and _dist(p, best) <= tolerance else (p, False)


# --- recognition ---------------------------------------------------------------------------
def recognize(points, targets=(), tolerance=8.0):
    """Returns (kind, points) of the recognised shape, or (None, None) if the
    stroke is too short or does not resemble any shape."""
    raw = [(p[0], p[1]) for p in points]
    if len(raw) < 2 or _length(raw) < MIN_LENGTH:
        return None, None
    pts = _resample(raw, SAMPLES)
    length = _length(pts)
    closed = _dist(pts[0], pts[-1]) <= CLOSED_GAP * length

    if not closed:
        a, b = pts[0], pts[-1]
        chord = _dist(a, b)
        deviation = max(_seg_dist(p, a, b) for p in pts)
        if chord > 0 and deviation <= LINE_DEVIATION * max(chord, length * 0.5):
            a, snapped_a = _snap(a, targets, tolerance)
            b, snapped_b = _snap(b, targets, tolerance)
            if not (snapped_a or snapped_b):     # freehand line: almost horizontal/vertical → straight
                ang = math.atan2(b[1] - a[1], b[0] - a[0])
                snapped = _snap_angle(ang, math.pi / 4)
                if snapped != ang:
                    b = (a[0] + chord * math.cos(snapped), a[1] + chord * math.sin(snapped))
            return "line", [a, b]
        curve = _bezier_fit(pts)
        curve_len = _length(curve)
        err = sum(min(_seg_dist(p, a, b) for a, b in zip(curve, curve[1:])) for p in pts) / len(pts)
        if length > MAX_CURVE_RETRACE * curve_len or err > MAX_CURVE_ERROR * curve_len:
            return None, None
        return "curve", curve

    loop = pts[:-1]
    ellipse = _fit_ellipse(loop)
    tri, tri_err = _best_polygon(loop, 3)
    quad, quad_err = _best_polygon(loop, 4)
    # A quadrilateral with an almost flat corner is a triangle with an extra point on a side.
    quad_angles = [_angle_at(quad[i - 1], quad[i], quad[(i + 1) % 4]) for i in range(4)]
    if max(quad_angles) >= FLAT_ANGLE:
        quad_err = math.inf
    candidates = [("ellipse", ellipse["err"] if ellipse else math.inf),
                  ("triangle", tri_err if tri_err <= quad_err * TRIANGLE_PREFERENCE else math.inf),
                  ("quad", quad_err)]
    kind, err = min(candidates, key=lambda c: c[1])
    if err / length > MAX_FIT_ERROR:
        return None, None
    # Stroke retraced several times (a scribble): much longer than the figure outline.
    outline = (_ellipse_perimeter(ellipse["a"], ellipse["b"]) if kind == "ellipse"
               else _perimeter(tri if kind == "triangle" else quad))
    if length > MAX_RETRACE * outline:
        return None, None
    if kind == "ellipse":
        return _ellipse_points(ellipse)
    if kind == "triangle":
        verts, kind = tri, "triangle"
    else:
        kind, verts = _quadrilateral(quad, loop)
    verts = [_snap(v, targets, tolerance)[0] for v in verts]
    return kind, verts + [verts[0]]
