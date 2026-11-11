// Shared UI pieces: toasts, confirm dialog, buttons, theme, navigation, assistant panel.
import { $, $$, esc, emit, icon } from './util.js';

/* ---------- toasts ---------- */
export function toast(message, tone = 'info', ms = 4500) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = `toast ${tone}`;
  el.setAttribute('role', tone === 'bad' ? 'alert' : 'status');
  el.innerHTML = `<span>${esc(message)}</span><button type="button" aria-label="Dismiss">×</button>`;
  el.querySelector('button').onclick = () => el.remove();
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

/* ---------- confirm dialog ---------- */
export function confirmDialog(text, okLabel = 'Delete') {
  const dlg = $('#confirmDialog');
  $('#confirmText').textContent = text;
  $('#confirmOk').textContent = okLabel;
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
    if (typeof dlg.showModal === 'function') dlg.showModal();
    else resolve(window.confirm(text));
  });
}

/* ---------- busy buttons ---------- */
export function setBusy(btn, busy, busyLabel) {
  const sp = btn.querySelector('.spinner');
  const label = btn.querySelector('.label');
  btn.disabled = busy;
  if (sp) sp.hidden = !busy;
  if (label) {
    if (busy) { label.dataset.orig = label.textContent; label.textContent = busyLabel || label.textContent; }
    else if (label.dataset.orig) label.textContent = label.dataset.orig;
  }
}

/* ---------- theme ---------- */
export function initTheme() {
  const apply = (t) => {
    document.documentElement.dataset.theme = t;
    try { localStorage.setItem('theme', t); } catch (e) { /* storage may be blocked */ }
    $('#themeLabel').textContent = t === 'dark' ? 'Light mode' : 'Dark mode';
    $('#themeIcon').innerHTML = `<use href="#i-${t === 'dark' ? 'sun' : 'moon'}"/>`;
  };
  apply(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  $('#themeBtn').addEventListener('click', () =>
    apply(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
}

/* ---------- navigation ---------- */
const VIEWS = {
  map: ['Map Navigation', 'Search places and compare real driving routes.'],
  lab: ['Algorithm Lab', 'Watch Dijkstra, BFS and DFS run on a sample city graph.'],
  history: ['History & Favourites', 'Reuse earlier routes and saved places.'],
  analytics: ['Analytics', 'Insights calculated from your saved routes and algorithm runs.'],
};

export function showView(name) {
  if (!VIEWS[name]) name = 'map';
  $$('.view').forEach((v) => { v.hidden = v.id !== `view-${name}`; });
  $$('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
  $('#pageTitle').textContent = VIEWS[name][0];
  $('#pageSub').textContent = VIEWS[name][1];
  closeSidebar();
  if (location.hash.slice(1) !== name) history.replaceState(null, '', `#${name}`);
  emit('view:show', name);
}

export function openSidebar() { $('#sidebar').classList.add('open'); $('#scrim').hidden = false; }
export function closeSidebar() { $('#sidebar').classList.remove('open'); $('#scrim').hidden = true; }

export function initNav() {
  $$('.nav-item').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));
  $('#menuBtn').addEventListener('click', openSidebar);
  $('#scrim').addEventListener('click', closeSidebar);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSidebar(); });
  window.addEventListener('hashchange', () => showView(location.hash.slice(1)));
  const pill = $('#netPill');
  const sync = () => { pill.hidden = navigator.onLine; };
  window.addEventListener('online', sync);
  window.addEventListener('offline', sync);
  sync();
}

/* ---------- assistant panel (rule-based) ---------- */
export class Assistant {
  constructor(root, { intro, chips = [] }) {
    this.root = root;
    this.intro = intro;
    root.innerHTML = `
      <div class="card-head"><h2>${icon('bot')} Smart travel assistant</h2>
        <span class="tag" title="Answers come from plain rules over real computed numbers. No external AI service is used.">Rule-based · no external AI</span></div>
      <div class="chips"></div>
      <div class="feed" aria-live="polite"><p class="empty">${esc(intro)}</p></div>`;
    this.feed = root.querySelector('.feed');
    this.chipBox = root.querySelector('.chips');
    this.chips = {};
    chips.forEach((c) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.textContent = c.label;
      b.disabled = !!c.disabled;
      b.addEventListener('click', () => c.onClick(this));
      this.chipBox.appendChild(b);
      this.chips[c.id] = b;
    });
    const clr = document.createElement('button');
    clr.type = 'button'; clr.className = 'chip'; clr.textContent = 'Clear messages';
    clr.addEventListener('click', () => this.clear());
    this.chipBox.appendChild(clr);
  }
  setChip(id, enabled) { if (this.chips[id]) this.chips[id].disabled = !enabled; }
  clear() { this.feed.innerHTML = `<p class="empty">${esc(this.intro)}</p>`; }
  /** key: a message with the same key is replaced instead of duplicated. */
  push({ title, messages, tone = 'info', key }) {
    const empty = this.feed.querySelector('.empty');
    if (empty) empty.remove();
    if (key) this.feed.querySelectorAll(`[data-key="${key}"]`).forEach((n) => n.remove());
    const el = document.createElement('div');
    el.className = `msg ${tone === 'info' ? '' : tone}`;
    if (key) el.dataset.key = key;
    el.innerHTML = `<h3>${esc(title)}</h3>` + messages.map((m) => `<p>${esc(m)}</p>`).join('');
    this.feed.prepend(el);
    while (this.feed.children.length > 6) this.feed.lastChild.remove();
  }
}
