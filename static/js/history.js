// History & favourites view.
import { api } from './api.js';
import { $, emit, esc, fmtDate, fmtDur, fmtKm, icon, on } from './util.js';
import { confirmDialog, toast } from './ui.js';
import { state } from './state.js';

const trash = (act, id, label) =>
  `<button type="button" class="icon-btn" data-act="${act}" data-id="${id}" title="${label}" aria-label="${label}">${icon('trash')}</button>`;

function render() {
  const h = $('#historyList');
  $('#clearHistoryBtn').disabled = state.history.length === 0;
  h.innerHTML = state.history.length ? `<div class="list">${state.history.map((r) => `
    <div class="item">
      <div class="txt">
        <div class="t">${esc(r.origin_name)} → ${esc(r.dest_name)}</div>
        <small>${r.distance_m != null ? fmtKm(r.distance_m) : 'distance n/a'} · ${r.duration_s != null ? 'est. ' + fmtDur(r.duration_s) : 'time n/a'} · ${r.alternatives} route${r.alternatives === 1 ? '' : 's'} found</small>
        <small>${esc(fmtDate(r.created_at))}</small>
      </div>
      <div class="acts"><button type="button" class="btn sm" data-act="reuse" data-id="${r.id}">Reuse</button>${trash('del-history', r.id, 'Remove from history')}</div>
    </div>`).join('')}</div>`
    : '<p class="empty">No routes yet. Routes you calculate in Map Navigation are saved here and stay after you restart the app.</p>';

  $('#favList').innerHTML = state.favourites.length ? `<div class="list">${state.favourites.map((f) => `
    <div class="item">
      <div class="txt"><div class="t">${icon('star')} ${esc(f.name)}</div><small>Saved ${esc(fmtDate(f.created_at))}</small></div>
      <div class="acts">
        <button type="button" class="btn sm" data-act="use-a" data-kind="fav" data-id="${f.id}">Start</button>
        <button type="button" class="btn sm" data-act="use-b" data-kind="fav" data-id="${f.id}">Destination</button>
        ${trash('del-fav', f.id, 'Remove from favourites')}
      </div></div>`).join('')}</div>`
    : '<p class="empty">No favourites yet. Press the ☆ button next to a place in Map Navigation to save it.</p>';

  $('#recentList').innerHTML = state.recents.length ? `<div class="list">${state.recents.map((p, i) => `
    <div class="item">
      <div class="txt"><div class="t">${esc(p.name)}</div></div>
      <div class="acts">
        <button type="button" class="btn sm" data-act="use-a" data-kind="recent" data-id="${i}">Start</button>
        <button type="button" class="btn sm" data-act="use-b" data-kind="recent" data-id="${i}">Destination</button>
      </div></div>`).join('')}</div>`
    : '<p class="empty">Places you search for appear here.</p>';
}

async function onClick(e) {
  const b = e.target.closest('button[data-act]');
  if (!b) return;
  const id = +b.dataset.id;
  try {
    switch (b.dataset.act) {
      case 'reuse': {
        const r = state.history.find((x) => x.id === id);
        if (!r) return;
        emit('reuse-route', {
          origin: { name: r.origin_name, lat: r.origin_lat, lon: r.origin_lon },
          destination: { name: r.dest_name, lat: r.dest_lat, lon: r.dest_lon } });
        break;
      }
      case 'del-history':
        await api(`/api/history/${id}`, { method: 'DELETE' });
        toast('History entry removed.', 'info', 2500);
        emit('history:changed');
        break;
      case 'del-fav':
        await api(`/api/favourites/${id}`, { method: 'DELETE' });
        toast('Favourite removed.', 'info', 2500);
        emit('favourites:changed');
        break;
      case 'use-a': case 'use-b': {
        const src = b.dataset.kind === 'fav' ? state.favourites.find((x) => x.id === id) : state.recents[id];
        if (src) emit('use-place', { kind: b.dataset.act === 'use-a' ? 'a' : 'b', place: { name: src.name, lat: src.lat, lon: src.lon } });
        break;
      }
    }
  } catch (err) {
    toast(err.message, 'bad');
    emit('history:changed');   // the entry may already be gone: refresh the lists
  }
}

export function initHistory() {
  ['#historyList', '#favList', '#recentList'].forEach((s) => $(s).addEventListener('click', onClick));
  $('#clearHistoryBtn').addEventListener('click', async () => {
    if (!(await confirmDialog('Delete your entire route history? Favourites are kept.', 'Delete all'))) return;
    try {
      const d = await api('/api/history', { method: 'DELETE' });
      toast(`Removed ${d.deleted} history entr${d.deleted === 1 ? 'y' : 'ies'}.`, 'info');
      emit('history:changed');
    } catch (err) { toast(err.message, 'bad'); }
  });
  on('personal:updated', render);
  render();
}
