"""The demo console served at `GET /`.

One self-contained HTML document with no build step and no external
dependencies beyond a webfont, so it works from a cold clone on a venue
network. Everything it shows comes from the API response: the answer, the
capability that produced it, the regions drawn over the image, and the
execution trace.
"""

from __future__ import annotations

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SatQuery AI</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet" />
<style>
  :root {
    --void:   #070A0E;
    --panel:  #0E141B;
    --raised: #141C25;
    --rule:   #232F3C;
    --ink:    #DCE4EC;
    --muted:  #6F8598;
    --accent: #E8A33D;
    --cyan:   #4CC5C0;
    --good:   #5CB87A;
    --bad:    #DB5A5A;
    --radius: 3px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--void); color: var(--ink); }
  body {
    font-family: 'IBM Plex Sans', system-ui, -apple-system, sans-serif;
    font-weight: 300;
    line-height: 1.6;
    min-height: 100vh;
  }
  .mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }

  .wrap { max-width: 1440px; margin: 0 auto; padding: 28px 22px 64px; }

  header { border-bottom: 1px solid var(--rule); padding-bottom: 20px; margin-bottom: 24px; }
  .brand {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 26px; font-weight: 500; letter-spacing: 0.12em; margin: 0;
  }
  .brand span { color: var(--accent); }
  .tagline { color: var(--muted); font-size: 14px; margin: 6px 0 0; max-width: 68ch; }
  .statusline {
    display: flex; flex-wrap: wrap; gap: 20px; margin-top: 14px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--muted);
  }
  .statusline b { color: var(--ink); font-weight: 500; }
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
  .dot.ok { background: var(--good); }
  .dot.warn { background: var(--accent); }
  .dot.bad { background: var(--bad); }

  .grid { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 20px; align-items: start; }
  @media (max-width: 1040px) { .grid { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel); border: 1px solid var(--rule); border-radius: var(--radius);
  }
  .card > h2 {
    margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--rule);
    font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 500;
    letter-spacing: 0.06em;
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
  }
  .card > .body { padding: 16px; }

  label { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 11px;
          color: var(--muted); margin-bottom: 6px; }
  textarea, select, input[type=text] {
    width: 100%; background: var(--void); color: var(--ink);
    border: 1px solid var(--rule); border-radius: var(--radius);
    padding: 9px 10px; font: inherit; font-size: 14px; outline: none;
  }
  textarea { resize: vertical; min-height: 78px; }
  textarea:focus, select:focus, input:focus { border-color: var(--accent); }
  select { font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
  .field + .field { margin-top: 16px; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

  .drop {
    border: 1px dashed var(--rule); border-radius: var(--radius);
    padding: 22px 14px; text-align: center; cursor: pointer;
    color: var(--muted); font-size: 13px; transition: border-color .15s, color .15s;
  }
  .drop:hover, .drop.hot { border-color: var(--accent); color: var(--ink); }
  .drop strong { color: var(--ink); font-weight: 500; display: block; }

  ul.files { list-style: none; margin: 10px 0 0; padding: 0; }
  ul.files li {
    display: flex; align-items: center; gap: 8px;
    border: 1px solid var(--rule); border-radius: var(--radius);
    padding: 6px 8px; margin-bottom: 6px;
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  }
  ul.files li .name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  ul.files li button {
    background: none; border: none; color: var(--muted); cursor: pointer; font: inherit;
  }
  ul.files li button:hover { color: var(--bad); }

  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip {
    background: none; border: 1px solid var(--rule); border-radius: var(--radius);
    color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 10.5px;
    padding: 4px 7px; cursor: pointer; text-align: left;
  }
  .chip:hover { border-color: var(--cyan); color: var(--cyan); }

  button.run {
    width: 100%; margin-top: 18px; padding: 11px;
    background: rgba(232,163,61,.12); border: 1px solid var(--accent);
    color: var(--accent); border-radius: var(--radius); cursor: pointer;
    font-family: 'IBM Plex Mono', monospace; font-size: 13px; letter-spacing: .04em;
  }
  button.run:hover:not(:disabled) { background: rgba(232,163,61,.22); }
  button.run:disabled { border-color: var(--rule); color: var(--muted); cursor: not-allowed; background: none; }

  .stack { display: flex; flex-direction: column; gap: 20px; }
  .split { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 20px; }
  @media (max-width: 1040px) { .split { grid-template-columns: 1fr; } }

  .badge {
    font-family: 'IBM Plex Mono', monospace; font-size: 10.5px;
    border: 1px solid var(--rule); border-radius: var(--radius);
    padding: 2px 7px; color: var(--muted);
  }
  .badge.ok { border-color: var(--good); color: var(--good); }
  .badge.bad { border-color: var(--bad); color: var(--bad); }
  .badge.accent { border-color: var(--accent); color: var(--accent); }

  .answer { font-size: 15px; white-space: pre-wrap; max-width: 76ch; }
  .answer.placeholder { color: var(--muted); font-size: 14px; }

  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px;
             margin-bottom: 16px; }
  .metrics dt { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--muted); }
  .metrics dd { margin: 2px 0 0; font-family: 'IBM Plex Mono', monospace; font-size: 13.5px; }

  .viewer { position: relative; display: inline-block; max-width: 100%; }
  .viewer img { display: block; max-width: 100%; border: 1px solid var(--rule); border-radius: var(--radius); }
  .viewer canvas { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .thumbs { display: flex; gap: 8px; margin-bottom: 12px; }
  .thumbs button {
    background: none; border: 1px solid var(--rule); border-radius: var(--radius);
    color: var(--muted); font-family: 'IBM Plex Mono', monospace; font-size: 10.5px;
    padding: 4px 8px; cursor: pointer;
  }
  .thumbs button[aria-pressed=true] { border-color: var(--accent); color: var(--accent); }

  table.regions { width: 100%; border-collapse: collapse; margin-top: 14px;
                  font-family: 'IBM Plex Mono', monospace; font-size: 11px; }
  table.regions th { text-align: left; color: var(--muted); font-weight: 400;
                     border-bottom: 1px solid var(--rule); padding: 5px 6px; }
  table.regions td { padding: 5px 6px; border-bottom: 1px solid rgba(35,47,60,.5); }

  pre.trace {
    margin: 0; background: var(--void); border-radius: var(--radius);
    padding: 12px; font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    line-height: 1.75; overflow-x: auto; max-height: 340px; overflow-y: auto;
    white-space: pre-wrap; word-break: break-word;
  }
  .t-ok { color: var(--good); } .t-bad { color: var(--bad); }
  .t-mut { color: var(--muted); } .t-cy { color: var(--cyan); } .t-ac { color: var(--accent); }

  details.raw { margin-top: 14px; }
  details.raw summary { cursor: pointer; font-family: 'IBM Plex Mono', monospace;
                        font-size: 11px; color: var(--muted); }
  details.raw pre { margin-top: 10px; background: var(--void); padding: 12px;
                    border-radius: var(--radius); font-size: 11px; max-height: 320px;
                    overflow: auto; font-family: 'IBM Plex Mono', monospace; }

  .notice { border-left: 2px solid var(--accent); background: rgba(232,163,61,.06);
            padding: 10px 12px; font-size: 13px; margin-bottom: 14px; }
  .notice.bad { border-color: var(--bad); background: rgba(219,90,90,.07); }
  .notice ul { margin: 8px 0 0; padding-left: 18px; color: var(--muted); font-size: 12.5px; }

  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <h1 class="brand">SatQuery<span> AI</span></h1>
    <p class="tagline">
      Ask a satellite or aerial image a question in plain language. The router picks a
      vision capability, runs it against the actual pixels, and shows you which one answered.
    </p>
    <div class="statusline" id="statusline">
      <span><span class="dot warn"></span>Checking backends&hellip;</span>
    </div>
  </header>

  <div class="grid">

    <!-- ------------------------------- controls ------------------------------- -->
    <section class="card">
      <h2>Query</h2>
      <div class="body">

        <div class="field">
          <label for="files">Imagery</label>
          <div class="drop" id="drop" tabindex="0" role="button">
            <strong>Drop images or browse</strong>
            <span>Two images unlock change detection</span>
          </div>
          <input id="files" type="file" multiple accept="image/*" style="display:none" />
          <ul class="files" id="filelist"></ul>
        </div>

        <div class="field">
          <label for="query">Question</label>
          <textarea id="query" placeholder="Describe this scene in detail"></textarea>
          <div class="chips" id="examples"></div>
        </div>

        <div class="field row">
          <div>
            <label for="modality">Modality hint</label>
            <select id="modality">
              <option value="">Detect from pixels</option>
              <option value="OPTICAL">Optical</option>
              <option value="SAR">SAR</option>
            </select>
          </div>
          <div>
            <label for="tool">Capability</label>
            <select id="tool">
              <option value="">Route automatically</option>
            </select>
          </div>
        </div>

        <button class="run" id="run" type="button">Run query</button>
      </div>
    </section>

    <!-- ------------------------------- results -------------------------------- -->
    <div class="stack">

      <section class="card">
        <h2>Answer <span class="badge" id="intentBadge">idle</span></h2>
        <div class="body">
          <div id="notices"></div>
          <dl class="metrics" id="metrics" style="display:none"></dl>
          <div class="answer placeholder" id="answer">
            Attach an image and ask a question. Nothing here is generated without looking
            at the pixels first.
          </div>
        </div>
      </section>

      <div class="split">
        <section class="card">
          <h2>Regions <span class="badge" id="regionBadge">none</span></h2>
          <div class="body">
            <div class="thumbs" id="thumbs"></div>
            <div class="viewer" id="viewer">
              <img id="preview" alt="" style="display:none" />
              <canvas id="overlay"></canvas>
            </div>
            <div id="regionTable"></div>
          </div>
        </section>

        <section class="card">
          <h2>Execution trace <span class="badge" id="latencyBadge">&mdash;</span></h2>
          <div class="body">
            <pre class="trace" id="trace"><span class="t-mut">No query has run yet.</span></pre>
            <details class="raw">
              <summary>Raw JSON response</summary>
              <pre id="raw">{}</pre>
            </details>
          </div>
        </section>
      </div>

    </div>
  </div>
</div>

<script>
'use strict';

const state = { files: [], response: null, activeImage: 0, objectUrls: [] };

const EXAMPLES = [
  'Describe this scene in detail',
  'What land use category is this?',
  'Where are the buildings?',
  'How many ships are visible?',
  'Are there any aircraft in this image?',
  'Is this optical or SAR imagery?',
  'Compare these two images and tell me what changed'
];

const $ = (id) => document.getElementById(id);

/* ----------------------------------------------------------------- setup */

function buildExamples() {
  const host = $('examples');
  EXAMPLES.forEach((text) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.textContent = text.length > 32 ? text.slice(0, 30) + '\u2026' : text;
    b.title = text;
    b.addEventListener('click', () => { $('query').value = text; });
    host.appendChild(b);
  });
}

