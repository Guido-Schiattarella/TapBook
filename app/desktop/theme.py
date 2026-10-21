"""Control panel — look: the same colours, fonts and shapes as the web
interface (view/static/css/app.css), redrawn with Tk.

  Palette        the :root colours of app.css
  RoundButton    button with rounded corners (primary, soft, danger, ghost)
  Card           rounded white card with border and soft shadow
  GradientBar    blue/light-blue gradient band, like the web sidebar
"""
import tkinter as tk
import tkinter.font as tkfont


class Palette:
    bg = "#f2f6fd"
    surface = "#ffffff"
    surface_2 = "#f6f9ff"
    text = "#1c2a4a"
    text_2 = "#3d4c6b"
    muted = "#8592ad"
    border = "#e3eaf6"
    accent = "#2f6cf6"
    accent_hover = "#2a62ee"
    accent_soft = "#e7efff"
    accent_soft_hover = "#d8e5ff"
    danger = "#e2475a"
    danger_hover = "#cc3a4c"
    danger_soft = "#fdecef"
    side_from = "#2a62ee"
    side_to = "#47a0ff"
    shadow = "#e6edf9"
    ok = "#2fa36b"
    warn = "#d9a514"


FAMILIES = ("Segoe UI", "SF Pro Text", "Inter", "Cantarell", "Noto Sans", "DejaVu Sans", "Helvetica")


class Fonts:
    """Fonts as on the web: the first available one in the CSS font stack."""

    def __init__(self, root):
        available = set(tkfont.families(root))
        family = next((f for f in FAMILIES if f in available), "TkDefaultFont")
        mono = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Noto Sans Mono", "Courier")
                     if f in available), "TkFixedFont")
        self.title = tkfont.Font(root, family=family, size=18, weight="bold")
        self.subtitle = tkfont.Font(root, family=family, size=10)
        self.heading = tkfont.Font(root, family=family, size=12, weight="bold")
        self.body = tkfont.Font(root, family=family, size=10)
        self.bold = tkfont.Font(root, family=family, size=10, weight="bold")
        self.small = tkfont.Font(root, family=family, size=9)
        self.big = tkfont.Font(root, family=family, size=13, weight="bold")
        self.button = tkfont.Font(root, family=family, size=10, weight="bold")
        self.mono = tkfont.Font(root, family=mono, size=9)


def auto_wrap(label):
    """The text wraps at the label's actual width (wider or narrower window,
    larger or smaller fonts)."""
    label.bind("<Configure>", lambda e: label.config(wraplength=max(60, e.width - 4)))
    return label


def rounded_rect(canvas, x0, y0, x1, y1, r, **kw):
    """Rectangle with rounded corners (smoothed polygon)."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return canvas.create_polygon(pts, smooth=True, splinesteps=24, **kw)


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class GradientBar(tk.Canvas):
    """Gradient band (left to right) on which the logo and title are drawn."""

    def __init__(self, parent, height, start=Palette.side_from, end=Palette.side_to, **kw):
        super().__init__(parent, height=height, highlightthickness=0, bd=0, bg=start, **kw)
        self.start, self.end = start, end
        self.bind("<Configure>", lambda e: self._paint())

    def _paint(self):
        self.delete("gradient")
        w, h = self.winfo_width(), self.winfo_height()
        steps = max(1, w // 4)
        for i in range(steps):
            x0 = w * i / steps
            self.create_rectangle(x0, 0, w * (i + 1) / steps + 1, h, width=0, tags="gradient",
                                  fill=_mix(self.start, self.end, i / max(1, steps - 1)))
        self.tag_lower("gradient")


STYLES = {
    #           background              hover background                text
    "primary": (Palette.accent, Palette.accent_hover, "#ffffff"),
    "soft": (Palette.accent_soft, Palette.accent_soft_hover, Palette.accent),
    "danger": (Palette.danger, Palette.danger_hover, "#ffffff"),
    "ghost": (Palette.surface, Palette.accent_soft, Palette.text_2),
}


class RoundButton(tk.Canvas):
    def __init__(self, parent, text, command, fonts, style="primary", width=None, height=38, bg=Palette.surface):
        self.fonts, self.text, self.command = fonts, text, command
        self.style, self.enabled, self.hover = style, True, False
        w = width or fonts.button.measure(text) + 36
        super().__init__(parent, width=w, height=height, highlightthickness=0, bd=0, bg=bg, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Configure>", lambda e: self._paint())
        self._paint()

    def configure_button(self, text=None, style=None, enabled=None, command=None):
        if text is not None:
            self.text = text
            self.config(width=max(int(self["width"]), self.fonts.button.measure(text) + 36))
        if style is not None:
            self.style = style
        if enabled is not None:
            self.enabled = enabled
            self.config(cursor="hand2" if enabled else "arrow")
        if command is not None:
            self.command = command
        self._paint()

    def _set_hover(self, on):
        self.hover = on
        self._paint()

    def _click(self, e):
        if self.enabled and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def _paint(self):
        self.delete("all")
        base, hover, fg = STYLES[self.style]
        fill = hover if self.hover and self.enabled else base
        if not self.enabled:
            fill, fg = _mix(fill, self["bg"], 0.55), _mix(fg, self["bg"], 0.35)
        w, h = self.winfo_width() or int(self["width"]), self.winfo_height() or int(self["height"])
        rounded_rect(self, 1, 1, w - 1, h - 1, 12, fill=fill, outline=fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.fonts.button)


class Card(tk.Canvas):
    """Rounded white card; its contents go in `card.body` (a Frame).
    Its height follows the contents."""
    PAD = 18

    def __init__(self, parent, fonts, title=None, bg=Palette.bg):
        super().__init__(parent, highlightthickness=0, bd=0, bg=bg, height=40)
        self.body = tk.Frame(self, bg=Palette.surface)
        if title:
            tk.Label(self.body, text=title, font=fonts.heading, fg=Palette.text, bg=Palette.surface,
                     anchor="w").pack(fill="x", pady=(0, 8))
        self.window = self.create_window(self.PAD, self.PAD, window=self.body, anchor="nw")
        self.bind("<Configure>", lambda e: self._paint())
        self.body.bind("<Configure>", lambda e: self._fit())

    def _fit(self):
        need = self.body.winfo_reqheight() + 2 * self.PAD + 4
        if int(self["height"]) != need:
            self.config(height=need)
        self._paint()

    def _paint(self):
        self.delete("shape")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        rounded_rect(self, 2, 4, w - 2, h - 1, 16, fill=Palette.shadow, outline=Palette.shadow, tags="shape")
        rounded_rect(self, 1, 1, w - 2, h - 4, 16, fill=Palette.surface, outline=Palette.border, tags="shape")
        self.tag_lower("shape")
        self.itemconfig(self.window, width=w - 2 * self.PAD)
