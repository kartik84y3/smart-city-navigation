// Entry point: wires the views together.
import { initAnalytics } from './analytics.js';
import { initHistory } from './history.js';
import { initLab } from './lab.js';
import { initMapView } from './map.js';
import { loadPersonal } from './state.js';
import { initNav, initTheme, showView } from './ui.js';

initTheme();
initNav();
initHistory();
initAnalytics();
initMapView();
await initLab();
await loadPersonal();
showView(location.hash.slice(1) || 'map');