async function loadStatus() {
  const line = $('statusline');
  try {
    const [healthRes, capRes] = await Promise.all([
      fetch('/api/v1/health'),
      fetch('/api/v1/capabilities')
    ]);
    const health = await healthRes.json();
    const caps = await capRes.json();

    const ready = health.ready;
    const strong = health.backends && health.backends.rsvlm && health.backends.rsvlm.available;
    const planner = health.backends && health.backends.planner_llm && health.backends.planner_llm.available;

    line.innerHTML = '';
    addStatus(line, ready ? 'ok' : 'bad', 'Vision', ready ? (strong ? 'RS VLM + CLIP' : 'BLIP + CLIP') : 'not configured');
    addStatus(line, 'ok', 'Device', health.device);
    addStatus(line, planner ? 'ok' : 'warn', 'Planner', planner ? health.backends.planner_llm.model : 'rule routing');
    addStatus(line, 'ok', 'Version', health.version);

    if (!ready && health.setup_actions && health.setup_actions.length) {
      showNotice('SatQuery has no vision backend yet, so it will refuse to answer rather than guess.',
                 health.setup_actions, true);
    }

    const sel = $('tool');
    caps.forEach((cap) => {
      const opt = document.createElement('option');
      opt.value = cap.tool;
      opt.textContent = cap.tool.replace(/_/g, ' ') + (cap.available ? '' : ' (unavailable)');
      opt.disabled = !cap.available;
      opt.title = cap.description;
      sel.appendChild(opt);
    });
  } catch (err) {
    line.innerHTML = '';
    addStatus(line, 'bad', 'API', 'unreachable');
  }
}

