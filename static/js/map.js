// Real-world map navigation: place search, markers, routes, alternatives, favourites.
import { api, ApiError } from './api.js';
import { $, debounce, emit, esc, fmtDur, fmtKm, icon, on } from './util.js';
import { Assistant, setBusy, showView, toast } from './ui.js';
import { isFavourite, state } from './state.js';

const DEFAULT_CENTER = [30.7046, 76.7179];
const DEFAULT_ZOOM = 10;
const mapOk = typeof window.L !== 'undefined';

let map = null;
let markers = { a: null, b: null };
let routeLayers = [];
let routes = [];
let selected = 0;
let lastSummary = null;
let busy = false;

export const mapAssistant = new Assistant($('#mapAssistant'), {
  intro: 'Calculate a route and I will compare the options for you.',
  chips: [
    { id: 'compare', label: 'Compare routes', disabled: true, onClick: (a) => {
      if (lastSummary) a.push({ title: lastSummary.title, messages: lastSummary.messages, tone: 'ok', key: 'compare' });
    } },
    { id: 'estimates', label: 'About estimates', onClick: (a) => a.push({
      title: 'How accurate are these times?', key: 'estimates', tone: 'warn',
      messages: [
        'Distances come from OpenStreetMap road data. Times are free-flow driving estimates from the public OSRM demo server.',
        'They do NOT include live traffic, traffic lights, roadworks, accidents or road closures, so real trips can take longer.',
        'The public demo servers are shared and can be slow or rate-limited. Try again if a request fails.',
      ] }) },
  ],
});

/* ------------------------------------------------------------------ */
/* Place input with suggestions (combobox)                             */
/* ------------------------------------------------------------------ */
class PlaceInput {
  constructor(kind, { input, list, star }) {
    this.kind = kind; this.input = input; this.list = list; this.star = star;
    this.value = null;      // resolved place {name, lat, lon}
    this.items = [];        // selectable suggestion entries
    this.active = -1;
    this.seq = 0;
    const search = debounce(() => this.search(), 550);
    input.addEventListener('input', () => {
      this.setValue(null);
      const q = input.value.trim();
      if (q.length === 0) return this.showDefaults();
      if (q.length < 3) return this.hide();
      this.showStatus('Searching…');
      search();
    });
    input.addEventListener('focus', () => { if (!input.value.trim()) this.showDefaults(); });
    input.addEventListener('blur', () => setTimeout(() => this.hide(), 150));
    input.addEventListener('keydown', (e) => this.onKey(e));
    list.addEventListener('mousedown', (e) => {
      const li = e.target.closest('li[data-i]');
      if (li) { e.preventDefault(); this.choose(this.items[+li.dataset.i]); }
    });
  }

  setValue(place) {
    this.value = place;
    if (this.onChange) this.onChange(place);
    this.updateStar();
  }
  set(place) { this.seq++; this.input.value = place.name; this.setValue({ name: place.name, lat: place.lat, lon: place.lon }); this.hide(); }
  clear() { this.input.value = ''; this.setValue(null); this.hide(); }
  choose(item) { if (item) this.set(item); }

  updateStar() {
    const fav = !!this.value && isFavourite(this.value.name);
    this.star.setAttribute('aria-pressed', String(fav));
    this.star.title = fav ? 'Remove from favourites' : 'Save to favourites';
  }

  hide() { this.list.hidden = true; this.input.setAttribute('aria-expanded', 'false'); this.items = []; this.active = -1; }
  show(html, passive = false) { this.list.innerHTML = html; this.list.classList.toggle('passive', passive); this.list.hidden = false; this.input.setAttribute('aria-expanded', 'true'); }
  showStatus(msg, bad = false) { this.items = []; this.show(`<li class="status ${bad ? 'bad' : ''}">${esc(msg)}</li>`, true); }

