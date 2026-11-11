// Algorithm Lab: Dijkstra / BFS / DFS on the sample graph, step playback and road closures.
import { api } from './api.js';
import { $, $$, esc } from './util.js';
import { Assistant, setBusy, toast } from './ui.js';

let graph = null;          // {nodes, edges, closed, stats}
let algo = 'dijkstra';
let result = null;         // latest algorithm result
let reroute = null;        // {before, after} shown after a closure
let index = 0;             // number of steps applied
let timer = null;
let working = false;

const keyOf = (a, b) => [a, b].sort().join('|');
const NODE_R = 24;

export const labAssistant = new Assistant($('#labAssistant'), {
  intro: 'Run an algorithm or close a road and I will explain what changed.',
  chips: [{
    id: 'status', label: 'Explain graph & alternatives',
    onClick: async (a) => {
      try {
        const d = await api(`/api/assistant/status?start=${encodeURIComponent($('#startSel').value)}&end=${encodeURIComponent($('#endSel').value)}`);
        a.push({ title: d.title, messages: d.messages, tone: d.messages[0].startsWith('No route') ? 'bad' : 'ok', key: 'status' });
      } catch (e) { toast(e.message, 'bad'); }
    },
  }],
});

/* ------------------------------------------------------------------ */
/* Loading the graph                                                    */
/* ------------------------------------------------------------------ */
async function loadGraph() {
  graph = await api('/api/graph');
  const keepS = $('#startSel').value || 'University';
  const keepE = $('#endSel').value || 'Airport';
  for (const sel of [$('#startSel'), $('#endSel')]) {
    sel.innerHTML = graph.nodes.map((n) => `<option value="${esc(n.id)}">${esc(n.id)}</option>`).join('');
  }
  const ids = graph.nodes.map((n) => n.id);
  $('#startSel').value = ids.includes(keepS) ? keepS : ids[0];
  $('#endSel').value = ids.includes(keepE) ? keepE : ids[ids.length - 1];
  renderRoads();
  drawGraph();
}

function renderRoads() {
  const s = graph.stats;
  $('#graphStats').textContent = `${s.vertices} locations · ${s.open_edges} of ${s.edges} roads open · ${s.components} connected part${s.components === 1 ? '' : 's'}`;
  $('#roadList').innerHTML = graph.edges.map((e) => `
    <div class="road ${e.closed ? 'closed' : ''}">
      <div>${esc(e.from)} ↔ ${esc(e.to)}<small>${e.distance} km · ${e.closed ? 'Closed' : 'Open'}</small></div>
      <button type="button" class="btn sm ${e.closed ? '' : 'danger'}" data-from="${esc(e.from)}" data-to="${esc(e.to)}"
        aria-label="${e.closed ? 'Reopen' : 'Close'} road ${esc(e.from)} to ${esc(e.to)}">${e.closed ? 'Reopen' : 'Close'}</button>
    </div>`).join('');
  $('#reopenAll').disabled = graph.stats.closed_edges === 0;
}