function addStatus(host, tone, label, value) {
  const span = document.createElement('span');
  span.innerHTML = '<span class="dot ' + tone + '"></span>' + label + ' <b></b>';
  span.querySelector('b').textContent = value;
  host.appendChild(span);
}

/* ------------------------------------------------------------------ files */

function renderFiles() {
  const host = $('filelist');
  host.innerHTML = '';
  state.files.forEach((file, index) => {
    const li = document.createElement('li');
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = 'T' + (index + 1) + '  ' + file.name;
    const size = document.createElement('span');
    size.style.color = 'var(--muted)';
    size.textContent = formatBytes(file.size);
    const drop = document.createElement('button');
    drop.type = 'button';
    drop.textContent = '\u00d7';
    drop.setAttribute('aria-label', 'Remove ' + file.name);
    drop.addEventListener('click', () => { state.files.splice(index, 1); renderFiles(); });
    li.append(name, size, drop);
    host.appendChild(li);
  });
}

function formatBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(2) + ' MB';
}

$('files').addEventListener('change', (e) => {
  Array.from(e.target.files).forEach((f) => state.files.push(f));
  e.target.value = '';
  renderFiles();
});
$('drop').addEventListener('click', () => $('files').click());
$('drop').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('files').click(); }
});
['dragenter', 'dragover'].forEach((ev) =>
  $('drop').addEventListener(ev, (e) => { e.preventDefault(); $('drop').classList.add('hot'); }));
