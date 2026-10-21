// VIEW — document list.
// Shows the folder contents received from the controller (coloured cards with
// title and creation date) and forwards the user's actions to it. Every
// controller response names the next view (for example opening a PDF switches to the editor).
import { renderLayoutOptions } from './layout_picker.js';
import { applyNoteColor, formatDate, icon } from './format.js';

export class LibraryView {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('library-view');
    this.entriesEl = document.getElementById('entries');
    this.emptyEl = document.getElementById('empty');
    this.crumbsEl = document.getElementById('crumbs');
    this.messageEl = document.getElementById('message');
    this.path = '';
    this.entries = [];
    this.filter = 'all';         // All / Documents / Folders (only what to show)
    this.newDocument = null;     // name, colour and layout proposed by the controller for a new document
    this.dialog = document.getElementById('newdoc-dialog');
    this.nameInput = document.getElementById('newdoc-name');

    document.getElementById('btn-mkdir').addEventListener('click', () => this.createFolder(this.path));
    document.getElementById('btn-newdoc').addEventListener('click', () => this.createDocument());
    document.getElementById('file-upload').addEventListener('change', (ev) => {
      const file = ev.target.files[0];
      ev.target.value = '';
      if (file) this.importPdf(file);
    });
    document.querySelectorAll('#library-view .pill').forEach((b) => b.addEventListener('click', () => {
      this.filter = b.dataset.filter;
      this.renderEntries();
    }));
    document.getElementById('newdoc-cancel').addEventListener('click', () => this.dialog.close());
    document.getElementById('newdoc-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const name = this.nameInput.value.trim();
      if (!name) return;
      this.dialog.close();
      this.send('/api/library/newdoc', { path: this.path, name, layout: this.chosenLayout, color: this.chosenColor });
    });
  }

  // --- requests to the controller ----------------------------------------------------
  async send(url, body) {
    try {
      await this.app.request(url, body);
    } catch (e) {
      this.showMessage(e.message);
    }
  }

  pathOf(entry) {
    return this.path ? `${this.path}/${entry.name}` : entry.name;
  }

  open(path) {
    this.app.navigate(path);
  }

  createFolder(parent) {
    const name = window.prompt('Nome della nuova cartella');
    if (name) this.send('/api/library/mkdir', { path: parent, name });
  }

  // New document: name, note colour and layout of the first page.
  createDocument() {
    const proposal = this.newDocument;
    if (!proposal) return;
    this.chosenLayout = proposal.layout;
    this.chosenColor = proposal.color;
    this.nameInput.value = proposal.name;
    this.renderSwatches(proposal.colors, proposal.color);
    renderLayoutOptions(document.getElementById('newdoc-layouts'), proposal.layouts, proposal.layout, 'newdoc-layout',
      (id) => { this.chosenLayout = id; });
    this.dialog.showModal();
    this.nameInput.select();   // focus goes to the name, not to the first option
  }

  renderSwatches(colors, selected) {
    document.getElementById('newdoc-colors').replaceChildren(...colors.map((c) => {
      const label = document.createElement('label');
      label.className = 'swatch';
      label.title = c.label;
      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'newdoc-color';
      input.value = c.id;
      input.checked = c.id === selected;
      input.setAttribute('aria-label', c.label);
      input.addEventListener('change', () => { this.chosenColor = c.id; });
      const dot = document.createElement('span');
      applyNoteColor(label, c);
      label.append(input, dot);
      return label;
    }));
  }

  async importPdf(file) {
    const form = new FormData();
    form.append('path', this.path);
    form.append('file', file);
    this.showMessage('');
    try {
      await this.app.request('/api/library/upload', form, { progress: { title: `Importazione di «${file.name}»` } });
    } catch (e) {
      this.showMessage(e.message);
    }
  }

  rename(entry) {
    const current = displayName(entry);
    const name = window.prompt('Nuovo nome', current);
    if (name && name !== current) this.send('/api/library/rename', { path: this.pathOf(entry), name });
  }

  moveToTrash(entry) {
    if (window.confirm(`Spostare «${displayName(entry)}» nel cestino?`)) {
      this.send('/api/library/delete', { path: this.pathOf(entry) });
    }
  }

  // --- drawing -------------------------------------------------------------------------------
  show(data) {
    this.path = data.path;
    this.entries = data.entries;
    if (data.newDocument) this.newDocument = data.newDocument;
    document.title = (data.path ? data.path.split('/').pop() : 'Documenti') + ' · TapBook';
    this.showMessage('');
    this.renderCrumbs();
    this.renderEntries();
  }

  hide() {}

  showMessage(msg) {
    this.messageEl.textContent = msg;
    this.messageEl.hidden = !msg;
  }

  renderEntries() {
    document.querySelectorAll('#library-view .pill').forEach((b) => b.classList.toggle('active', b.dataset.filter === this.filter));
    const shown = this.entries.filter((e) => this.filter === 'all' || e.type === this.filter);
    this.entriesEl.replaceChildren(...shown.map((e) => this.entryEl(e)));
    this.emptyEl.hidden = shown.length > 0;
  }

  renderCrumbs() {
    this.crumbsEl.replaceChildren();
    const parts = this.path ? this.path.split('/') : [];
    const add = (label, target) => {
      const a = document.createElement('a');
      a.href = '/?path=' + encodeURIComponent(target);
      a.textContent = label;
      a.addEventListener('click', (e) => { e.preventDefault(); this.open(target); });
      this.crumbsEl.append(a);
    };
    add('Documenti', '');
    parts.forEach((p, i) => {
      const sep = document.createElement('span');
      sep.className = 'sep';
      sep.textContent = '›';
      this.crumbsEl.append(sep);
      add(p, parts.slice(0, i + 1).join('/'));
    });
  }

  // Card: for a document the creation date, dot and title on the note colour; for
  // a folder icon, name and number of items. Rename and Delete at the bottom.
  entryEl(entry) {
    const li = document.createElement('li');
    const isDir = entry.type === 'dir';
    li.className = 'card' + (isDir ? ' folder' : '');
    if (!isDir) applyNoteColor(li, entry.color);
    const path = this.pathOf(entry);
    const a = document.createElement('a');
    a.className = 'card-open';
    a.href = (isDir ? '/' : '/edit') + '?path=' + encodeURIComponent(path);
    // Folder or PDF: the controller answers with the right view.
    a.addEventListener('click', (e) => { e.preventDefault(); this.open(path); });

    const title = document.createElement('span');
    title.className = 'card-title';
    const name = document.createElement('span');
    name.textContent = displayName(entry);
    if (isDir) {
      const tile = document.createElement('span');
      tile.className = 'folder-tile';
      tile.append(icon('folder'));
      title.append(name);
      const meta = document.createElement('span');
      meta.className = 'card-meta';
      meta.textContent = entry.items === 1 ? '1 elemento' : `${entry.items ?? 0} elementi`;
      a.append(tile, title, meta);
    } else {
      const date = document.createElement('span');
      date.className = 'card-date';
      date.textContent = formatDate(entry.created, false);
      const dot = document.createElement('i');
      dot.className = 'dot';
      title.append(dot, name);
      a.append(date, title);
    }

    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const rename = document.createElement('button');
    rename.append(icon('edit'), 'Rinomina');
    rename.addEventListener('click', () => this.rename(entry));
    const del = document.createElement('button');
    del.className = 'del';
    del.append(icon('trash'), 'Elimina');
    del.addEventListener('click', () => this.moveToTrash(entry));
    actions.append(rename, del);
    li.append(a, actions);
    return li;
  }
}

function displayName(entry) {
  return entry.type === 'pdf' ? entry.name.replace(/\.pdf$/i, '') : entry.name;
}
