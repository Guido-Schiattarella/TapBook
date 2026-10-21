// VIEW — formatting of dates, sizes and profile photos (presentation only).

export function formatDate(epoch, withTime = true) {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleString('it-IT', withTime
    ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'long' });
}

export function formatBytes(n) {
  if (n < 1024) return `${n} byte`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
  return `${(n / 1024 ** 3).toFixed(2).replace('.', ',')} GB`;
}

// Profile photo (if any) or the name's initial. user = { name, avatar } from the controller.
export function renderAvatar(el, user) {
  el.replaceChildren();
  if (user.avatar) {
    const img = document.createElement('img');
    img.alt = '';
    img.src = '/api/account/avatar?v=' + encodeURIComponent(user.avatar);
    el.append(img);
  } else {
    el.textContent = user.name.charAt(0).toUpperCase();
  }
}

// Text with the matched part highlighted: { before, match, after } from the controller.
export function highlighted({ before, match, after }) {
  const span = document.createElement('span');
  const mark = document.createElement('mark');
  mark.textContent = match;
  span.append(before, mark, after);
  return span;
}

// Icon from the shared sprite (templates/_icons.html).
export function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'i');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name);
  svg.append(use);
  return svg;
}

// Note colours { bg, dot } received from the controller → CSS variables of the element.
export function applyNoteColor(el, color) {
  if (!color) return;
  el.style.setProperty('--note-bg', color.bg);
  el.style.setProperty('--note-dot', color.dot);
}