['dragleave', 'drop'].forEach((ev) =>
  $('drop').addEventListener(ev, (e) => { e.preventDefault(); $('drop').classList.remove('hot'); }));
$('drop').addEventListener('drop', (e) => {
  Array.from(e.dataTransfer.files).forEach((f) => {
    if (f.type.startsWith('image/')) state.files.push(f);
  });
  renderFiles();
});

/* ------------------------------------------------------------------ notices */

function clearNotices() { $('notices').innerHTML = ''; }

function showNotice(text, bullets, bad) {
  const div = document.createElement('div');
  div.className = 'notice' + (bad ? ' bad' : '');
  const p = document.createElement('div');
  p.textContent = text;
  div.appendChild(p);
  if (bullets && bullets.length) {
    const ul = document.createElement('ul');
    bullets.forEach((b) => { const li = document.createElement('li'); li.textContent = b; ul.appendChild(li); });
    div.appendChild(ul);
  }
  $('notices').appendChild(div);
}

/* ------------------------------------------------------------------ render */

function renderResponse(data) {
  state.response = data;
  state.activeImage = 0;

  const badge = $('intentBadge');
  badge.textContent = data.intent.toLowerCase().replace(/_/g, ' ');
  badge.className = 'badge ok';

  $('latencyBadge').textContent = data.latency_ms.toFixed(0) + ' ms';
  $('latencyBadge').className = 'badge accent';

  const metrics = $('metrics');
  metrics.style.display = 'grid';
  metrics.innerHTML = '';
  const primary = data.results[0] || {};
  addMetric(metrics, 'Capability', (data.tools_used[0] || '\u2014').replace(/_/g, ' '));
  addMetric(metrics, 'Backend', data.backend);
  addMetric(metrics, 'Router', data.plan.router);
  addMetric(metrics, 'Confidence', data.confidence == null ? '\u2014' : data.confidence.toFixed(3));
  addMetric(metrics, 'Model', shorten(primary.model || '\u2014'));
  addMetric(metrics, 'Modality', (data.images[0] || {}).modality || '\u2014');

  const answer = $('answer');
  answer.className = 'answer';
  answer.textContent = data.answer;

  if (data.warnings && data.warnings.length) showNotice('Notes on this run:', data.warnings, false);

  renderImages(data);
  renderTrace(data);
  $('raw').textContent = JSON.stringify(data, (key, value) => {
    if (key === 'response_map' || key === 'map') return '[matrix elided]';
    return value;
  }, 2);
}

