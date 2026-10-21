// VIEW — list of layouts to choose from (new document and editor).
// Names and previews come from the controller: the view does not know what a layout looks like.

export function layoutPreviewUrl(id) {
  return '/api/layout/preview?id=' + encodeURIComponent(id);
}

// Fills `container` with one option per layout; onPick(id) when one is chosen.
// The chosen option has the "selected" class, set here and always on a single option
// (the CSS :has selector is not used: Safari on the iPad does not always update it).
export function renderLayoutOptions(container, layouts, selected, group, onPick) {
  const mark = (id) => container.querySelectorAll('.layout-option').forEach((l) =>
    l.classList.toggle('selected', l.querySelector('input').value === id));
  container.replaceChildren(...layouts.map((layout) => {
    const label = document.createElement('label');
    label.className = 'layout-option';
    const input = document.createElement('input');
    input.type = 'radio';
    input.name = group;
    input.value = layout.id;
    input.checked = layout.id === selected;
    label.classList.toggle('selected', input.checked);
    input.addEventListener('change', () => { mark(layout.id); onPick(layout.id); });
    const img = document.createElement('img');
    img.src = layoutPreviewUrl(layout.id);
    img.alt = '';
    const name = document.createElement('span');
    name.textContent = layout.label;
    label.append(input, img, name);
    return label;
  }));
}