  showDefaults() {
    const favs = state.favourites.slice(0, 5);
    const recents = state.recents.filter((r) => !favs.some((f) => f.name.toLowerCase() === r.name.toLowerCase())).slice(0, 5);
    this.items = [...favs, ...recents];
    if (!this.items.length) return this.hide();
    let html = '', i = 0;
    if (favs.length) html += '<li class="group">Favourites</li>' + favs.map((f) => `<li role="option" data-i="${i++}">${icon('star')}<div>${esc(f.name)}</div></li>`).join('');
    if (recents.length) html += '<li class="group">Recent</li>' + recents.map((r) => `<li role="option" data-i="${i++}">${icon('clock')}<div>${esc(r.name)}</div></li>`).join('');
    this.show(html);
  }

  async search() {
    const q = this.input.value.trim();
    if (q.length < 3) return;
    const mine = ++this.seq;
    try {
      const data = await api(`/api/geocode?q=${encodeURIComponent(q)}`);
      if (mine !== this.seq || this.input.value.trim() !== q) return;   // outdated answer
      if (document.activeElement !== this.input) return this.hide();      // user already moved on
      this.items = data.results.map((r) => ({ name: r.label, lat: r.lat, lon: r.lon, full: r.display_name }));
      if (!this.items.length) return this.showStatus(`No places found for “${q}”. Try adding a city or area name.`);
      this.show(this.items.map((r, i) => `<li role="option" data-i="${i}">${icon('pin')}<div>${esc(r.name)}<small>${esc(r.full)}</small></div></li>`).join(''));
    } catch (e) {
      if (mine === this.seq) this.showStatus(e.message, true);
    }
  }

  onKey(e) {
    const open = !this.list.hidden && this.items.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!open) return;
      e.preventDefault();
      this.active = (this.active + (e.key === 'ArrowDown' ? 1 : -1) + this.items.length) % this.items.length;
      this.list.querySelectorAll('li[data-i]').forEach((li) => {
        const on_ = +li.dataset.i === this.active;
        li.classList.toggle('active', on_);
        if (on_) li.scrollIntoView({ block: 'nearest' });
      });
    } else if (e.key === 'Enter' && open && this.active >= 0) {
      e.preventDefault();
      this.choose(this.items[this.active]);
    } else if (e.key === 'Escape') this.hide();
  }

  /** Make sure a place is selected: use the typed text's best match if needed. */
  async resolve() {
    if (this.value) return this.value;
    const q = this.input.value.trim();
    const label = this.kind === 'a' ? 'starting point' : 'destination';
    if (!q) throw new Error(`Please enter a ${label}.`);
    if (q.length < 2) throw new Error(`The ${label} is too short. Type at least 2 characters.`);
    const data = await api(`/api/geocode?q=${encodeURIComponent(q)}`);
    if (!data.results.length) throw new Error(`Could not find “${q}”. Try a more specific name or add the city.`);
    const r = data.results[0];
    this.set({ name: r.label, lat: r.lat, lon: r.lon });
    return this.value;
  }
}

const origin = new PlaceInput('a', { input: $('#originInput'), list: $('#originList'), star: $('#originFav') });
const dest = new PlaceInput('b', { input: $('#destInput'), list: $('#destList'), star: $('#destFav') });

