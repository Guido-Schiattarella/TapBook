// VIEW — start of the interface in the browser (iPad).
//
// The browser holds only the View: several views (document list, editor,
// search, trash, account) in the same page. Every user action becomes a
// request to the controller on the computer; the response carries the data and
// the name of the view to switch to. The view decides nothing on its own.
import { apiPost, apiPostProgress } from './api.js';
import { Progress } from './progress.js';
import { LibraryView } from './library_view.js';
import { EditorView } from './editor_view.js';
import { SearchView } from './search_view.js';
import { TrashView } from './trash_view.js';
import { AccountView } from './account_view.js';
import { Shell } from './shell.js';

class App {
  constructor() {
    this.views = {
      library: new LibraryView(this), editor: new EditorView(this), search: new SearchView(this),
      trash: new TrashView(this), account: new AccountView(this),
    };
    this.shell = new Shell(this);
    this.progress = new Progress();
    this.current = null;
    // Browser back/forward buttons: ask the controller for the view of that address.
    window.addEventListener('popstate', () => this.load({ push: false }));
  }

  // Request matching the current address (used when the page is reloaded).
  route() {
    const q = new URLSearchParams(location.search);
    switch (location.pathname) {
      case '/cestino': return ['/api/trash/open', {}];
      case '/account': return ['/api/account/open', {}];
      case '/cerca': return ['/api/search', { query: q.get('q') || '' }];
      default: return ['/api/open', { path: q.get('path') || '' }];
    }
  }

  urlFor(result) {
    const enc = encodeURIComponent;
    switch (result.view) {
      case 'editor': return '/edit?path=' + enc(result.path);
      case 'search': return '/cerca?q=' + enc(result.query);
      case 'trash': return '/cestino';
      case 'account': return '/account';
      default: return '/' + (result.path ? '?path=' + enc(result.path) : '');
    }
  }

  // Sends a request to the controller and switches to the view named in the response.
  // Opening a path or creating a document shows the progress bar (if it takes
  // more than a moment); progress: { title, delay } for other cases.
  async request(url, body, { push = true, progress = this.autoProgress(url, body) } = {}) {
    const result = progress ? await this.withProgress(url, body, progress) : await apiPost(url, body);
    if (result.redirect) { location.href = result.redirect; return result; }  // e.g. account deleted
    this.show(result, { push });
    return result;
  }

  autoProgress(url, body) {
    const name = (s) => String(s || '').split('/').pop().replace(/\.pdf$/i, '');
    if (url === '/api/open') {
      const isPdf = /\.pdf$/i.test(body?.path || '');
      return { title: isPdf ? `Apertura di «${name(body.path)}»` : 'Apertura…', delay: 250 };
    }
    if (url === '/api/library/newdoc') return { title: `Creazione di «${name(body?.name)}»`, delay: 250 };
    return null;
  }

  // Request with a progress bar: upload (file to import), waiting for the
  // computer, download (the document). When switching to the editor, the editor
  // completes the bar once the first page is drawn.
  async withProgress(url, body, { title, delay = 0 }) {
    const p = this.progress;
    const upload = body instanceof FormData;
    p.start(title, { delay });
    p.set(upload ? 0 : null, upload ? 'Caricamento…' : 'Il computer prepara il documento…');
    try {
      const result = await apiPostProgress(url, body, {
        onUpload: upload ? (loaded, total) => p.transfer('Caricamento', loaded, total, 0, 0.9) : null,
        onWaiting: () => p.set(null, upload ? 'Controllo del PDF sul computer…' : 'Il computer prepara il documento…'),
        // The response is small (the editor's PDF is downloaded afterwards, measured by the editor).
        onDownload: null,
      });
      if (result?.view !== 'editor') p.done();
      return result;
    } catch (e) {
      p.fail();
      throw e;
    }
  }

  // Like request, but when leaving the editor it is closed first (saves).
  async go(url, body, options) {
    if (this.current === 'editor') await this.views.editor.close();
    return this.request(url, body, options);
  }

  goTo(url) {
    this.go(url, {}).catch((e) => this.views[this.current]?.showMessage?.(e.message));
  }

  async load(options) {
    const [url, body] = this.route();
    try {
      await this.go(url, body, options);
    } catch (e) {
      this.show({ view: 'library', path: '', entries: [] }, { push: false });
      this.views.library.showMessage(e.message);
      if (e.status === 404 || e.status === 400) this.navigate('');
    }
  }

  async navigate(path, { push = true } = {}) {
    try {
      await this.go('/api/open', { path }, { push });
    } catch (e) {
      if (this.current !== 'library') this.show({ view: 'library', path: '', entries: [] }, { push: false });
      this.views.library.showMessage(e.message);
      if (e.status === 404 && path) this.navigate('');
    }
  }

  search(query) {
    if (!query.trim()) return;
    this.go('/api/search', { query }).catch((e) => this.views[this.current]?.showMessage?.(e.message));
  }

  // Shows the view named by the controller.
  show(result, { push = true } = {}) {
    const name = result.view;
    if (this.current && this.current !== name) this.views[this.current].hide();
    for (const [key, view] of Object.entries(this.views)) view.element.hidden = key !== name;
    // The editor takes the whole screen; the other views sit inside the frame.
    this.shell.element.hidden = name === 'editor';
    if (name !== 'editor') this.shell.render(result);
    document.body.className = name === 'editor' ? 'editor-page' : 'browser-page';
    this.current = name;
    const url = this.urlFor(result);
    if (push && url !== location.pathname + location.search) history.pushState(null, '', url);
    else history.replaceState(null, '', url);
    this.views[name].show(result);
  }
}

const app = new App();
app.load({ push: false });
