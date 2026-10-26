"""Shape recognition: rates on many hand-drawn-like strokes, slow and fast (few
samples, left open or drawn past the start). Minimum rates are those measured
when the recogniser was tuned: a change that lowers them fails here."""
import math
import random
from _common import Checks
from app.control.shapes import recognize


def jit(rnd, pts, a=0.6):
    return [(x + rnd.gauss(0, a), y + rnd.gauss(0, a)) for x, y in pts]


def ellipse(rnd, close=1.0, n=110, noise=0.8):
    rx = rnd.uniform(30, 140); ry = rx * rnd.uniform(0.35, 1); rot = rnd.uniform(0, 3.14); t0 = rnd.uniform(0, 6.28)
    pts = []
    for k in range(n):
        t = t0 + 2 * math.pi * close * k / (n - 1)
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((300 + x * math.cos(rot) - y * math.sin(rot) + rnd.gauss(0, noise), 400 + x * math.sin(rot) + y * math.cos(rot) + rnd.gauss(0, noise)))
    return pts


def poly(rnd, verts, close):
    sides = [(verts[i], verts[(i + 1) % len(verts)]) for i in range(len(verts))]
    per = sum(math.dist(a, b) for a, b in sides); out = []; acc = 0
    while acc < per * close:
        s = acc % per
        for a, b in sides:
            L = math.dist(a, b)
            if s <= L:
                out.append((a[0] + (b[0] - a[0]) * s / L, a[1] + (b[1] - a[1]) * s / L)); break
            s -= L
        acc += 2.0
    return jit(rnd, out)


def rect(rnd, close):
    w, h = rnd.uniform(60, 220), rnd.uniform(40, 160)
    return poly(rnd, [(100, 100), (100 + w, 100), (100 + w, 100 + h), (100, 100 + h)], close)


def tri(rnd, close):
    s = rnd.uniform(60, 200)
    return poly(rnd, [(100, 100 + s), (100 + s / 2, 100), (100 + s, 100 + s)], close)


def arc(rnd, turn):
    r = rnd.uniform(40, 150); t0 = rnd.uniform(0, 6.28)
    return jit(rnd, [(300 + r * math.cos(t0 + 2 * math.pi * turn * k / 80), 300 + r * math.sin(t0 + 2 * math.pi * turn * k / 80)) for k in range(81)])


def line(rnd):
    L = rnd.uniform(40, 300); a = rnd.uniform(0, 3.14)
    return jit(rnd, [(200 + L * k / 60 * math.cos(a), 200 + L * k / 60 * math.sin(a)) for k in range(61)])


def scribble(rnd):
    turns = rnd.uniform(2.2, 4); r = rnd.uniform(30, 80)
    return jit(rnd, [(300 + r * (1 + 0.3 * math.sin(k / 7)) * math.cos(k / 100 * 2 * math.pi * turns), 300 + r * math.sin(k / 100 * 2 * math.pi * turns)) for k in range(101)], 2)


ELL = ("ellipse", "circle")
CASES = [  # name, generator, accepted kinds, minimum out of 60
    ("linea", line, ("line",), 60),
    ("arco 1/2 giro (resta curva)", lambda r: arc(r, 0.5), ("curve",), 60),
    ("arco 0,65 di giro (resta curva)", lambda r: arc(r, 0.65), ("curve",), 57),
    ("ellisse chiusa", lambda r: ellipse(r), ELL, 59),
    ("ellisse veloce, 14 campioni", lambda r: ellipse(r, n=14), ELL, 57),
    ("ellisse con buco del 15%", lambda r: ellipse(r, 0.85, n=20), ELL, 54),
    ("ellisse con buco del 22%", lambda r: ellipse(r, 0.78, n=20), ELL, 40),
    ("ellisse oltre il 30%", lambda r: ellipse(r, 1.3, n=24), ELL, 57),
    ("rettangolo chiuso", lambda r: rect(r, 1.0), ("rectangle", "square"), 59),
    ("rettangolo con buco del 15%", lambda r: rect(r, 0.85), ("rectangle", "square"), 50),
    ("triangolo con buco del 15%", lambda r: tri(r, 0.85), ("triangle",), 50),
    ("scarabocchio (più giri)", scribble, (None,), 60),
]


def main():
    check = Checks("test_shapes")
    rows = []
    for name, gen, ok, minimum in CASES:
        rnd = random.Random(1)
        good = sum(recognize(gen(rnd))[0] in ok for _ in range(60))
        rows.append(f"   {name:34s} {good:2d}/60 (minimo {minimum})")
        check(good >= minimum, f"{name}: {good}/60 < {minimum}")
    check.done()
    print("\n".join(rows))


if __name__ == "__main__":
    main()