/* ------------------------------------------------------------------ */
/* Drawing                                                              */
/* ------------------------------------------------------------------ */
/** Work out how every node/edge should look after `index` steps. */
function computeViz() {
  const viz = { node: {}, val: {}, edge: {}, caption: '' };
  const r = result;
  if (!r) return viz;
  const steps = r.steps;
  const last = index > 0 ? steps[index - 1] : null;
  const done = index >= steps.length;

  if (r.algorithm === 'dijkstra') {
    const dist = {}, prev = {}, settled = [];
    if (index > 0) dist[r.start] = 0;
    for (let i = 0; i < index; i++) {
      const s = steps[i];
      settled.push(s.node);
      dist[s.node] = s.distance;
      s.relaxed.forEach((x) => { if (x.improved) { dist[x.to] = x.candidate; prev[x.to] = s.node; } });
    }
    settled.forEach((n) => { viz.node[n] = 'visited'; });
    if (last) {
      last.queue.forEach((q) => { viz.node[q.node] = 'frontier'; });
      viz.node[last.node] = 'current';
      last.relaxed.filter((x) => x.improved).forEach((x) => { viz.edge[keyOf(last.node, x.to)] = 'relaxed'; });
    }
    settled.forEach((n) => { if (prev[n]) viz.edge[keyOf(prev[n], n)] = viz.edge[keyOf(prev[n], n)] || 'tree'; });
    graph.nodes.forEach((n) => {
      if (index === 0) return;
      viz.val[n.id] = dist[n.id] === undefined ? '∞' : dist[n.id];
    });
    if (done && r.reachable) {
      r.path.forEach((n) => { viz.node[n] = 'path'; });
      r.path.slice(1).forEach((n, i) => { viz.edge[keyOf(r.path[i], n)] = 'path'; });
    }
    viz.caption = index === 0
      ? `Ready. Distances start at ∞ except ${r.start} = 0. Press Play or Step.`
      : last.description;
    if (done) viz.caption += r.reachable ? ` Done: shortest path costs ${r.distance} km.` : ' Done: the destination cannot be reached.';
  } else {
    const seen = [];
    for (let i = 0; i < index; i++) {
      const s = steps[i];
      if (r.algorithm === 'bfs') {
        seen.push(s.node);
        s.discovered.forEach((d) => { viz.edge[keyOf(s.node, d)] = 'tree'; });
      } else if (s.event === 'visit') {
        seen.push(s.node);
        if (s.from) viz.edge[keyOf(s.from, s.node)] = 'tree';
      }
    }
    seen.forEach((n, i) => { viz.node[n] = 'visited'; viz.val[n] = i + 1; });
    if (last) {
      (r.algorithm === 'bfs' ? last.queue : last.stack).forEach((n) => { if (viz.node[n] !== 'current') viz.node[n] = 'frontier'; });
      const cur = r.algorithm === 'dfs' && last.event === 'backtrack' ? last.from : last.node;
      if (cur) viz.node[cur] = 'current';
    }
    viz.caption = index === 0 ? `Ready. Traversal starts at ${r.start}. Press Play or Step.` : last.description;
    if (done) viz.caption += ` Done: ${r.visited_count} location(s) reached.`;
  }
  return viz;
}

function drawGraph() {
  if (!graph) return;
  const viz = computeViz();
  const pos = Object.fromEntries(graph.nodes.map((n) => [n.id, n]));
  const edges = graph.edges.map((e) => {
    const a = pos[e.from], b = pos[e.to];
    const state = e.closed ? 'closed' : (viz.edge[keyOf(e.from, e.to)] || '');
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const label = e.closed ? `✕ ${e.distance}` : e.distance;
    return `<g class="edge ${state}" data-from="${esc(e.from)}" data-to="${esc(e.to)}">
      <title>${esc(e.from)} ↔ ${esc(e.to)}: ${e.distance} km (${e.closed ? 'closed' : 'open'}). Click to ${e.closed ? 'reopen' : 'close'}.</title>
      <line class="base" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>
      <line class="hit" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>
      <rect class="wpill" x="${mx - (e.closed ? 22 : 15)}" y="${my - 12}" width="${e.closed ? 44 : 30}" height="24" rx="9"/>
      <text x="${mx}" y="${my}">${label}</text></g>`;
  }).join('');
  const nodes = graph.nodes.map((n) => {
    const cls = viz.node[n.id] || '';
    const val = viz.val[n.id] !== undefined ? viz.val[n.id] : '';
    const tag = result && n.id === result.start ? 'START' : (result && result.algorithm === 'dijkstra' && n.id === result.end ? 'END' : '');
    return `<g class="node ${cls}" data-id="${esc(n.id)}">
      <circle cx="${n.x}" cy="${n.y}" r="${NODE_R}"/>
      <text class="val" x="${n.x}" y="${n.y}">${esc(val)}</text>
      <text class="name" x="${n.x}" y="${n.y + NODE_R + 17}">${esc(n.id)}</text>
      ${tag ? `<text class="tag" x="${n.x}" y="${n.y - NODE_R - 7}">${tag}</text>` : ''}</g>`;
  }).join('');
  $('#graph').innerHTML = edges + nodes;
  $('#stepCaption').textContent = result ? viz.caption : 'Run an algorithm to see it step by step.';
  updatePlayer();
  updateResultHighlights();
}