function addMetric(host, label, value) {
  const dt = document.createElement('dt'); dt.textContent = label;
  const dd = document.createElement('dd'); dd.textContent = value;
  const box = document.createElement('div'); box.append(dt, dd);
  host.appendChild(box);
}

function shorten(text) {
  const s = String(text);
  return s.length > 22 ? '\u2026' + s.slice(-21) : s;
}

function renderImages(data) {
  const thumbs = $('thumbs');
  thumbs.innerHTML = '';
  if (state.files.length > 1) {
    state.files.forEach((file, index) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = 'T' + (index + 1);
      b.setAttribute('aria-pressed', String(index === state.activeImage));
      b.addEventListener('click', () => { state.activeImage = index; renderImages(data); });
      thumbs.appendChild(b);
    });
  }

  const file = state.files[state.activeImage];
  const img = $('preview');
  if (!file) { img.style.display = 'none'; return; }

  state.objectUrls.forEach(URL.revokeObjectURL);
  const url = URL.createObjectURL(file);
  state.objectUrls = [url];
  img.onload = () => drawRegions(data);
  img.src = url;
  img.style.display = 'block';
}

function drawRegions(data) {
  const img = $('preview');
  const canvas = $('overlay');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const regions = (data.results[0] && data.results[0].regions) || [];
  $('regionBadge').textContent = regions.length
    ? regions.length + ' region' + (regions.length === 1 ? '' : 's')
    : 'none';
  $('regionBadge').className = 'badge' + (regions.length ? ' ok' : '');

  const scale = Math.max(canvas.width / 600, 1);
  regions.forEach((region, index) => {
    const x = region.box.x0 * canvas.width;
    const y = region.box.y0 * canvas.height;
    const w = (region.box.x1 - region.box.x0) * canvas.width;
    const h = (region.box.y1 - region.box.y0) * canvas.height;
    const strong = region.score >= 0.6;
    ctx.strokeStyle = strong ? '#E8A33D' : '#4CC5C0';
    ctx.lineWidth = 2 * scale;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = strong ? 'rgba(232,163,61,.12)' : 'rgba(76,197,192,.12)';
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = strong ? '#E8A33D' : '#4CC5C0';
    ctx.font = (12 * scale) + 'px IBM Plex Mono, monospace';
    ctx.fillText(region.region_id + '  ' + region.score.toFixed(2), x + 3 * scale,
                 Math.max(y - 4 * scale, 14 * scale));
  });

  renderRegionTable(regions);
}

