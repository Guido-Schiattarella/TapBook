"""MODEL — page layouts (blank, lined, squared, dotted, Cornell).

The layout is drawn INSIDE the PDF page, like the background of a notebook:
any PDF reader on the computer shows it and the eraser cannot remove it.
Every page created by the app remembers its layout in its PDF dictionary
(key NotesAppLayout), so it is found again after reopening.

This is the only place where layouts are drawn. The names shown to the user
are added by the controller (control/library.py); the view receives the list
(id and name), the preview (PNG) and, for new pages not saved yet, the empty
page already drawn (PDF).
"""
import functools
import math

import pymupdf

MM = 72 / 25.4      # PDF points in one millimetre

# Available layouts (in the order shown in the menus).
LAYOUTS = ("blank", "lined", "squared", "dotted", "cornell_lined", "cornell_squared")
DEFAULT = "blank"

LINE_COLOR = (0.66, 0.78, 0.91)    # soft blue of the lines
MARGIN_COLOR = (0.93, 0.62, 0.62)  # soft red of the margin
GRID_COLOR = (0.78, 0.85, 0.93)
DOT_COLOR = (0.55, 0.60, 0.68)
CORNELL_COLOR = (0.42, 0.52, 0.68)  # lines dividing the areas of the Cornell method


def exists(layout) -> bool:
    return isinstance(layout, str) and layout in LAYOUTS


def _lines(shape, x0, x1, y0, y1, step):
    """Horizontal lines from y0 to y1 (inclusive) between x0 and x1."""
    y = y0
    while y <= y1 + 0.01:
        shape.draw_line((x0, y), (x1, y))
        y += step
    shape.finish(color=LINE_COLOR, width=0.6, closePath=False)


def _grid(shape, x0, x1, y0, y1, step):
    """Grid squares in the rectangle, aligned to its top-left corner."""
    x = x0 + step
    while x < x1 - 0.01:
        shape.draw_line((x, y0), (x, y1))
        x += step
    y = y0 + step
    while y < y1 - 0.01:
        shape.draw_line((x0, y), (x1, y))
        y += step
    shape.finish(color=GRID_COLOR, width=0.45, closePath=False)


def _cornell(shape, w, h, kind):
    """Cornell method: space for title and date at the top, column for keywords
    and questions on the left, notes on the right, summary at the bottom.
    Lines or grid cover the column and the notes; title and summary stay blank."""
    top = 20 * MM
    cue = min(60 * MM, w * 0.3)
    summary = h - min(50 * MM, h * 0.2)
    if kind == "lined":
        _lines(shape, 0, w, top + 8 * MM, summary - 4 * MM, 8 * MM)
    else:
        _grid(shape, 0, w, top, summary, 5 * MM)
    shape.draw_line((0, top), (w, top))
    shape.draw_line((cue, top), (cue, summary))
    shape.draw_line((0, summary), (w, summary))
    shape.finish(color=CORNELL_COLOR, width=1.1, closePath=False)


def draw(page: pymupdf.Page, layout):
    """Draws the layout on a new (empty) page."""
    w, h = page.rect.width, page.rect.height
    shape = page.new_shape()
    if layout == "lined":
        _lines(shape, 0, w, 25 * MM, h - 12 * MM, 8 * MM)
        shape.draw_line((25 * MM, 0), (25 * MM, h))
        shape.finish(color=MARGIN_COLOR, width=0.8, closePath=False)
    elif layout == "squared":
        _grid(shape, 0, w, 0, h, 5 * MM)
    elif layout == "dotted":
        # A dot = an almost zero-length dash with a round cap.
        # On huge pages (unusual imported PDFs) they thin out: at most 300,000 dots.
        step = max(5 * MM, math.sqrt(w * h / 300000))
        y = step
        while y < h:
            x = step
            while x < w:
                shape.draw_line((x, y), (x + 0.01, y))
                x += step
            y += step
        shape.finish(color=DOT_COLOR, width=1.3, lineCap=1, closePath=False)
    elif layout == "cornell_lined":
        _cornell(shape, w, h, "lined")
    elif layout == "cornell_squared":
        _cornell(shape, w, h, "squared")
    else:
        return
    shape.commit(overlay=False)


def new_page(doc: pymupdf.Document, width: float, height: float, layout) -> pymupdf.Page:
    page = doc.new_page(width=width, height=height)
    draw(page, layout)
    return page


@functools.lru_cache(maxsize=64)
def page_pdf(layout: str, width: float, height: float) -> bytes:
    """An empty page with the layout: the view uses it as the background of pages
    added in this session, until they are saved into the PDF."""
    doc = pymupdf.open()
    new_page(doc, width, height, layout)
    data = doc.tobytes(deflate=True)
    doc.close()
    return data


@functools.lru_cache(maxsize=16)
def preview_png(layout: str) -> bytes:
    """Preview (PNG) of an A4 page with the layout, for the menus."""
    doc = pymupdf.open(stream=page_pdf(layout, 595.0, 842.0), filetype="pdf")
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(0.4, 0.4), alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return data