/* ------------------------------------------------------------------ */
/* Result panel                                                         */
/* ------------------------------------------------------------------ */
function chips(list, cls = '') {
  return list.map((n, i) => `${i ? '<span class="arrow">→</span>' : ''}<span class="n ${cls}" data-n="${i}">${esc(n)}</span>`).join('');
}

function renderResult() {
  const r = result;
  const box = $('#labResult');
  if (!r) { box.innerHTML = '<h2>Algorithm analysis</h2><p class="empty">Choose an algorithm and press <b>Run algorithm</b>.</p>'; return; }
  const V = r.vertices;
  let stats, body = '';
  if (r.algorithm === 'dijkstra') {
    stats = `
      <div class="stat ${r.reachable ? 'ok' : 'bad'}"><small>Path cost</small><b>${r.reachable ? r.distance + ' km' : 'No route'}</b></div>
      <div class="stat"><small>Hops (roads used)</small><b>${r.reachable ? r.path.length - 1 : '—'}</b></div>
      <div class="stat"><small>Nodes visited</small><b>${r.visited_count} / ${V}</b></div>
      <div class="stat"><small>Edge relaxations</small><b>${r.relaxations}</b></div>`;
    body = (r.reachable ? `<h3>Selected shortest path</h3><div class="order" id="pathChips">${chips(r.path, 'path')}</div>`
      : `<div class="explain">${esc(r.message)} ${esc(r.end)} cannot be reached from ${esc(r.start)} using the roads that are currently open.</div>`)
      + `<h3>Order in which nodes were settled (visited)</h3><div class="order" id="orderChips">${chips(r.order)}</div>`;
  } else {
    const depth = r.algorithm === 'dfs' ? Math.max(...r.steps.map((s) => s.depth)) : r.levels.length - 1;
    stats = `
      <div class="stat ok"><small>Nodes reached</small><b>${r.visited_count} / ${V}</b></div>
      <div class="stat"><small>${r.algorithm === 'bfs' ? 'Levels (depth)' : 'Max depth'}</small><b>${depth}</b></div>
      <div class="stat ${r.unreachable.length ? 'bad' : ''}"><small>Unreachable</small><b>${r.unreachable.length}</b></div>`;
    body = `<h3>Traversal order</h3><div class="order" id="orderChips">${chips(r.order)}</div>`;
    if (r.algorithm === 'bfs') body += `<h3>Levels</h3><div class="explain">${r.levels.map((l, i) => `<b>Level ${i}:</b> ${l.map(esc).join(', ')}`).join('<br>')}</div>`;
    if (r.unreachable.length) body += `<div class="explain">Not reachable from ${esc(r.start)} right now: <b>${r.unreachable.map(esc).join(', ')}</b> (the graph is disconnected because of closed roads).</div>`;
  }
  stats += `<div class="stat"><small>Runtime</small><b>${r.runtime_ms} ms</b></div>`;
  let cmp = '';
  if (reroute) {
    const b = reroute.before;
    if (r.algorithm === 'dijkstra') {
      cmp = `<h3>Route change after the road update</h3><div class="compare">
        <div class="before"><small>Before</small>${b.reachable ? `${b.path.map(esc).join(' → ')}<br><b>${b.distance} km</b>` : 'No route'}</div>
        <div class="after"><small>After</small>${r.reachable ? `${r.path.map(esc).join(' → ')}<br><b>${r.distance} km</b>${b.reachable ? ` (${r.distance - b.distance >= 0 ? '+' : ''}${+(r.distance - b.distance).toFixed(2)} km)` : ''}` : 'No route'}</div></div>`;
    } else {
      cmp = `<h3>Change after the road update</h3><div class="compare">
        <div class="before"><small>Before</small><b>${b.visited_count}</b> nodes reached</div>
        <div class="after"><small>After</small><b>${r.visited_count}</b> nodes reached</div></div>`;
    }
  }
  const c = r.complexity;
  box.innerHTML = `
    <h2>Algorithm analysis · ${esc(r.label)}</h2>
    <div class="stats">${stats}</div>
    ${cmp}${body}
    <table class="simple-table"><tbody>
      <tr><th>Time complexity</th><td><b>${esc(c.time)}</b></td></tr>
      <tr><th>Space complexity</th><td><b>${esc(c.space)}</b></td></tr>
      <tr><th>This run</th><td>V = ${V}, E (open roads) = ${r.open_edges}</td></tr></tbody></table>
    <p class="hint">${esc(c.note)}</p>
    <div class="explain"><b>In simple words:</b> ${esc(r.explanation)}</div>
    <h3>Step-by-step log <span class="tiny">(click a step to jump to it)</span></h3>
    <ol class="steplog" id="stepLog">${r.steps.map((s, i) => `<li data-i="${i + 1}">${i + 1}. ${esc(s.description)}</li>`).join('')}</ol>`;
  updateResultHighlights();
}

