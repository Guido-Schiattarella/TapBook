// VIEW — account: profile photo, password change, account deletion.
// The checks (current password, rules, confirmation) are done by the controller on the computer.
import { formatBytes, formatDate, renderAvatar } from './format.js';

export class AccountView {
  constructor(app) {
    this.app = app;
    this.element = document.getElementById('account-view');
    this.messageEl = document.getElementById('account-message');
    this.avatarInput = document.getElementById('avatar-input');
    this.removeBtn = document.getElementById('btn-avatar-remove');
    this.passwordForm = document.getElementById('password-form');
    this.deleteForm = document.getElementById('delete-form');

    this.avatarInput.addEventListener('change', () => {
      const file = this.avatarInput.files[0];
      this.avatarInput.value = '';
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      this.showMessage('Caricamento della foto…');
      this.send('/api/account/avatar', form, this.messageEl);
    });
    this.removeBtn.addEventListener('click', () => this.send('/api/account/avatar/delete', {}, this.messageEl));
    this.passwordForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const f = new FormData(this.passwordForm);
      this.send('/api/account/password',
        { current: f.get('current'), new: f.get('new'), confirm: f.get('confirm') },
        document.getElementById('password-error'));
    });
    this.deleteForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!window.confirm('Eliminare definitivamente il tuo account? Non potrai più accedere con questo nome.')) return;
      const f = new FormData(this.deleteForm);
      this.send('/api/account/delete', { password: f.get('password'), confirm: f.get('confirm') },
        document.getElementById('delete-error'));
    });
  }

  // Sends a request to the controller; an error is shown at the given place.
  async send(url, body, errorEl) {
    errorEl.hidden = true;
    try {
      await this.app.request(url, body);
    } catch (e) {
      errorEl.textContent = e.message;
      errorEl.hidden = false;
    }
  }

  show(data) {
    document.title = 'Account · TapBook';
    const { user, stats } = data;
    renderAvatar(document.getElementById('account-avatar'), user);
    document.getElementById('account-name').textContent = user.name;
    document.getElementById('password-username').value = user.name;
    document.getElementById('account-dates').textContent =
      `Account creato il ${formatDate(data.created, false)} · ultimo accesso ${formatDate(data.lastLogin)}`;
    const stat = (value, label) => {
      const el = document.createElement('div');
      el.className = 'stat';
      const b = document.createElement('b');
      b.textContent = value;
      const span = document.createElement('span');
      span.textContent = label;
      el.append(b, span);
      return el;
    };
    document.getElementById('account-stats').replaceChildren(
      stat(stats.documents, stats.documents === 1 ? 'documento' : 'documenti'),
      stat(stats.folders, stats.folders === 1 ? 'cartella' : 'cartelle'),
      stat(formatBytes(stats.size), 'spazio occupato'),
      stat(stats.trash, stats.trash === 1 ? 'elemento nel cestino' : 'elementi nel cestino'));
    this.removeBtn.hidden = !user.avatar;
    this.passwordForm.reset();
    this.deleteForm.reset();
    document.getElementById('password-error').hidden = true;
    document.getElementById('delete-error').hidden = true;
    this.showMessage(data.message);
  }

  hide() {}

  showMessage(msg) {
    this.messageEl.textContent = msg || '';
    this.messageEl.hidden = !msg;
  }
}
