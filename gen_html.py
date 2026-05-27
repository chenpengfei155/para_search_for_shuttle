#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent

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
.tags-group { display: flex; flex-wrap: wrap; gap: 4px 10px; max-width: 760px; }
.mode-row { font-size: 13px; }
.summary { margin: 8px 0 12px; font-size: 13px; color: #444; }
.summary button { font-size: 12px; margin-left: 8px; padding: 2px 8px; cursor: pointer; }
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
    <label><input type="checkbox" id="show-derived" checked> show derived columns</label>
  </section>
  <section>
    <strong>Tags</strong>
    <div class="mode-row">Match:
      <label><input type="radio" name="match" value="AND" checked> ALL of selected</label>
      <label><input type="radio" name="match" value="OR"> ANY of selected</label>
    </div>
    <div id="tag-filter" class="tags-group"></div>
  </section>
</div>

<div class="summary">
  Showing <strong id="visible-count">0</strong> / <strong id="total-count">0</strong> records
  <button id="clear-tags">clear tag selection</button>
  &nbsp;|&nbsp;
  Selected: <strong id="selected-count">0</strong>
  <button id="select-all-visible">select all visible</button>
  <button id="select-none">deselect all</button>
  <button id="copy-selected">copy selected JSON</button>
  <span id="copy-status"></span>
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

<script id="data" type="application/json">__DATA__</script>
<script>
const records = JSON.parse(document.getElementById('data').textContent);
records.forEach((r, i) => { r._idx = i; });
const selected = new Set();

const allTags = new Set();
for (const r of records) {
  for (const t of (r.tags || [])) allTags.add(t);
}

// Sort tags so target_security=* comes first, then rough, then lwe>*, sis_uf>*, sis_suf>*
function tagSortKey(t) {
  if (t.startsWith('target_security=')) return [0, parseInt(t.split('=')[1], 10)];
  if (t === 'rough') return [1, 0];
  const order = { 'lwe': 2, 'sis_uf': 3, 'sis_suf': 4 };
  const [prefix, thr] = t.split('>');
  return [order[prefix] ?? 99, parseInt(thr, 10) || 0];
}
const sortedTags = [...allTags].sort((a, b) => {
  const [pa, va] = tagSortKey(a), [pb, vb] = tagSortKey(b);
  return pa !== pb ? pa - pb : va - vb;
});
const tagFilterDiv = document.getElementById('tag-filter');
for (const t of sortedTags) {
  const safe = t.replace(/[^a-zA-Z0-9]/g, '_');
  tagFilterDiv.insertAdjacentHTML('beforeend',
    `<label><input type="checkbox" data-tag="${t}" id="tag-${safe}"> ${t}</label>`);
}

let sortKey = null, sortAsc = true;
document.querySelectorAll('th[data-sort]').forEach(th => {
  th.addEventListener('click', () => {
    const k = th.dataset.sort;
    if (sortKey === k) sortAsc = !sortAsc;
    else { sortKey = k; sortAsc = true; }
    document.querySelectorAll('th[data-sort]').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
    th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
    render();
  });
});

document.getElementById('clear-tags').addEventListener('click', () => {
  document.querySelectorAll('#tag-filter input:checked').forEach(i => i.checked = false);
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
    if (t.includes('>') && checkedTargets.length > 0) {
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
updateTagVisibility();

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

function render() {
  const checkedTags = [...document.querySelectorAll('#tag-filter input:checked')].map(i => i.dataset.tag);
  const mode = document.querySelector('input[name=match]:checked').value;

  let rows = records.filter(r => {
    if (checkedTags.length === 0) return true;
    const rtags = new Set(r.tags || []);
    return mode === 'AND'
      ? checkedTags.every(t => rtags.has(t))
      : checkedTags.some(t => rtags.has(t));
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
  document.getElementById('visible-count').textContent = rows.length;
  document.getElementById('total-count').textContent = records.length;
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
    for (const cb of document.querySelectorAll('#tag-filter input')) {
      if (!cb.dataset.tag.startsWith('target_security=')) cb.checked = false;
    }
    updateTagVisibility();
  }
  if (e.target.matches('input[type=checkbox], input[name=match]')) render();
});
render();
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Render param search jsonl into a filterable HTML report.")
    parser.add_argument("--in", dest="inp", default="results/param_search.jsonl",
                        help="input jsonl path (relative to script dir if not absolute)")
    parser.add_argument("--out", default="results/param_search.html",
                        help="output html path (relative to script dir if not absolute)")
    args = parser.parse_args()

    in_path = Path(args.inp)
    out_path = Path(args.out)
    if not in_path.is_absolute():
        in_path = SCRIPT_DIR / in_path
    if not out_path.is_absolute():
        out_path = SCRIPT_DIR / out_path

    if not in_path.exists():
        raise SystemExit(f"input not found: {in_path}")

    rows = load_jsonl(in_path)
    payload = json.dumps(rows, ensure_ascii=False)
    # Prevent any literal "</script>" in the JSON from breaking the host tag.
    payload = payload.replace("</", "<\\/")

    html = HTML_TEMPLATE.replace("__DATA__", payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {len(rows)} records -> {out_path}")


if __name__ == "__main__":
    main()