/* ------------------------------------------------------------------ */
/* Map                                                                 */
/* ------------------------------------------------------------------ */
function initMap() {
  if (!mapOk) {
    $('#map').innerHTML = '<div class="map-fallback"><div><b>The map could not be loaded.</b><br>The Leaflet library comes from the internet. Check your connection and reload the page. The Algorithm Lab still works offline.</div></div>';
    return;
  }
  map = L.map('map', { zoomControl: true }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
}

function pinIcon(letter, cls) {
  return L.divIcon({ className: '', html: `<div class="pin ${cls}">${letter}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] });
}

function setMarker(kind, place) {
  if (!map) return;
  if (markers[kind]) { map.removeLayer(markers[kind]); markers[kind] = null; }
  if (!place) return;
  markers[kind] = L.marker([place.lat, place.lon], { icon: pinIcon(kind.toUpperCase(), kind), title: place.name })
    .addTo(map).bindPopup(`<b>${kind === 'a' ? 'Start' : 'Destination'}</b><br>${esc(place.name)}`);
  if (markers.a && markers.b && !routeLayers.length) {
    map.fitBounds(L.latLngBounds([markers.a.getLatLng(), markers.b.getLatLng()]), { padding: [60, 60] });
  } else if (!routeLayers.length) {
    map.setView([place.lat, place.lon], 13);
  }
}
origin.onChange = (p) => setMarker('a', p);
dest.onChange = (p) => setMarker('b', p);

const ROUTE_STYLE = {
  selected: { color: '#4f8cff', weight: 7, opacity: 0.95 },
  other: { color: '#8a97b8', weight: 5, opacity: 0.75 },
};

function clearRoute() {
  routeLayers.forEach((l) => map && map.removeLayer(l));
  routeLayers = []; routes = []; selected = 0;
  $('#routeInfo').innerHTML = '<h2>Route information</h2><p class="empty">No route yet. Choose a start and destination, then press <b>Find route</b>.</p>';
  hideError();
}

function drawRoutes() {
  if (!map) return;
  routeLayers.forEach((l) => map.removeLayer(l));
  routeLayers = routes.map((r, i) => {
    const layer = L.geoJSON(r.geometry, { style: i === selected ? ROUTE_STYLE.selected : ROUTE_STYLE.other }).addTo(map);
    layer.on('click', () => selectRoute(i));
    return layer;
  });
  routeLayers[selected].bringToFront();
}

function fitRoutes() {
  if (!map || !routeLayers.length) return;
  let b = routeLayers[0].getBounds();
  routeLayers.forEach((l) => b.extend(l.getBounds()));
  map.fitBounds(b, { padding: [40, 40] });
}

function selectRoute(i) {
  selected = i;
  routeLayers.forEach((l, k) => l.setStyle(k === i ? ROUTE_STYLE.selected : ROUTE_STYLE.other));
  if (routeLayers[i]) routeLayers[i].bringToFront();
  renderInfo();
}

function renderInfo() {
  const r = routes[selected];
  const fastest = routes.find((x) => x.is_fastest) || routes[0];
  const cards = routes.map((x, i) => {
    const badges = (x.is_fastest ? '<span class="badge ok">Fastest</span>' : '') + (x.is_shortest ? '<span class="badge info">Shortest</span>' : '');
    return `<button type="button" class="route-card ${i === selected ? 'selected' : ''}" data-i="${i}" aria-pressed="${i === selected}">
      <span class="swatch"></span>
      <span class="meta"><span class="big">Route ${i + 1}${badges}</span><small>${fmtKm(x.distance)} · est. ${fmtDur(x.duration)}</small></span>
    </button>`;
  }).join('');
  const table = routes.length > 1 ? `<table class="simple-table"><thead><tr><th>Route</th><th>Distance</th><th>Est. time</th><th>vs fastest</th></tr></thead><tbody>${routes.map((x, i) => {
    const dd = x.distance - fastest.distance, dt = x.duration - fastest.duration;
    const diff = i === routes.indexOf(fastest) ? '—' : `${dd >= 0 ? '+' : '−'}${fmtKm(Math.abs(dd))}, ${dt >= 0 ? '+' : '−'}${fmtDur(Math.abs(dt))}`;
    return `<tr><td>${i + 1}${i === selected ? ' ✓' : ''}</td><td>${fmtKm(x.distance)}</td><td>${fmtDur(x.duration)}</td><td>${diff}</td></tr>`;
  }).join('')}</tbody></table>` : '';
  $('#routeInfo').innerHTML = `
    <h2>Route information</h2>
    <div class="stats">
      <div class="stat"><small>Distance</small><b>${fmtKm(r.distance)}</b></div>
      <div class="stat"><small>Estimated time</small><b>${fmtDur(r.duration)}</b></div>
      <div class="stat"><small>Routes found</small><b>${routes.length}</b></div>
    </div>
    <div class="route-cards">${cards}</div>${table}
    <p class="hint">${routes.length > 1 ? 'Click a route card or a line on the map to switch. ' : 'The routing service returned one route. '}Times are estimates without live traffic.</p>`;
  $('#routeInfo').querySelectorAll('.route-card').forEach((b) => b.addEventListener('click', () => selectRoute(+b.dataset.i)));
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */
function showError(msg) { const e = $('#routeError'); e.textContent = msg; e.hidden = false; }
function hideError() { $('#routeError').hidden = true; }

async function findRoute() {
  if (busy) return;
  hideError();
  origin.seq++; dest.seq++; origin.hide(); dest.hide();
  const btn = $('#routeBtn');
  busy = true;
  setBusy(btn, true, 'Searching…');
  $('#mapLoading').hidden = !map;
  try {
    const a = await origin.resolve();
    const b = await dest.resolve();
    const data = await api('/api/route', { method: 'POST', body: { origin: a, destination: b } });
    routes = data.routes;
    selected = data.assistant.recommended ?? 0;
    drawRoutes(); fitRoutes(); renderInfo();
    lastSummary = data.assistant;
    mapAssistant.push({ title: data.assistant.title, messages: data.assistant.messages, tone: 'ok', key: 'compare' });
    mapAssistant.setChip('compare', true);
    toast(`Route found: ${fmtKm(routes[selected].distance)}, est. ${fmtDur(routes[selected].duration)}.`, 'ok');
    emit('history:changed');
  } catch (e) {
    const msg = e.message || 'Something went wrong. Please try again.';
    showError(msg);
    toast(msg, 'bad');
    mapAssistant.push({ title: 'Route unavailable', tone: 'bad', key: 'compare', messages: [
      msg,
      e instanceof ApiError && e.status === 503 ? 'This is usually a temporary network or public-server problem. Check your connection and try again in a moment.'
        : 'Try different place names, add the city name, or pick a suggestion from the list.',
    ] });
  } finally {
    busy = false;
    setBusy(btn, false);
    $('#mapLoading').hidden = true;
  }
}

async function toggleFavourite(input) {
  try {
    const place = await input.resolve();
    const fav = state.favourites.find((f) => f.name.toLowerCase() === place.name.toLowerCase());
    if (fav) {
      await api(`/api/favourites/${fav.id}`, { method: 'DELETE' });
      toast(`Removed “${place.name}” from favourites.`, 'info');
    } else {
      await api('/api/favourites', { method: 'POST', body: place });
      toast(`Saved “${place.name}” to favourites.`, 'ok');
    }
    emit('favourites:changed');
  } catch (e) {
    toast(e.message, e.status === 409 ? 'warn' : 'bad');
  }
}

function resetAll() {
  clearRoute();
  origin.clear(); dest.clear();
  setMarker('a', null); setMarker('b', null);
  if (map) map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  toast('Map reset.', 'info', 2000);
}

export function initMapView() {
  initMap();
  $('#routeForm').addEventListener('submit', (e) => { e.preventDefault(); findRoute(); });
  $('#clearRouteBtn').addEventListener('click', () => {
    if (!routes.length) return toast('There is no route to clear.', 'info', 2500);
    clearRoute();
    mapAssistant.setChip('compare', !!lastSummary);
  });
  $('#resetMapBtn').addEventListener('click', resetAll);
  $('#swapBtn').addEventListener('click', () => {
    const a = origin.value, b = dest.value, at = origin.input.value, bt = dest.input.value;
    origin.input.value = bt; dest.input.value = at;
    origin.setValue(b); dest.setValue(a);
    if (routes.length) clearRoute();
  });
  $('#originFav').addEventListener('click', () => toggleFavourite(origin));
  $('#destFav').addEventListener('click', () => toggleFavourite(dest));

  on('personal:updated', () => { origin.updateStar(); dest.updateStar(); });
  on('view:show', (v) => { if (v === 'map' && map) setTimeout(() => map.invalidateSize(), 60); });
  on('use-place', ({ kind, place }) => {
    (kind === 'a' ? origin : dest).set(place);
    showView('map');
    toast(`“${place.name}” set as ${kind === 'a' ? 'starting point' : 'destination'}.`, 'ok', 2500);
  });
  on('reuse-route', ({ origin: o, destination: d }) => {
    origin.set(o); dest.set(d);
    showView('map');
    if (routes.length) clearRoute();
    findRoute();
  });
}
