/* Minimal stand-in for Leaflet, used ONLY by the offline browser test (tests/e2e_browser.py).
   It records calls so the test can check that the app drives the map correctly.
   It does not draw anything: real map rendering must be checked manually with internet. */
(function () {
  const calls = [];
  window.__L = { calls, map: null };
  class Bounds { constructor(p) { this.pts = p || []; } extend(o) { this.pts.push(...((o && o.pts) || [o])); return this; } }
  window.L = {
    map() {
      const m = { layers: new Set(), center: null, zoom: null,
        setView(c, z) { m.center = c; m.zoom = z; calls.push(['setView', c, z]); return m; },
        fitBounds() { calls.push(['fitBounds']); return m; },
        invalidateSize() {},
        removeLayer(l) { m.layers.delete(l); calls.push(['removeLayer', l.type]); return m; } };
      window.__L.map = m; return m;
    },
    tileLayer() { return { addTo() { return this; } }; },
    latLngBounds(p) { return new Bounds(p); },
    divIcon(o) { return o; },
    marker(ll, o) {
      const l = { type: 'marker', ll, opts: o,
        addTo(m) { m.layers.add(l); calls.push(['marker', o && o.title]); return l; },
        bindPopup(h) { l.popup = h; return l; }, getLatLng() { return ll; } };
      return l;
    },
    geoJSON(g, o) {
      const l = { type: 'route', geom: g, style: o.style, handlers: {},
        addTo(m) { m.layers.add(l); calls.push(['route']); return l; },
        on(e, f) { l.handlers[e] = f; return l; },
        setStyle(s) { l.style = s; return l; }, bringToFront() { return l; },
        getBounds() { return new Bounds([[0, 0]]); } };
      return l;
    },
  };
})();
