"""Helpers for the Regulation section: load the three CSV files and build the HTML for the
timeline table, the legislation tree and the institution cards. The pages stay short and
the three pages cannot disagree, because they all read data/regulation/*.csv.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "regulation"

AREAS = ["Market structure", "Prices and settlement", "Grid and interconnection", "Renewables and support",
         "New business types", "Retail and tariffs", "Climate and adjacent"]
AREA_COLOURS = {"Market structure": "#6470E0", "Prices and settlement": "#169CAB", "Grid and interconnection": "#D9701F",
                "Renewables and support": "#4FA864", "New business types": "#D9558C", "Retail and tariffs": "#C9A227",
                "Climate and adjacent": "#9C5CDD"}


def load_milestones() -> pd.DataFrame:
    return pd.read_csv(DIR / "milestones.csv", dtype=str).fillna("")


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ev = pd.read_csv(DIR / "events.csv", dtype=str).fillna("")
    inst = pd.read_csv(DIR / "institutions.csv", dtype=str).fillna("")
    log = pd.read_csv(DIR / "research_log.csv", dtype=str).fillna("")
    ev["when"] = ev["date"].apply(plot_date)
    return ev, inst, log


def plot_date(s: str) -> pd.Timestamp:
    """'2004-03' and '2018' are kept on the chart at the start of the month or year."""
    parts = s.split("-")
    return pd.Timestamp(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1)


def shown_date(r) -> str:
    """The date as known: a month or a year is shown as such, never padded."""
    d = r["date"]
    suffix = {"adoption": " (adopted)", "decision": " (decision)", "start": " (start)", "reported": " (reported)"}
    return d + suffix.get(r["date_type"], "")


def badge(status: str) -> str:
    cls = "text-bg-success" if status == "verified" else "text-bg-warning"
    return f'<span class="badge {cls}">{escape(status)}</span>'


def source_link(r) -> str:
    if r["source_url"]:
        return f'<a href="{escape(r["source_url"])}">source</a>'
    return '<span class="text-muted">no page read</span>'


def timeline_table(ev: pd.DataFrame) -> str:
    rows = []
    for _, r in ev.sort_values(["when", "id"]).iterrows():
        inst = ", ".join(r["institutions"].split(";")) if r["institutions"] else ""
        rows.append(
            f'<tr id="{escape(r["id"])}" data-area="{escape(r["area"])}" data-status="{r["status"]}">'
            f'<td class="text-nowrap">{escape(shown_date(r))}</td>'
            f'<td><strong>{escape(r["title"])}</strong><br><span class="small text-muted">{escape(r["instrument"])}</span>'
            f'<br><span class="small">{escape(r["effect"])}</span>'
            f'<br><span class="small text-muted">Source note: {escape(r["source_note"])}</span></td>'
            f'<td>{escape(r["kind"])}</td><td>{escape(r["area"])}</td><td>{escape(inst)}</td>'
            f'<td>{badge(r["status"])}<br>{source_link(r)}</td></tr>'
        )
    head = ("<thead><tr><th>Date</th><th>What changed</th><th>Type</th><th>Area</th><th>Institutions</th>"
            "<th>Status</th></tr></thead>")
    return f'<div class="table-responsive"><table class="table table-sm align-top" id="reg-table">{head}<tbody>{"".join(rows)}</tbody></table></div>'


FILTER_JS = """
<script>
(function () {
  var area = document.getElementById('f-area'), status = document.getElementById('f-status'),
      text = document.getElementById('f-text'), count = document.getElementById('f-count');
  function apply() {
    var rows = document.querySelectorAll('#reg-table tbody tr'), shown = 0;
    var q = text.value.toLowerCase();
    rows.forEach(function (tr) {
      var ok = (!area.value || tr.dataset.area === area.value) &&
               (!status.value || tr.dataset.status === status.value) &&
               (!q || tr.textContent.toLowerCase().indexOf(q) !== -1);
      tr.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    count.textContent = shown + ' of ' + rows.length + ' entries shown';
  }
  [area, status].forEach(function (e) { e.addEventListener('change', apply); });
  text.addEventListener('input', apply);
  apply();
})();
</script>
"""


def filter_controls(ev: pd.DataFrame) -> str:
    opts = "".join(f'<option value="{escape(a)}">{escape(a)}</option>' for a in AREAS if a in set(ev["area"]))
    return (
        '<div class="row g-2 mb-3">'
        f'<div class="col-md-4"><select id="f-area" class="form-select form-select-sm"><option value="">All areas</option>{opts}</select></div>'
        '<div class="col-md-3"><select id="f-status" class="form-select form-select-sm"><option value="">Verified and draft</option>'
        '<option value="verified">Verified only</option><option value="draft">Draft only</option></select></div>'
        '<div class="col-md-5"><input id="f-text" class="form-control form-control-sm" placeholder="Search title, number, institution"></div>'
        '</div><p class="small text-muted" id="f-count"></p>'
    )


def tree_html(ev: pd.DataFrame) -> str:
    """Nested collapsible list built from the parent column. Each node: date, title, relation to its parent."""
    ev = ev.sort_values(["when", "id"])
    kids: dict[str, list] = {}
    for _, r in ev.iterrows():
        kids.setdefault(r["parent"], []).append(r)

    def node(r, depth: int) -> str:
        label = (f'<span class="text-muted">{escape(r["date"])}</span> '
                 f'<a href="index.html#{escape(r["id"])}"><strong>{escape(r["title"])}</strong></a> '
                 f'<span class="small text-muted">{escape(r["kind"])}</span> {badge(r["status"])}')
        rel = f'<div class="small text-muted ms-1">{escape(r["relation"])}</div>' if r["relation"] else ""
        sub = kids.get(r["id"], [])
        if not sub:
            return f'<li class="mb-1">{label}{rel}</li>'
        opened = " open" if depth == 0 else ""
        inner = "".join(node(c, depth + 1) for c in sub)
        return (f'<li class="mb-1"><details{opened}><summary>{label} <span class="small text-muted">'
                f'({count_desc(r["id"], kids)} below)</span></summary>{rel}<ul class="list-unstyled ms-3 border-start ps-3">{inner}</ul>'
                f'</details></li>')

    roots = kids.get("", [])
    return '<ul class="list-unstyled reg-tree">' + "".join(node(r, 0) for r in roots) + "</ul>"


def count_desc(rid: str, kids: dict) -> int:
    return sum(1 + count_desc(c["id"], kids) for c in kids.get(rid, []))


def institution_cards(ev: pd.DataFrame, inst: pd.DataFrame) -> str:
    out = []
    for _, i in inst.iterrows():
        out.append(
            f'<div class="col-md-6 mb-3"><div class="card h-100"><div class="card-body">'
            f'<h5 class="card-title">{escape(i["code"])} <span class="small text-muted">{escape(i["name"])}</span></h5>'
            f'<p class="mb-1">{escape(i["role"])}</p>'
            f'<p class="small text-muted mb-0">Basis: {escape(i["legal_basis"])}</p></div></div></div>')
    return '<div class="row">' + "".join(out) + "</div>"


def matrix_html(ev: pd.DataFrame, inst: pd.DataFrame) -> str:
    """Institution by area: number of entries in which the institution is named."""
    areas = [a for a in AREAS if a in set(ev["area"])]
    head = "<tr><th></th>" + "".join(f"<th class='text-center small'>{escape(a)}</th>" for a in areas) + "</tr>"
    body = []
    for _, i in inst.iterrows():
        cells = []
        for a in areas:
            n = int(((ev["area"] == a) & ev["institutions"].str.split(";").apply(lambda s: i["code"] in s)).sum())
            cells.append(f"<td class='text-center'>{n if n else ''}</td>")
        body.append(f"<tr><th class='text-nowrap'>{escape(i['code'])}</th>{''.join(cells)}</tr>")
    return f'<div class="table-responsive"><table class="table table-sm">{head}{"".join(body)}</table></div>'


def log_table(log: pd.DataFrame) -> str:
    rows = []
    for _, r in log.iterrows():
        src = f'<a href="{escape(r["source"])}">{escape(r["source"])}</a>' if r["source"].startswith("http") else escape(r["source"])
        rows.append(f'<tr><td class="text-nowrap">{escape(r["entry"])}</td><td class="small" style="word-break:break-all">{src}</td>'
                    f'<td>{escape(r["outcome"])}</td><td class="small">{escape(r["note"])}</td></tr>')
    return ('<div class="table-responsive"><table class="table table-sm"><thead><tr><th>Entry</th><th>Source</th><th>Outcome</th>'
            '<th>Note</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


# ---------------------------------------------------------------------------------------------------------------
# Vertical milestone timeline
# ---------------------------------------------------------------------------------------------------------------
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

VT_CSS = """
<style>
.vt-bar { display:flex; flex-wrap:wrap; gap:.4rem; margin:0 0 .6rem 0; }
.vt-chip { border:1px solid var(--c, #888); color:inherit; background:transparent; border-radius:999px; padding:.15rem .7rem;
           font-size:.82rem; cursor:pointer; line-height:1.4; }
.vt-chip[aria-pressed="true"] { background:var(--c, #888); color:#0E161B; font-weight:600; }
.vt-jump { font-size:.85rem; margin:0 0 1.2rem 0; }
.vt-jump a { margin-right:.9rem; }
.vt { position:relative; margin:0; padding:0 0 0 1.6rem; list-style:none; border-left:2px solid rgba(148,165,175,.35); }
.vt-item { position:relative; margin:0 0 1.5rem 0; }
.vt-item::before { content:""; position:absolute; left:calc(-1.6rem - 7px); top:.55rem; width:12px; height:12px; border-radius:50%;
                   background:var(--c); border:2px solid #0E161B; box-sizing:content-box; }
.vt-decade { margin:1.8rem 0 1rem -1.6rem; padding-left:1.6rem; font-weight:700; font-size:1.15rem; letter-spacing:.02em; }
.vt-date { font-size:.85rem; opacity:.75; margin:0 0 .15rem 0; }
.vt-card { border:1px solid rgba(148,165,175,.3); border-left:4px solid var(--c); border-radius:6px; padding:.8rem 1rem; }
.vt-tags { display:flex; flex-wrap:wrap; gap:.4rem; align-items:center; margin:0 0 .3rem 0; font-size:.75rem; }
.vt-type { color:var(--c); font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.vt-draft { background:#C9A227; color:#0E161B; border-radius:3px; padding:0 .4rem; font-weight:600; }
.vt-title { font-size:1.1rem; font-weight:600; margin:0 0 .35rem 0; }
.vt-text { margin:0 0 .6rem 0; }
.vt-inst { margin:0; padding:.5rem 0 0 0; list-style:none; border-top:1px solid rgba(148,165,175,.2); font-size:.85rem; }
.vt-inst li { margin:0 0 .35rem 0; }
.vt-inst .tr { opacity:.75; }
.vt-inst .rests { opacity:.65; }
@media (max-width: 576px) { .vt { padding-left:1.2rem; } .vt-item::before { left:calc(-1.2rem - 7px); } .vt-decade { margin-left:-1.2rem; padding-left:1.2rem; } }
</style>
"""

VT_JS = """
<script>
(function () {
  var chips = document.querySelectorAll('.vt-chip'), items = document.querySelectorAll('.vt-item'),
      decades = document.querySelectorAll('.vt-decade'), count = document.getElementById('vt-count');
  var active = null;
  function apply() {
    var shown = 0;
    items.forEach(function (it) {
      var ok = !active || it.dataset.type === active;
      it.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    decades.forEach(function (d) {
      var any = false, n = d.nextElementSibling;
      while (n && !n.classList.contains('vt-decade')) { if (n.style.display !== 'none') any = true; n = n.nextElementSibling; }
      d.style.display = any ? '' : 'none';
    });
    chips.forEach(function (c) { c.setAttribute('aria-pressed', (c.dataset.type === active) ? 'true' : 'false'); });
    count.textContent = shown + ' of ' + items.length + ' milestones shown';
  }
  chips.forEach(function (c) {
    c.addEventListener('click', function () { active = (active === c.dataset.type) ? null : c.dataset.type; apply(); });
  });
  apply();
})();
</script>
"""


def _when(d: str) -> str:
    p = d.split("-")
    return f"{MONTHS[int(p[1]) - 1]} {p[0]}" if len(p) > 1 else p[0]


def vertical_timeline(ms: pd.DataFrame, ev: pd.DataFrame) -> str:
    e = ev.set_index("id")
    ms = ms.sort_values(["date", "id"])
    chips = "".join(
        f'<button type="button" class="vt-chip" style="--c:{AREA_COLOURS[a]}" data-type="{escape(a)}" aria-pressed="false">{escape(a)}</button>'
        for a in AREAS if a in set(ms["type"]))
    decades = sorted({d[:3] for d in ms["date"]})
    jump = "".join(f'<a href="#vt-{d}0s">{d}0s</a>' for d in decades)
    body, seen = [], set()
    for _, m in ms.iterrows():
        dec = m["date"][:3]
        if dec not in seen:
            seen.add(dec)
            body.append(f'<li class="vt-decade" id="vt-{dec}0s">{dec}0s</li>')
        items = []
        for i in m["instruments"].split(";"):
            r = e.loc[i]
            tr = f' <span class="tr">· {escape(r["name_tr"])}</span>' if r["name_tr"] else ""
            par = ""
            if r["parent"] and r["parent"] in e.index:
                par = f' <span class="rests">· rests on {escape(e.loc[r["parent"], "label"])}</span>'
            src = f' · <a href="{escape(r["source_url"])}">source</a>' if r["source_url"] else ""
            ins = r["instrument"]
            ins = ins[len(r["label"]):].strip() if ins.startswith(r["label"]) else ins
            ins = ins if ins.startswith("(") else f"({ins})"
            items.append(f'<li><strong>{escape(r["label"])}</strong> <span class="rests">{escape(ins)}</span>{tr}{par}{src}</li>')
        draft = '<span class="vt-draft">draft</span>' if m["status"] == "draft" else ""
        c = AREA_COLOURS[m["type"]]
        body.append(
            f'<li class="vt-item" id="{escape(m["id"])}" data-type="{escape(m["type"])}" style="--c:{c}">'
            f'<p class="vt-date">{_when(m["date"])}</p><div class="vt-card"><div class="vt-tags">'
            f'<span class="vt-type">{escape(m["type"])}</span>{draft}</div>'
            f'<h3 class="vt-title">{escape(m["title"])}</h3><p class="vt-text">{escape(m["summary"])}</p>'
            f'<ul class="vt-inst">{"".join(items)}</ul></div></li>')
    return (VT_CSS + f'<div class="vt-bar">{chips}</div><p class="small" id="vt-count"></p><p class="vt-jump">Jump to: {jump}</p>'
            + f'<ol class="vt">{"".join(body)}</ol>' + VT_JS)


def instrument_table(ev: pd.DataFrame) -> str:
    """Compact index: one line per instrument, no long text."""
    rows = []
    for _, r in ev.sort_values(["when", "id"]).iterrows():
        src = f'<a href="{escape(r["source_url"])}">source</a>' if r["source_url"] else '<span class="text-muted">none read</span>'
        tr = f'<br><span class="small text-muted">{escape(r["name_tr"])}</span>' if r["name_tr"] else ""
        rows.append(
            f'<tr id="{escape(r["id"])}" data-area="{escape(r["area"])}" data-status="{r["status"]}">'
            f'<td class="text-nowrap">{escape(r["date"])}</td><td><strong>{escape(r["label"])}</strong>{tr}</td>'
            f'<td>{escape(r["kind"])}</td><td>{escape(r["area"])}</td><td>{escape(r["instrument"])}</td>'
            f'<td>{badge(r["status"])} {src}</td></tr>')
    head = "<thead><tr><th>Date</th><th>Instrument</th><th>Type</th><th>Area</th><th>Number and gazette</th><th>Status</th></tr></thead>"
    return f'<div class="table-responsive"><table class="table table-sm align-top" id="reg-table">{head}<tbody>{"".join(rows)}</tbody></table></div>'
