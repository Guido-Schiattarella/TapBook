// VIEW — search results across all of the user's documents.
// The controller on the computer does the search; here the results are shown
// (on each note's colour) and, tapping one, the controller is asked to open the
// document at the matching page. The search field is in the top bar (shell.js).
import { applyNoteColor, highlighted, icon } from './format.js';

export class SearchView {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('search-view');
    this.summaryEl = document.getElementById('search-summary');
    this.resultsEl = document.getElementById('search-results');
  }

  show(data) {
    document.title = `Cerca «${data.query}» · TapBook`;
    document.getElementById('search-input').value = data.query;
    const n = data.results.length;
    this.summaryEl.textContent = n
      ? `${n}${data.truncated ? '+' : ''} ${n === 1 ? 'documento trovato' : 'documenti trovati'} per «${data.query}»`
      : `Nessun documento trovato per «${data.query}».`;
    this.resultsEl.replaceChildren(...data.results.map((r) => this.resultEl(r)));
  }

  hide() {}

  showMessage(msg) {
    this.summaryEl.textContent = msg;
  }

  open(path, page) {
    this.app.go('/api/open', page == null ? { path } : { path, page }).catch((e) => this.showMessage(e.message));
  }

  resultEl(r) {
    const li = document.createElement('li');
    li.className = 'row-card';
    applyNoteColor(li, r.color);
    const headRow = document.createElement('div');
    headRow.className = 'row-head';
    const head = document.createElement('button');
    const tile = document.createElement('span');
    tile.className = 'row-icon';
    tile.append(icon('logo'));
    const text = document.createElement('span');
    text.className = 'row-text';
    const name = document.createElement('strong');
    name.append(r.nameMatch ? highlighted(r.nameMatch) : r.name);
    const where = document.createElement('span');
    where.className = 'muted small';
    const folder = r.folder ? `Documenti › ${r.folder.replaceAll('/', ' › ')}` : 'Documenti';
    where.textContent = folder + (r.pages ? ` · trovato in ${r.pages} ${r.pages === 1 ? 'pagina' : 'pagine'}` : '');
    text.append(name, where);
    head.append(tile, text);
    // A match in the name opens the start of the document; if the word is only in the text, the first matching page.
    head.addEventListener('click', () => this.open(r.path, r.nameMatch || r.folderMatch ? null : r.matches[0]?.page));
    headRow.append(head);
    li.append(headRow);
    for (const m of r.matches) {
      const b = document.createElement('button');
      b.className = 'snippet';
      const page = document.createElement('span');
      page.className = 'page-no';
      page.textContent = `p. ${m.page + 1}`;
      b.append(page, highlighted(m));
      b.addEventListener('click', () => this.open(r.path, m.page));
      li.append(b);
    }
    return li;
  }
}
