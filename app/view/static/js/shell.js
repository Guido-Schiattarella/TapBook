// VIEW — frame shared by list, search, trash and account: sidebar (sections and
// top-level folders) and top bar (search, greeting, photo).
// The data (user, folders) comes from the controller in every response ("shell").
import { renderAvatar } from './format.js';

// Colours of the folder dots in the sidebar (presentation only).
const FOLDER_DOTS = ['#ffd36b', '#7fe0c4', '#ffb3c7', '#bfe3ff', '#c9b8ff', '#ffc59e'];

export class Shell {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('shell');
    this.foldersEl = document.getElementById('side-folders');
    this.searchInput = document.getElementById('search-input');
    this.navItems = [...document.querySelectorAll('.nav-item')];
    const go = { library: () => app.navigate(''), trash: () => app.goTo('/api/trash/open'),
      account: () => app.goTo('/api/account/open'), search: () => this.focusSearch() };
    this.navItems.forEach((b) => b.addEventListener('click', () => go[b.dataset.nav]()));
    document.getElementById('btn-account').addEventListener('click', go.account);
    document.getElementById('side-add-folder').addEventListener('click', () => app.views.library.createFolder(''));
    document.getElementById('search-form').addEventListener('submit', (e) => {
      e.preventDefault();
      this.app.search(this.searchInput.value);
      this.searchInput.blur();
    });
  }

  focusSearch() {
    this.searchInput.focus();
    this.searchInput.select();
  }

  // result: the controller's response with the view and the frame data.
  render(result) {
    const { shell, view } = result;
    if (shell) {
      renderAvatar(document.getElementById('topbar-avatar'), shell.user);
      document.getElementById('hello-text').textContent = `Ciao, ${shell.user.name}!`;
      this.foldersEl.replaceChildren(...shell.folders.map((name, i) => {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.dataset.folder = name;
        const dot = document.createElement('i');
        dot.className = 'dot';
        dot.style.background = FOLDER_DOTS[i % FOLDER_DOTS.length];
        const label = document.createElement('span');
        label.textContent = name;
        b.append(dot, label);
        b.title = name;
        b.addEventListener('click', () => this.app.navigate(name));
        li.append(b);
        return li;
      }));
    }
    const top = view === 'library' ? (result.path || '').split('/')[0] : null;
    this.navItems.forEach((b) => b.classList.toggle('active', b.dataset.nav === view));
    this.foldersEl.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.folder === top));
    if (view !== 'search') this.searchInput.value = '';
  }
}