/** Cheap per-tick updates: dim not-yet-visited chips and mark the current log line. */
function updateResultHighlights() {
  if (!result) return;
  const seenNodes = new Set();
  for (let i = 0; i < index; i++) {
    const s = result.steps[i];
    if (result.algorithm !== 'dfs' || s.event === 'visit') seenNodes.add(s.node);
  }
  $$('#orderChips .n').forEach((el) => el.classList.toggle('dim', index < result.steps.length && !seenNodes.has(el.textContent)));
  $$('#stepLog li').forEach((li, i) => {
    li.classList.toggle('done', i < index);
    li.classList.toggle('now', i === index - 1);
  });
  // scroll only inside the log box (scrollIntoView would also scroll the whole page away from the graph)
  const log = $('#stepLog'), now = $('#stepLog li.now');
  if (log && now && (now.offsetTop < log.scrollTop || now.offsetTop + now.offsetHeight > log.scrollTop + log.clientHeight)) {
    log.scrollTop = now.offsetTop - log.clientHeight / 2;
  }
}

/* ------------------------------------------------------------------ */
/* Playback                                                             */
/* ------------------------------------------------------------------ */
function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  $('#pPlay').querySelector('span').textContent = 'Play';
  $('#pPlay').querySelector('use').setAttribute('href', '#i-play');
}
function play() {
  if (!result) return;
  if (index >= result.steps.length) index = 0;
  $('#pPlay').querySelector('span').textContent = 'Pause';
  $('#pPlay').querySelector('use').setAttribute('href', '#i-pause');
  const tick = () => {
    if (index >= result.steps.length) { stop(); drawGraph(); return; }
    index++; drawGraph();
    if (index >= result.steps.length) stop();
  };
  tick();
  if (timer !== null || index < result.steps.length) timer = setInterval(tick, +$('#pSpeed').value);
}
function updatePlayer() {
  const has = !!result;
  const n = has ? result.steps.length : 0;
  $('#pReset').disabled = !has || index === 0;
  $('#pBack').disabled = !has || index === 0;
  $('#pStep').disabled = !has || index >= n;
  $('#pEnd').disabled = !has || index >= n;
  $('#pPlay').disabled = !has;
}
function go(i) { stop(); index = Math.max(0, Math.min(result.steps.length, i)); drawGraph(); }

/* ------------------------------------------------------------------ */
/* Actions                                                              */
/* ------------------------------------------------------------------ */
function setAlgo(a) {
  algo = a;
  $$('#algoSeg button').forEach((b) => { const on_ = b.dataset.algo === a; b.classList.toggle('active', on_); b.setAttribute('aria-checked', String(on_)); });
  $('#endWrap').hidden = a !== 'dijkstra';
  labAssistant.setChip('status', a === 'dijkstra');
}

