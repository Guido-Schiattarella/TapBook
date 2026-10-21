// VIEW — trash: deleted items, restore and permanent deletion.
// Every action is a request to the controller, which answers with the updated trash.
import { formatBytes, formatDate, icon } from './format.js';

export class TrashView {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('trash-view');
    this.listEl = document.getElementById('trash-entries');
    this.emptyEl = document.getElementById('trash-empty');
    this.messageEl = document.getElementById('trash-message');
    this.emptyBtn = document.getElementById('btn-empty-trash');
    this.emptyBtn.addEventListener('click', () => {
      if (window.confirm('Svuotare il cestino? Tutti gli elementi verranno eliminati definitivamente e non si potranno più recuperare.')) {
        this.send('/api/trash/empty', {});
      }
    });
  }

  async send(url, body) {
    try {
      await this.app.request(url, body);
    } catch (e) {
      this.showMessage(e.message);
    }
  }

  show(data) {
    document.title = 'Cestino · TapBook';
    this.showMessage(data.message);
    this.listEl.replaceChildren(...data.entries.map((e) => this.entryEl(e)));
    this.emptyEl.hidden = data.entries.length > 0;
    this.emptyBtn.disabled = data.entries.length === 0;
  }

  hide() {}

  showMessage(msg) {
    this.messageEl.textContent = msg || '';
    this.messageEl.hidden = !msg;
  }

  entryEl(e) {
    const li = document.createElement('li');
    li.className = 'row-card';
    const row = document.createElement('div');
    row.className = 'row-head';
    const tile = document.createElement('span');
    tile.className = 'row-icon';
    tile.append(icon(e.type === 'dir' ? 'folder' : 'logo'));
    const text = document.createElement('span');
    text.className = 'row-text';
    const name = document.createElement('strong');
    name.textContent = e.type === 'pdf' ? e.name.replace(/\.pdf$/i, '') : e.name;
    const meta = document.createElement('span');
    meta.className = 'muted small';
    const from = e.from == null ? 'posizione non nota (tornerà in Documenti)'
      : (e.from ? `da Documenti › ${e.from.replaceAll('/', ' › ')}` : 'da Documenti');
    meta.textContent = `Eliminato il ${formatDate(e.deleted)} · ${formatBytes(e.size)} · ${from}`;
    text.append(name, meta);
    const actions = document.createElement('div');
    actions.className = 'row-actions';
    const restore = document.createElement('button');
    restore.className = 'soft';
    restore.append(icon('restore'), 'Ripristina');
    restore.addEventListener('click', () => this.send('/api/trash/restore', { entry: e.entry }));
    const del = document.createElement('button');
    del.className = 'del';
    del.append(icon('trash'), 'Elimina definitivamente');
    del.addEventListener('click', () => {
      if (window.confirm(`Eliminare definitivamente «${name.textContent}»? Non si potrà più recuperare.`)) {
        this.send('/api/trash/delete', { entry: e.entry });
      }
    });
    actions.append(restore, del);
    row.append(tile, text, actions);
    li.append(row);
    return li;
  }
}
