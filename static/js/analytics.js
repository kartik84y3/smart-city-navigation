// Analytics view: every number comes from /api/analytics (real saved data).
import { api } from './api.js';
import { $, esc, fmtDate, fmtKm, on } from './util.js';
import { toast } from './ui.js';

const empty = (msg) => `<p class="empty">${esc(msg)}</p>`;

function hbars(items, fmt = (v) => v) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return items.map((i) => `<div class="hbar"><span class="lbl" title="${esc(i.label)}">${esc(i.label)}</span>
    <span class="track"><span class="fill" style="width:${(i.value / max) * 100}%"></span></span><b>${esc(fmt(i.value))}</b></div>`).join('');
}

function render(a) {
  const stat = (label, value, sub = '') => `<div class="stat"><small>${label}</small><b>${value}</b><small>${sub}</small></div>`;
  $('#statGrid').innerHTML =
    stat('Routes calculated', a.total_routes, a.total_routes ? 'saved in history' : 'none yet') +
    stat('Average distance', a.avg_distance_km != null ? `${a.avg_distance_km} km` : '—', a.avg_distance_km != null ? `from ${a.routes_with_distance} route(s)` : 'not enough data') +
    stat('Average est. time', a.avg_duration_min != null ? `${a.avg_duration_min} min` : '—', 'free-flow estimate') +
    stat('Favourite places', a.favourites_count, a.favourites_count ? esc(a.favourites.map((f) => f.name).slice(0, 2).join(', ')) : 'none yet') +
    stat('Algorithm runs', a.algorithm_runs_total, a.algorithm_runs_total ? 'in the Algorithm Lab' : 'none yet');

  $('#chartDistances').innerHTML = a.distance_series.length
    ? `<div class="vbars">${(() => {
      const max = Math.max(...a.distance_series.map((r) => r.distance_m));
      return a.distance_series.map((r) => `<div class="col" title="${esc(r.origin_name)} → ${esc(r.dest_name)}: ${esc(fmtKm(r.distance_m))}">
        <small>${(r.distance_m / 1000).toFixed(1)}</small><div class="bar" style="height:${Math.max(3, (r.distance_m / max) * 120)}px"></div><small>#${r.id}</small></div>`).join('');
    })()}</div><p class="hint">Distance in km of your last ${a.distance_series.length} route(s), oldest on the left.</p>`
    : empty('No routes yet. Calculate a route in Map Navigation to see distances here.');

  $('#chartLocations').innerHTML = a.top_locations.length
    ? hbars(a.top_locations.map((l) => ({ label: l.name, value: l.count })), (v) => `${v}×`)
    : empty('No searched locations yet.');

  $('#chartAlgos').innerHTML = a.algorithm_stats.length
    ? hbars(a.algorithm_stats.map((s) => ({ label: s.algorithm.toUpperCase(), value: s.runs })), (v) => `${v} run${v === 1 ? '' : 's'}`) +
      `<table class="simple-table"><thead><tr><th>Algorithm</th><th>Avg runtime</th><th>Avg nodes visited</th><th>Avg path cost</th></tr></thead><tbody>${
        a.algorithm_stats.map((s) => `<tr><td>${esc(s.algorithm.toUpperCase())}</td><td>${s.avg_runtime_ms} ms</td><td>${s.avg_visited}</td><td>${s.avg_cost != null ? s.avg_cost + ' km' : '—'}</td></tr>`).join('')}</tbody></table>
      <p class="hint">Runtimes are measured in Python on this computer, so they are tiny for a 9-node graph.</p>`
    : empty('No algorithm runs yet. Open the Algorithm Lab and run Dijkstra, BFS or DFS.');

  $('#recentRoutes').innerHTML = a.recent_routes.length
    ? `<table class="simple-table"><thead><tr><th>Route</th><th>Distance</th><th>When</th></tr></thead><tbody>${
      a.recent_routes.map((r) => `<tr><td>${esc(r.origin_name)} → ${esc(r.dest_name)}</td><td>${r.distance_m != null ? esc(fmtKm(r.distance_m)) : '—'}</td><td>${esc(fmtDate(r.created_at))}</td></tr>`).join('')}</tbody></table>`
    : empty('No recent routes.');
}

export async function loadAnalytics() {
  $('#statGrid').innerHTML = '<div class="skeleton" style="grid-column:1/-1;height:70px"></div>';
  try { render(await api('/api/analytics')); }
  catch (e) { toast(e.message, 'bad'); $('#statGrid').innerHTML = empty(e.message); }
}

export function initAnalytics() {
  on('view:show', (v) => { if (v === 'analytics') loadAnalytics(); });
}
