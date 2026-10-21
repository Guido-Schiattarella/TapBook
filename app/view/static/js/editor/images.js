// VIEW — editor, images: choosing the photo, upload, placement and resizing.
// EditorView methods (see editor_view.js): here `this` is the editor.
import { apiPost } from '../api.js';

export class ImagesMethods {
  // =====================================================================
  // Images
  // =====================================================================
  // Where to put the photo: at the tapped point or, from the button, at the centre of the visible page.
  pickImage(target) {
    if (!target) {
      const page = this.pages[this.currentPageIndex()];
      const r = this.els.get(page.id).el.getBoundingClientRect();
      const view = this.pagesEl.getBoundingClientRect();
      const midY = (Math.max(r.top, view.top) + Math.min(r.bottom, view.bottom)) / 2;
      target = { page: page.id, x: page.w / 2, y: (midY - r.top) / this.scale };
    }
    this.imageTarget = target;
    this.imageInput.click();  // on the iPad: choose between "Take photo" and "Photo library"
  }

  uploadImage(target, file) {
    this.tool = 'image';
    this.showTool();
    this.enqueue((session) => {
      const form = new FormData();
      form.append('session', session);
      form.append('page', target.page);
      form.append('x', target.x);
      form.append('y', target.y);
      form.append('file', file);
      return apiPost('/api/edit/image', form);
    });
    this.setStatus('Caricamento foto…');
  }

  renderImages(page) {
    const v = this.els.get(page.id);
    if (v) v.images.replaceChildren(...page.images.map((img) => this.imageEl(page, img)));
  }

  placeImage(el, img) {
    const k = this.scale;
    Object.assign(el.style, { left: img.x * k + 'px', top: img.y * k + 'px', width: img.w * k + 'px', height: img.h * k + 'px' });
  }

  imageEl(page, img) {
    const el = document.createElement('div');
    el.className = 'imagebox';
    el.dataset.id = img.id;
    const pic = document.createElement('img');
    pic.draggable = false;
    pic.alt = '';
    pic.src = `/api/edit/picture?session=${encodeURIComponent(this.session)}&id=${encodeURIComponent(img.id)}`;
    const remove = document.createElement('button');
    remove.className = 'remove';
    remove.textContent = '✕';
    const resize = document.createElement('span');
    resize.className = 'resize';
    el.append(pic, remove, resize);
    this.placeImage(el, img);
    remove.addEventListener('click', () => this.send({ type: 'removeImage', page: page.id, id: img.id }));
    // Dragging the image moves it; dragging the corner resizes it (proportions
    // kept). The final position goes to the controller.
    const drag = (e, mode) => {
      if (this.tool !== 'image') return;
      e.preventDefault();
      e.stopPropagation();
      const target = e.currentTarget;
      try { target.setPointerCapture(e.pointerId); } catch { /* ignored */ }
      const start = { cx: e.clientX, cy: e.clientY, x: img.x, y: img.y, w: img.w };
      const ratio = img.h / img.w;
      const move = (ev) => {
        const dx = (ev.clientX - start.cx) / this.scale, dy = (ev.clientY - start.cy) / this.scale;
        if (mode === 'move') { img.x = start.x + dx; img.y = start.y + dy; }
        else { img.w = Math.max(20, start.w + dx); img.h = img.w * ratio; }
        this.placeImage(el, img);
      };
      const up = () => {
        target.removeEventListener('pointermove', move);
        target.removeEventListener('pointerup', up);
        target.removeEventListener('pointercancel', up);
        if (img.x !== start.x || img.y !== start.y || img.w !== start.w) {
          this.send({ type: 'changeImage', page: page.id, id: img.id, x: img.x, y: img.y, w: img.w, h: img.h });
        }
      };
      target.addEventListener('pointermove', move);
      target.addEventListener('pointerup', up);
      target.addEventListener('pointercancel', up);
    };
    pic.addEventListener('pointerdown', (e) => drag(e, 'move'));
    resize.addEventListener('pointerdown', (e) => drag(e, 'resize'));
    return el;
  }
}
