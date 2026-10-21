// VIEW — progress bar (importing a PDF, opening a document).
// Presentation only: shows how far an operation already in progress has got.
import { formatBytes } from './format.js';

export class Progress {
  constructor() {
    this.el = document.getElementById('progress');
    this.titleEl = document.getElementById('progress-title');
    this.detailEl = document.getElementById('progress-detail');
    this.track = this.el.querySelector('.progress-track');
    this.bar = this.el.querySelector('.progress-bar');
    this.active = false;
    this.timer = null;
  }

  // delay: the bar appears only if the operation lasts longer than this (no flashes
  // for quick operations, like opening a folder).
  start(title, { delay = 0 } = {}) {
    clearTimeout(this.timer);
    clearTimeout(this.hideTimer);
    this.active = true;
    this.titleEl.textContent = title;
    this.set(null, '');
    if (delay) this.timer = setTimeout(() => this.reveal(), delay);
    else this.reveal();
  }

  reveal() {
    if (this.active) this.el.hidden = false;
  }

  // fraction: from 0 to 1; null = unknown duration (moving bar).
  set(fraction, detail) {
    if (!this.active) return;
    const known = fraction != null;
    this.track.classList.toggle('indeterminate', !known);
    this.bar.style.width = known ? `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%` : '';
    this.track.setAttribute('aria-valuenow', known ? String(Math.round(fraction * 100)) : '');
    if (detail !== undefined) this.detailEl.textContent = detail;
  }

  // Progress of a transfer, mapped onto the [from, to] interval of the bar.
  transfer(label, loaded, total, from, to) {
    if (total > 0) {
      const pct = Math.round((loaded / total) * 100);
      this.set(from + (to - from) * (loaded / total), `${label}: ${formatBytes(loaded)} di ${formatBytes(total)} (${pct}%)`);
    } else {
      this.set(null, `${label}: ${formatBytes(loaded)}`);
    }
  }

  // Done: the bar reaches the end and disappears.
  done() {
    if (!this.active) return;
    clearTimeout(this.timer);
    const visible = !this.el.hidden;
    this.set(1);
    this.active = false;
    if (visible) this.hideTimer = setTimeout(() => { if (!this.active) this.el.hidden = true; }, 280);
    else this.el.hidden = true;
  }

  // Error: it disappears right away (the view shows the message).
  fail() {
    clearTimeout(this.timer);
    this.active = false;
    this.el.hidden = true;
  }
}
