// VIEW — editor, stroke thickness: three standard sizes (the same for every tool)
// and a custom one chosen with the slider, kept separately for each tool.
// EditorView methods (see editor_view.js): here `this` is the editor.
//
// Clicking small, medium or large moves the slider to that size; moving the
// slider selects "Personalizzato" and remembers the value for the current tool,
// so it can be chosen again later. Everything is remembered on this iPad.
import { WIDTH_PRESETS, WIDTH_TOOLS, WIDTH_DEFAULT, WIDTH_MIN, WIDTH_MAX, WIDTHS_PREF, WIDTH_PREF,
  sliderFromWidth } from './shared.js';

export class WidthMethods {
  loadWidths() {
    const valid = (n) => typeof n === 'number' && Number.isFinite(n) && n >= WIDTH_MIN && n <= WIDTH_MAX;
    let stored = {};
    let old = NaN;
    try {
      stored = JSON.parse(localStorage.getItem(WIDTHS_PREF) || '{}') || {};
      old = Number(localStorage.getItem(WIDTH_PREF));   // single thickness of earlier versions
    } catch { /* no storage available, or not readable: defaults */ }
    this.widths = {};
    for (const tool of WIDTH_TOOLS) {
      const s = stored[tool] || {};
      const choice = s.choice in WIDTH_PRESETS || s.choice === 'custom' ? s.choice : 'medium';
      this.widths[tool] = { choice, custom: valid(s.custom) ? s.custom : WIDTH_DEFAULT };
    }
    if (!stored.pen && valid(old) && old !== WIDTH_DEFAULT) this.widths.pen = { choice: 'custom', custom: old };
  }

  saveWidths() {
    try { localStorage.setItem(WIDTHS_PREF, JSON.stringify(this.widths)); } catch { /* no storage available */ }
  }

  // The tool whose thickness the toolbar shows (the others use the pen's).
  widthTool() {
    return WIDTH_TOOLS.includes(this.tool) ? this.tool : 'pen';
  }

  // Current thickness of the tool (PDF points).
  get width() {
    const s = this.widths[this.widthTool()];
    return s.choice === 'custom' ? s.custom : WIDTH_PRESETS[s.choice];
  }

  chooseWidth(choice) {
    this.widths[this.widthTool()].choice = choice;
    this.saveWidths();
    this.showWidth();
  }

  // Slider moved: "Personalizzato", with this value, for the current tool.
  setCustomWidth(value, final) {
    const s = this.widths[this.widthTool()];
    s.choice = 'custom';
    s.custom = value;
    if (final) this.saveWidths();
    this.showWidth({ moveSlider: false });
  }

  // Slider, value, dot and chosen size of the current tool.
  showWidth({ moveSlider = true } = {}) {
    const w = this.width;
    if (moveSlider) document.getElementById('width').value = sliderFromWidth(w);
    document.getElementById('width-value').textContent = (w < 1 ? w.toFixed(2) : w.toFixed(1)).replace('.', ',');
    const d = Math.max(1, Math.min(22, w * this.scale));
    Object.assign(document.getElementById('width-preview').style, { width: d + 'px', height: d + 'px' });
    const choice = this.widths[this.widthTool()].choice;
    document.querySelectorAll('#width-presets [data-width]').forEach((b) => {
      b.classList.toggle('active', b.dataset.width === choice);
      b.setAttribute('aria-checked', String(b.dataset.width === choice));
    });
  }
}