function assistantFor(res) {
  if (res.assistant) {
    const bad = res.assistant.messages[0].startsWith('No route');
    labAssistant.push({ title: res.assistant.title, messages: res.assistant.messages, tone: bad ? 'bad' : 'ok', key: 'status' });
  }
}

async function runAlgorithm() {
  if (working) return;
  const start = $('#startSel').value, end = $('#endSel').value;
  if (!start || (algo === 'dijkstra' && !end)) return toast('Please choose a start' + (algo === 'dijkstra' ? ' and destination.' : '.'), 'warn');
  working = true; stop();
  const btn = $('#runBtn');
  setBusy(btn, true, 'Running…');
  try {
    result = await api('/api/algorithm', { method: 'POST', body: { algorithm: algo, start, end } });
    reroute = null; index = 0;
    renderResult(); drawGraph(); assistantFor(result);
    play();
  } catch (e) {
    toast(e.message, 'bad');
  } finally {
    working = false; setBusy(btn, false);
  }
}

async function setRoad(from, to) {
  if (working) return;
  const edge = graph.edges.find((e) => e.from === from && e.to === to);
  if (!edge) return;
  working = true; stop();
  try {
    const d = await api('/api/road', { method: 'POST', body: {
      from, to, closed: !edge.closed, algorithm: algo, start: $('#startSel').value, end: $('#endSel').value } });
    graph = d.graph;
    result = d.result;
    reroute = { before: d.before };
    index = result.steps.length;      // show the new final state straight away
    renderRoads(); renderResult(); drawGraph();
    const bad = d.result.algorithm === 'dijkstra' && !d.result.reachable;
    labAssistant.push({ title: d.assistant.title, messages: d.assistant.messages, tone: bad ? 'bad' : 'ok', key: 'status' });
    toast(`${from} ↔ ${to} ${d.status}.${bad ? ' The destination is now unreachable.' : ''}`, bad ? 'warn' : 'info');
  } catch (e) {
    toast(e.message, 'bad');
  } finally {
    working = false;
  }
}

async function reopenAll() {
  if (working || !graph.stats.closed_edges) return;
  working = true; stop();
  try {
    const d = await api('/api/roads/reset', { method: 'POST' });
    graph = d.graph; reroute = null;
    renderRoads();
    if (result) {
      result = await api('/api/algorithm', { method: 'POST', body: { algorithm: algo, start: $('#startSel').value, end: $('#endSel').value } });
      index = result.steps.length; renderResult(); assistantFor(result);
    }
    drawGraph();
    toast('All roads reopened.', 'ok');
  } catch (e) { toast(e.message, 'bad'); } finally { working = false; }
}

export async function initLab() {
  $$('#algoSeg button').forEach((b) => b.addEventListener('click', () => { setAlgo(b.dataset.algo); }));
  $('#runBtn').addEventListener('click', runAlgorithm);
  $('#pPlay').addEventListener('click', () => (timer ? stop() : play()));
  $('#pStep').addEventListener('click', () => go(index + 1));
  $('#pBack').addEventListener('click', () => go(index - 1));
  $('#pReset').addEventListener('click', () => go(0));
  $('#pEnd').addEventListener('click', () => go(result.steps.length));
  $('#pSpeed').addEventListener('change', () => { if (timer) { stop(); play(); } });
  $('#reopenAll').addEventListener('click', reopenAll);
  $('#roadList').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-from]');
    if (b) setRoad(b.dataset.from, b.dataset.to);
  });
  $('#graph').addEventListener('click', (e) => {
    const g = e.target.closest('.edge');
    if (g) setRoad(g.dataset.from, g.dataset.to);
  });
  $('#labResult').addEventListener('click', (e) => {
    const li = e.target.closest('#stepLog li');
    if (li) go(+li.dataset.i);
  });
  setAlgo('dijkstra');
  try { await loadGraph(); }
  catch (e) { toast(e.message, 'bad'); $('#roadList').innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
}