function renderRegionTable(regions) {
  const host = $('regionTable');
  host.innerHTML = '';
  if (!regions.length) return;

  const table = document.createElement('table');
  table.className = 'regions';
  table.innerHTML = '<thead><tr><th>id</th><th>label</th><th>score</th>' +
                    '<th>box [x0 y0 x1 y1]</th><th>placement</th></tr></thead>';
  const tbody = document.createElement('tbody');
  regions.forEach((r) => {
    const tr = document.createElement('tr');
    const box = [r.box.x0, r.box.y0, r.box.x1, r.box.y1].map((v) => v.toFixed(3)).join('  ');
    [r.region_id, r.label, r.score.toFixed(3), box, r.placement].forEach((value) => {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  host.appendChild(table);
}

function renderTrace(data) {
  const host = $('trace');
  host.innerHTML = '';
  const line = (text, cls) => {
    const div = document.createElement('div');
    if (cls) div.className = cls;
    div.textContent = text;
    host.appendChild(div);
  };

  line('request ' + data.request_id + '   ' + data.timestamp_utc, 't-mut');
  line('query    ' + data.query, 't-cy');
  line('');
  line('plan  ' + data.intent + '  via ' + data.plan.router +
       '  (confidence ' + data.plan.confidence.toFixed(2) + ')', 't-ac');
  line('      ' + data.plan.rationale, 't-mut');
  if (data.plan.target) line('      target: ' + data.plan.target, 't-mut');
  line('');

  data.trace.forEach((step, index) => {
    const last = index === data.trace.length - 1;
    const marker = last ? '\u2514 ' : '\u251c ';
    const cls = step.status === 'ok' ? 't-ok' : (step.status === 'failed' ? 't-bad' : 't-mut');
    line(marker + pad(step.step, 30) + pad(step.latency_ms.toFixed(1) + ' ms', 12) + step.status, cls);
    if (step.detail) line('   ' + step.detail, 't-mut');
    if (step.model) line('   model: ' + step.model, 't-mut');
  });

  line('');
  line('total ' + data.latency_ms.toFixed(1) + ' ms', 't-ac');
}

function pad(text, width) {
  const s = String(text);
  return s.length >= width ? s.slice(0, width - 1) + ' ' : s + ' '.repeat(width - s.length);
}

function renderError(status, body) {
  const badge = $('intentBadge');
  badge.textContent = 'error ' + status;
  badge.className = 'badge bad';
  $('metrics').style.display = 'none';

  const answer = $('answer');
  answer.className = 'answer';
  answer.textContent = body.detail || 'The request failed.';

  showNotice(body.error ? body.error.replace(/_/g, ' ') : 'Request failed',
             body.remediation || [], true);

  $('raw').textContent = JSON.stringify(body, null, 2);
  $('trace').innerHTML = '<span class="t-bad">' + (body.error || 'error') + '</span>';
  $('regionBadge').textContent = 'none';
}

/* ------------------------------------------------------------------ submit */

async function run() {
  const query = $('query').value.trim();
  if (!query) { showNotice('Enter a question first.', [], true); return; }

  const button = $('run');
  button.disabled = true;
  button.textContent = 'Running\u2026';
  clearNotices();
  $('trace').innerHTML = '<span class="t-mut">dispatching to POST /api/v1/query\u2026</span>';

  const form = new FormData();
  form.append('query', query);
  form.append('include_trace', 'true');
  if ($('modality').value) form.append('modality_hint', $('modality').value);
  if ($('tool').value) form.append('force_tool', $('tool').value);
  state.files.forEach((file) => form.append('files', file, file.name));

  try {
    const res = await fetch('/api/v1/query', { method: 'POST', body: form });
    const body = await res.json();
    if (!res.ok) { renderError(res.status, body); } else { renderResponse(body); }
  } catch (err) {
    renderError('network', { error: 'unreachable', detail: 'The console could not reach the API.',
                             remediation: ['Check the server is running and reload the page.'] });
  } finally {
    button.disabled = false;
    button.textContent = 'Run query';
  }
}

$('run').addEventListener('click', run);
$('query').addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') run();
});

buildExamples();
renderFiles();
loadStatus();
</script>
</body>
</html>
"""
