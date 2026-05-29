#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from result_dedup import pick_plateau_representatives, record_key


SCRIPT_DIR = Path(__file__).resolve().parent
PARAM_KEY_FIELDS = ("n", "q", "ell", "m", "sigma", "alpha_h")
GOAL_LO_OFFSET = 5
GOAL_HI_OFFSET = 30
SIGMA_AT_LEAST_ONE_TAG = "sigma>=1"

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Param Search Results</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; margin: 16px; color: #222; }
h2 { margin: 0 0 12px; }
.controls { display: flex; flex-wrap: wrap; gap: 24px; margin-bottom: 12px; padding: 12px; background: #f5f5f7; border: 1px solid #e1e1e6; border-radius: 6px; }
.controls section { display: flex; flex-direction: column; gap: 6px; }
.controls strong { font-size: 12px; color: #555; text-transform: uppercase; letter-spacing: 0.04em; }
.controls label { font-size: 13px; margin-right: 10px; cursor: pointer; }
.tags-group { display: flex; flex-direction: column; gap: 6px; max-width: 760px; }
.tags-row { display: flex; gap: 4px 10px; }
.tags-row-primary { flex-wrap: nowrap; }
.tags-row-secondary { flex-wrap: wrap; }
.mode-row { font-size: 13px; }
.summary { margin: 8px 0 12px; font-size: 13px; color: #444; }
.summary button { font-size: 12px; margin-left: 8px; padding: 2px 8px; cursor: pointer; }
.pager { margin: 0 0 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 13px; color: #444; }
.pager button { font-size: 12px; padding: 2px 8px; cursor: pointer; }
.pager select { font-size: 12px; padding: 2px 4px; }
.load-status { margin: 0 0 12px; font-size: 13px; color: #555; }
.load-status.error { color: #b00; }
.update-banner { display: none; margin: 0 0 12px; padding: 10px 12px; background: #fff4d6; border: 1px solid #e3c268; border-radius: 6px; color: #6b4e00; align-items: center; gap: 8px; flex-wrap: wrap; }
.update-banner.visible { display: flex; }
.update-banner button { font-size: 12px; padding: 2px 8px; cursor: pointer; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; font-size: 12px; width: 100%; }
th, td { border: 1px solid #d0d0d4; padding: 4px 8px; text-align: right; white-space: nowrap; }
th { background: #eee; position: sticky; top: 0; cursor: pointer; user-select: none; font-weight: 600; }
th.group { background: #dde; cursor: default; font-size: 11px; text-align: center; letter-spacing: 0.04em; }
th.sort-asc::after  { content: " \25B2"; font-size: 9px; }
th.sort-desc::after { content: " \25BC"; font-size: 9px; }
.sep-l { border-left: 2px solid #888; }
body.hide-derived .col-derived { display: none; }
th.group.col-derived { cursor: pointer; }
th.group.col-derived::before { content: "\25BE "; font-size: 10px; }
tr.failed td { color: #888; background: #fafafa; }
tr.selected td { background: #fff5cc !important; }
td.tags   { text-align: left; font-size: 11px; color: #444; max-width: 360px; white-space: normal; }
td.reason { text-align: left; font-style: italic; color: #b00; max-width: 360px; white-space: normal; }
th.sel, td.sel { width: 24px; text-align: center; cursor: default; }
th.sel { background: #dde; }
#copy-status { margin-left: 8px; font-size: 12px; color: #060; }
</style>
</head>
<body>
<h2>Param Search Results</h2>

<div class="controls">
  <section>
    <strong>Columns</strong>
    <label><input type="checkbox" id="show-derived"> show derived columns</label>
  </section>
  <section>
    <strong>Tags</strong>
    <div class="mode-row">Match:
      <label><input type="radio" name="match" value="AND" checked> ALL of selected</label>
      <label><input type="radio" name="match" value="OR"> ANY of selected</label>
    </div>
    <div id="tag-filter" class="tags-group">
      <div id="tag-filter-primary" class="tags-row tags-row-primary"></div>
      <div id="tag-filter-secondary" class="tags-row tags-row-secondary"></div>
    </div>
  </section>
</div>

<div class="summary">
  Showing <strong id="page-count">0</strong> / <strong id="filtered-count">0</strong> filtered / <strong id="total-count">0</strong> total
  <button id="clear-tags">clear tag selection</button>
  &nbsp;|&nbsp;
  Selected: <strong id="selected-count">0</strong>
  <button id="select-all-visible">select all page</button>
  <button id="select-none">deselect all</button>
  <button id="copy-selected">copy selected JSON</button>
  <span id="copy-status"></span>
</div>

<div class="pager">
  <span>Page <strong id="page-label">1 / 1</strong></span>
  <button id="prev-page">prev</button>
  <button id="next-page">next</button>
  <label>Rows per page
    <select id="page-size">
      <option value="50">50</option>
      <option value="100" selected>100</option>
      <option value="250">250</option>
      <option value="500">500</option>
      <option value="1000">1000</option>
    </select>
  </label>
</div>

<div id="load-status" class="load-status">Loading data...</div>
<div id="update-banner" class="update-banner">
  <strong>Data updated on server.</strong>
  Refresh to load the latest results.
  <button id="refresh-page">refresh now</button>
</div>

<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th class="group"></th>
      <th class="group" colspan="7">inputs</th>
      <th class="group sep-l col-derived" colspan="9" id="derived-group">derived</th>
      <th class="group sep-l" colspan="6">outputs</th>
      <th class="group sep-l">meta</th>
    </tr>
    <tr>
      <th class="sel" title="select / deselect all visible"><input type="checkbox" id="header-sel"></th>
      <th data-sort="target_security">target</th>
      <th data-sort="n">n</th>
      <th data-sort="q">q</th>
      <th data-sort="ell">ell</th>
      <th data-sort="m">m</th>
      <th data-sort="sigma">sigma</th>
      <th data-sort="alpha_h">alpha_h</th>
      <th data-sort="bk" class="sep-l col-derived">bk</th>
      <th data-sort="alpha_1" class="col-derived">alpha_1</th>
      <th data-sort="r" class="col-derived">r</th>
      <th data-sort="mu_s" class="col-derived">mu_s</th>
      <th data-sort="v_s" class="col-derived">v_s</th>
      <th data-sort="bs" class="col-derived">bs</th>
      <th data-sort="bv" class="col-derived">bv</th>
      <th data-sort="sigma_h" class="col-derived">sigma_h</th>
      <th data-sort="a_h" class="col-derived">a_h</th>
      <th data-sort="LWE_security_bit" class="sep-l">LWE</th>
      <th data-sort="SIS_UF_security_bit">SIS_UF</th>
      <th data-sort="SIS_sUF_security_bit">SIS_sUF</th>
      <th data-sort="PkBytes">PkBytes</th>
      <th data-sort="SignBytes">SignBytes</th>
      <th data-sort="CombinedBytes">CombinedBytes</th>
      <th class="sep-l">tags / reason</th>
    </tr>
  </thead>
  <tbody id="rows"></tbody>
</table>
</div>

<script>
const dataUrl = "__DATA_URL__";
let records = [];
const selected = new Set();
let sortKey = null, sortAsc = true;
let currentPage = 1;
let pageSize = 100;
let filteredRowsCache = [];
const UPDATE_CHECK_INTERVAL_MS = 20 * 60 * 1000;
const UPDATE_CHECK_LABEL = '20 minutes';
const tagFilterDiv = document.getElementById('tag-filter');
const tagFilterPrimaryDiv = document.getElementById('tag-filter-primary');
const tagFilterSecondaryDiv = document.getElementById('tag-filter-secondary');
const loadStatus = document.getElementById('load-status');
const updateBanner = document.getElementById('update-banner');
const refreshPageBtn = document.getElementById('refresh-page');
let currentDataVersion = null;
let updateCheckMode = 'headers';
let updateAvailable = false;
let lastUpdateCheckAt = 0;

function isSecurityThresholdTag(t) {
  return /^(lwe|sis_uf|sis_suf)>\d+$/.test(t);
}

// Sort tags so target_security=* comes first, then rough, then sigma>=1, then lwe>*, sis_uf>*, sis_suf>*
function tagSortKey(t) {
  if (t.startsWith('target_security=')) return [0, parseInt(t.split('=')[1], 10)];
  if (t === 'rough') return [1, 0];
  if (t === 'sigma>=1') return [2, 1];
  if (isSecurityThresholdTag(t)) {
    const order = { 'lwe': 3, 'sis_uf': 4, 'sis_suf': 5 };
    const [prefix, thr] = t.split('>');
    return [order[prefix] ?? 99, parseInt(thr, 10) || 0];
  }
  return [99, t];
}

function populateTagFilters() {
  const allTags = new Set();
  for (const r of records) {
    for (const t of (r.tags || [])) allTags.add(t);
  }
  const sortedTags = [...allTags].sort((a, b) => {
    const [pa, va] = tagSortKey(a), [pb, vb] = tagSortKey(b);
    if (pa !== pb) return pa - pb;
    if (typeof va === 'number' && typeof vb === 'number') return va - vb;
    return String(va).localeCompare(String(vb));
  });
  tagFilterPrimaryDiv.innerHTML = '';
  tagFilterSecondaryDiv.innerHTML = '';
  for (const t of sortedTags) {
    const safe = t.replace(/[^a-zA-Z0-9]/g, '_');
    const isPrimaryTag = t.startsWith('target_security=') || t === 'rough';
    const isDefaultChecked = t === 'rough';
    const targetDiv = isPrimaryTag ? tagFilterPrimaryDiv : tagFilterSecondaryDiv;
    targetDiv.insertAdjacentHTML('beforeend',
      `<label><input type="checkbox" data-tag="${t}" id="tag-${safe}"${isDefaultChecked ? ' checked' : ''}> ${t}</label>`);
  }
}

function clearSecurityThresholdSelections() {
  document.querySelectorAll('#tag-filter input:checked').forEach(cb => {
    if (isSecurityThresholdTag(cb.dataset.tag)) cb.checked = false;
  });
}

function freshDataUrl() {
  const sep = dataUrl.includes('?') ? '&' : '?';
  return `${dataUrl}${sep}_ts=${Date.now()}`;
}

function responseVersion(response) {
  const parts = [
    response.headers.get('etag'),
    response.headers.get('last-modified'),
    response.headers.get('content-length'),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join('|') : null;
}

function hashText(text) {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function computeDataVersion(response, text) {
  return responseVersion(response) || `${text.length}:${hashText(text)}`;
}

function showUpdateBanner() {
  updateBanner.classList.add('visible');
}

document.querySelectorAll('th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const k = th.dataset.sort;
    if (sortKey === k) sortAsc = !sortAsc;
    else { sortKey = k; sortAsc = true; }
    document.querySelectorAll('th[data-sort]').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
    th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
    currentPage = 1;
    render();
  });
});

document.getElementById('clear-tags').addEventListener('click', () => {
  document.querySelectorAll('#tag-filter input:checked').forEach(i => i.checked = false);
  currentPage = 1;
  render();
});

document.getElementById('prev-page').addEventListener('click', () => {
  if (currentPage > 1) {
    currentPage -= 1;
    render();
  }
});

document.getElementById('next-page').addEventListener('click', () => {
  const totalPages = Math.max(1, Math.ceil(filteredRowsCache.length / pageSize));
  if (currentPage < totalPages) {
    currentPage += 1;
    render();
  }
});

document.getElementById('page-size').addEventListener('change', e => {
  pageSize = parseInt(e.target.value, 10);
  currentPage = 1;
  render();
});

function visibleIndices() {
  return [...document.querySelectorAll('#rows input.row-sel')].map(cb => parseInt(cb.dataset.idx, 10));
}

function updateSelectedCount() {
  document.getElementById('selected-count').textContent = selected.size;
  const vis = visibleIndices();
  const allOn = vis.length > 0 && vis.every(i => selected.has(i));
  const someOn = vis.some(i => selected.has(i));
  const hdr = document.getElementById('header-sel');
  hdr.checked = allOn;
  hdr.indeterminate = !allOn && someOn;
}

document.getElementById('select-all-visible').addEventListener('click', () => {
  for (const i of visibleIndices()) selected.add(i);
  document.querySelectorAll('#rows input.row-sel').forEach(cb => cb.checked = true);
  document.querySelectorAll('#rows tr').forEach(tr => tr.classList.add('selected'));
  updateSelectedCount();
});

document.getElementById('select-none').addEventListener('click', () => {
  selected.clear();
  document.querySelectorAll('#rows input.row-sel').forEach(cb => cb.checked = false);
  document.querySelectorAll('#rows tr.selected').forEach(tr => tr.classList.remove('selected'));
  updateSelectedCount();
});

document.getElementById('header-sel').addEventListener('change', e => {
  if (e.target.checked) document.getElementById('select-all-visible').click();
  else document.getElementById('select-none').click();
});

refreshPageBtn.addEventListener('click', () => {
  window.location.reload();
});

async function copySelected() {
  const status = document.getElementById('copy-status');
  if (selected.size === 0) {
    status.textContent = 'nothing selected';
    status.style.color = '#b00';
    setTimeout(() => { status.textContent = ''; status.style.color = '#060'; }, 1500);
    return;
  }
  const items = [...selected].sort((a, b) => a - b).map(i => {
    const { _idx, ...rest } = records[i];
    return rest;
  });
  const text = JSON.stringify(items, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = `copied ${items.length} record(s)`;
  } catch (err) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); status.textContent = `copied ${items.length} (fallback)`; }
    catch (e2) { status.textContent = 'copy failed; see console'; console.log(text); }
    ta.remove();
  }
  setTimeout(() => { status.textContent = ''; }, 2500);
}

document.getElementById('copy-selected').addEventListener('click', copySelected);

function updateTagVisibility() {
  const checkedTargets = [...document.querySelectorAll('#tag-filter input[data-tag^="target_security="]:checked')]
    .map(i => parseInt(i.dataset.tag.split('=')[1], 10));
  const relevantThrs = new Set();
  for (const ts of checkedTargets) {
    relevantThrs.add(ts);
    relevantThrs.add(ts + 5);
  }
  for (const label of document.querySelectorAll('#tag-filter label')) {
    const cb = label.querySelector('input');
    const t = cb.dataset.tag;
    let visible = true;
    if (isSecurityThresholdTag(t) && checkedTargets.length > 0) {
      const thr = parseInt(t.split('>')[1], 10);
      visible = relevantThrs.has(thr);
    }
    label.style.display = visible ? '' : 'none';
    if (!visible && cb.checked) cb.checked = false;
  }
}

const showDerivedCb = document.getElementById('show-derived');
function applyDerivedVisibility() {
  document.body.classList.toggle('hide-derived', !showDerivedCb.checked);
}
showDerivedCb.addEventListener('change', applyDerivedVisibility);
document.getElementById('derived-group').addEventListener('click', () => {
  showDerivedCb.checked = !showDerivedCb.checked;
  applyDerivedVisibility();
});
applyDerivedVisibility();

function fmtNum(x, digits = 1) {
  if (x === null || x === undefined || x === '') return '';
  if (typeof x !== 'number') return String(x);
  if (Number.isInteger(x)) return String(x);
  return x.toFixed(digits);
}

function getField(r, k) {
  if (r.inputs && k in r.inputs) return r.inputs[k];
  if (r.outputs && k in r.outputs) return r.outputs[k];
  return null;
}

function computeVisibleRows() {
  const checkedTags = [...document.querySelectorAll('#tag-filter input:checked')].map(i => i.dataset.tag);
  const mode = document.querySelector('input[name=match]:checked').value;

  let rows = records.filter(r => {
    if (checkedTags.length === 0) return true;
    return mode === 'AND'
      ? checkedTags.every(t => r._tagsSet.has(t))
      : checkedTags.some(t => r._tagsSet.has(t));
  });

  if (sortKey) {
    rows.sort((a, b) => {
      const av = getField(a, sortKey), bv = getField(b, sortKey);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      const cmp = (typeof av === 'number' && typeof bv === 'number') ? av - bv : String(av).localeCompare(String(bv));
      return cmp * (sortAsc ? 1 : -1);
    });
  }

  return rows;
}

function render() {
  filteredRowsCache = computeVisibleRows();
  const totalPages = Math.max(1, Math.ceil(filteredRowsCache.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * pageSize;
  const rows = filteredRowsCache.slice(start, start + pageSize);

  const html = rows.map(r => {
    const i = r.inputs || {}, o = r.outputs || {};
    const failed = !r.outputs;
    const tail = failed
      ? `<td class="reason sep-l">${(r.reason || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}</td>`
      : `<td class="tags sep-l">${(r.tags || []).join(', ')}</td>`;
    const isSelected = selected.has(r._idx);
    const rowClasses = [failed ? 'failed' : 'ok'];
    if (isSelected) rowClasses.push('selected');
    return `<tr class="${rowClasses.join(' ')}">
      <td class="sel"><input type="checkbox" class="row-sel" data-idx="${r._idx}"${isSelected ? ' checked' : ''}></td>
      <td>${i.target_security ?? ''}</td>
      <td>${i.n ?? ''}</td>
      <td>${i.q ?? ''}</td>
      <td>${i.ell ?? ''}</td>
      <td>${i.m ?? ''}</td>
      <td>${i.sigma ?? ''}</td>
      <td>${i.alpha_h ?? ''}</td>
      <td class="sep-l col-derived">${fmtNum(i.bk, 2)}</td>
      <td class="col-derived">${fmtNum(i.alpha_1, 0)}</td>
      <td class="col-derived">${fmtNum(i.r, 0)}</td>
      <td class="col-derived">${fmtNum(i.mu_s, 2)}</td>
      <td class="col-derived">${fmtNum(i.v_s, 2)}</td>
      <td class="col-derived">${fmtNum(i.bs, 2)}</td>
      <td class="col-derived">${fmtNum(i.bv, 2)}</td>
      <td class="col-derived">${fmtNum(i.sigma_h, 3)}</td>
      <td class="col-derived">${fmtNum(i.a_h, 3)}</td>
      <td class="sep-l">${fmtNum(o.LWE_security_bit)}</td>
      <td>${fmtNum(o.SIS_UF_security_bit)}</td>
      <td>${fmtNum(o.SIS_sUF_security_bit)}</td>
      <td>${fmtNum(o.PkBytes, 0)}</td>
      <td>${fmtNum(o.SignBytes, 0)}</td>
      <td>${fmtNum(o.CombinedBytes, 0)}</td>
      ${tail}
    </tr>`;
  }).join('');

  document.getElementById('rows').innerHTML = html;
  document.getElementById('page-count').textContent = rows.length;
  document.getElementById('filtered-count').textContent = filteredRowsCache.length;
  document.getElementById('total-count').textContent = records.length;
  document.getElementById('page-label').textContent = `${currentPage} / ${totalPages}`;
  document.getElementById('prev-page').disabled = currentPage <= 1;
  document.getElementById('next-page').disabled = currentPage >= totalPages;
  updateSelectedCount();
}

document.addEventListener('change', e => {
  if (e.target.matches('input.row-sel')) {
    const idx = parseInt(e.target.dataset.idx, 10);
    if (e.target.checked) selected.add(idx);
    else selected.delete(idx);
    const tr = e.target.closest('tr');
    if (tr) tr.classList.toggle('selected', e.target.checked);
    updateSelectedCount();
    return;
  }
  if (e.target.id === 'header-sel' || e.target.id === 'show-derived') return;
  if (e.target.matches('#tag-filter input[data-tag^="target_security="]')) {
    if (e.target.checked) {
      for (const cb of document.querySelectorAll('#tag-filter input[data-tag^="target_security="]')) {
        if (cb !== e.target) cb.checked = false;
      }
    }
    clearSecurityThresholdSelections();
    updateTagVisibility();
  }
  if (e.target.matches('input[type=checkbox], input[name=match]')) {
    currentPage = 1;
    render();
  }
});

async function init() {
  loadStatus.textContent = 'Loading data...';
  loadStatus.classList.remove('error');
  try {
    const response = await fetch(freshDataUrl(), { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    currentDataVersion = computeDataVersion(response, text);
    lastUpdateCheckAt = Date.now();
    updateCheckMode = responseVersion(response) ? 'headers' : 'body';
    records = JSON.parse(text);
    records.forEach((r, i) => {
      r._idx = i;
      r._tagsSet = new Set(r.tags || []);
    });
    filteredRowsCache = records;
    populateTagFilters();
    updateTagVisibility();
    render();
    loadStatus.textContent = `Loaded ${records.length} record(s) from ${dataUrl}. Auto-checking for updates every ${UPDATE_CHECK_LABEL}.`;
  } catch (err) {
    console.error(err);
    loadStatus.textContent = `Failed to load ${dataUrl}: ${err}`;
    loadStatus.classList.add('error');
  }
}

async function checkForUpdates() {
  if (updateAvailable || !currentDataVersion) return;
  const now = Date.now();
  if (now - lastUpdateCheckAt < UPDATE_CHECK_INTERVAL_MS) return;
  lastUpdateCheckAt = now;
  try {
    if (updateCheckMode === 'headers') {
      const response = await fetch(freshDataUrl(), { method: 'HEAD', cache: 'no-store' });
      if (!response.ok) return;
      const nextVersion = responseVersion(response);
      if (nextVersion) {
        if (nextVersion !== currentDataVersion) {
          updateAvailable = true;
          showUpdateBanner();
        }
        return;
      }
      updateCheckMode = 'body';
    }

    const response = await fetch(freshDataUrl(), { cache: 'no-store' });
    if (!response.ok) return;
    const text = await response.text();
    const nextVersion = computeDataVersion(response, text);
    if (nextVersion !== currentDataVersion) {
      updateAvailable = true;
      showUpdateBanner();
    }
  } catch (err) {
    console.error('Update check failed:', err);
  }
}

init();
setInterval(checkForUpdates, UPDATE_CHECK_INTERVAL_MS);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) checkForUpdates();
});
</script>
</body>
</html>
"""


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def dedupe_exact_records(rows: list[dict]) -> list[dict]:
  seen_keys: set[tuple] = set()
  unique_rows: list[dict] = []
  for record in rows:
    key = record_key(record)
    if key is not None:
      if key in seen_keys:
        continue
      seen_keys.add(key)
    unique_rows.append(record)
  return unique_rows


def sort_records(rows: list[dict]) -> list[dict]:
  return sorted(
    rows,
    key=lambda record: (
      (record.get("inputs") or {}).get("target_security", math.inf),
      (record.get("inputs") or {}).get("n", math.inf),
      (record.get("inputs") or {}).get("ell", math.inf),
      (record.get("inputs") or {}).get("m", math.inf),
      (record.get("inputs") or {}).get("q", math.inf),
      (record.get("inputs") or {}).get("sigma", math.inf),
      (record.get("inputs") or {}).get("alpha_h", math.inf),
    ),
  )


def in_goal_band(value, lo, hi) -> bool:
  return value is not None and lo <= value <= hi


def detect_goals(record: dict) -> list[str]:
  inputs = record.get("inputs")
  outputs = record.get("outputs")
  if not isinstance(inputs, dict) or not isinstance(outputs, dict):
    return []

  target_security = inputs.get("target_security")
  if target_security is None:
    return []

  lo = target_security + GOAL_LO_OFFSET
  hi = target_security + GOAL_HI_OFFSET
  lwe = outputs.get("LWE_security_bit")
  sis_uf = outputs.get("SIS_UF_security_bit")
  sis_suf = outputs.get("SIS_sUF_security_bit")

  goals: list[str] = []
  if in_goal_band(lwe, lo, hi) and in_goal_band(sis_uf, lo, hi):
    goals.append("UF")
  if in_goal_band(lwe, lo, hi) and in_goal_band(sis_suf, lo, hi):
    goals.append("sUF")
  return goals


def normalize_json_value(value):
  if isinstance(value, float):
    if math.isfinite(value):
      return value
    if math.isinf(value):
      return "Infinity" if value > 0 else "-Infinity"
    return "NaN"
  if isinstance(value, dict):
    return {key: normalize_json_value(inner) for key, inner in value.items()}
  if isinstance(value, list):
    return [normalize_json_value(item) for item in value]
  return value


def enrich_html_tags(record: dict) -> dict:
  enriched_record = dict(record)
  tags = list(enriched_record.get("tags") or [])
  inputs = enriched_record.get("inputs")
  sigma = inputs.get("sigma") if isinstance(inputs, dict) else None

  if isinstance(sigma, (int, float)) and sigma >= 1 and SIGMA_AT_LEAST_ONE_TAG not in tags:
    tags.append(SIGMA_AT_LEAST_ONE_TAG)

  if tags:
    enriched_record["tags"] = tags

  return enriched_record


def render_html_rows(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data_path = out_path.with_suffix(".data.json")
    html_rows = [enrich_html_tags(record) for record in pick_plateau_representatives(rows)]
    sanitized_rows = normalize_json_value(html_rows)
    data_path.write_text(json.dumps(sanitized_rows, ensure_ascii=False), encoding="utf-8")

    html = HTML_TEMPLATE.replace("__DATA_URL__", data_path.name)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {len(sanitized_rows)} records -> {out_path} (data: {data_path.name})")


def render_html(in_path: Path, out_path: Path) -> None:
    render_html_rows(load_jsonl(in_path), out_path)


def should_render_report(jsonl_path: Path) -> bool:
  name = jsonl_path.name
  if name in {"param_all.jsonl", "param_ideal.jsonl"}:
    return False
  return "iter" not in jsonl_path.stem


def update_param_all(results_dir: Path, source_rows: dict[Path, list[dict]] | None = None) -> tuple[Path, int]:
  param_all_path = results_dir / "param_all.jsonl"
  source_iter = source_rows.items() if source_rows is not None else (
    (jsonl_path, load_jsonl(jsonl_path))
    for jsonl_path in sorted(results_dir.glob("*.jsonl"))
  )

  all_records: list[dict] = []
  for jsonl_path, rows in source_iter:
    if jsonl_path.name in {"param_all.jsonl", "param_ideal.jsonl"}:
      continue
    all_records.extend(rows)

  exact_unique = dedupe_exact_records(all_records)
  collapsed = sort_records(pick_plateau_representatives(exact_unique))

  with param_all_path.open("w", encoding="utf-8") as out_file:
    for record in collapsed:
      out_file.write(json.dumps(normalize_json_value(record), ensure_ascii=False) + "\n")

  return param_all_path, len(collapsed)


def update_param_ideal(results_dir: Path, source_rows: dict[Path, list[dict]] | None = None) -> tuple[Path, int]:
  param_ideal_path = results_dir / "param_ideal.jsonl"
  source_iter = source_rows.items() if source_rows is not None else (
    (jsonl_path, load_jsonl(jsonl_path))
    for jsonl_path in sorted(results_dir.glob("*.jsonl"))
  )

  seen: dict[tuple, dict] = {}
  for jsonl_path, rows in source_iter:
    if jsonl_path.name in {"param_all.jsonl", "param_ideal.jsonl"}:
      continue
    for record in rows:
      goals = detect_goals(record)
      if not goals:
        continue
      key = record_key(record)
      if key is None:
        continue
      if key in seen:
        merged_goals = set(seen[key].get("goals", []))
        merged_goals.update(goals)
        seen[key]["goals"] = sorted(merged_goals)
        continue
      enriched_record = dict(record)
      enriched_record["goals"] = goals
      enriched_record["source"] = jsonl_path.name
      seen[key] = enriched_record

  collapsed = sort_records(pick_plateau_representatives(list(seen.values())))

  with param_ideal_path.open("w", encoding="utf-8") as out_file:
    for record in collapsed:
      out_file.write(json.dumps(normalize_json_value(record), ensure_ascii=False) + "\n")

  return param_ideal_path, len(collapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render param search jsonl files into filterable HTML reports.")
    parser.add_argument(
        "--in",
        dest="inp",
        default="results",
        help="input jsonl file or directory (relative to script dir if not absolute)",
    )
    parser.add_argument(
        "--out",
        help="output html path for single-file mode, or output directory for directory mode",
    )
    args = parser.parse_args()

    in_path = Path(args.inp)
    if not in_path.is_absolute():
        in_path = SCRIPT_DIR / in_path

    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    if in_path.is_dir():
        out_dir = Path(args.out) if args.out else in_path
        if not out_dir.is_absolute():
            out_dir = SCRIPT_DIR / out_dir

        jsonl_files = sorted(in_path.glob("*.jsonl"))
        if not jsonl_files:
            raise SystemExit(f"no jsonl files found in: {in_path}")

        source_rows = {
          jsonl_path: load_jsonl(jsonl_path)
          for jsonl_path in jsonl_files
          if jsonl_path.name != "param_all.jsonl"
        }

        for jsonl_path in jsonl_files:
          if not should_render_report(jsonl_path):
            continue
          render_html_rows(source_rows[jsonl_path], out_dir / f"{jsonl_path.stem}.html")

        param_all_path, appended = update_param_all(in_path, source_rows)
        print(f"rebuilt {param_all_path} with {appended} record(s)")
        param_ideal_path, ideal_appended = update_param_ideal(in_path, source_rows)
        print(f"rebuilt {param_ideal_path} with {ideal_appended} record(s)")
        render_html(param_ideal_path, out_dir / "param_ideal.html")
        render_html(param_all_path, out_dir / "param_all.html")
        return

    if in_path.suffix != ".jsonl":
        raise SystemExit(f"input is not a jsonl file: {in_path}")

    out_path = Path(args.out) if args.out else in_path.with_suffix(".html")
    if not out_path.is_absolute():
        out_path = SCRIPT_DIR / out_path
    render_html(in_path, out_path)


if __name__ == "__main__":
    main()
