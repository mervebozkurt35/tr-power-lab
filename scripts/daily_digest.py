"""Build (and optionally e-mail) the one-page overview of the latest day after a data update.

Reads only data/processed, so it can run after the update step whether or not the data was committed.

  python scripts/daily_digest.py                 # writes _digest/digest.html, digest/digest.txt and digest/subject.txt
  python scripts/daily_digest.py --trial         # same, with "TRIAL" in the subject (nothing was published)
  python scripts/daily_digest.py --send          # also sends it by e-mail (needs the mail secrets below)

Mail settings come from environment variables (GitHub secrets):
  MAIL_USERNAME      the sender's address, for example a Gmail address
  MAIL_APP_PASSWORD  an app password (Gmail: Google account > Security > 2-step verification > App passwords)
  MAIL_TO            who receives it (default: MAIL_USERNAME)
  MAIL_SMTP_HOST     default smtp.gmail.com (port 465, SSL)
If they are missing, nothing is sent and the script still exits normally.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
SITE = "https://trpowerlab.com"


def read(name: str) -> pd.DataFrame | None:
    p = PROC / name
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
    return df


def num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(v) else v


def fmt(v, digits=0, unit="", plus=False) -> str:
    if v is None:
        return "n/a"
    s = f"{v:+,.{digits}f}" if plus else f"{v:,.{digits}f}"
    return f"{s} {unit}".strip()


def change(now, ref, mode="rel") -> str:
    """mode: rel = percent change, pp = difference in percentage points, none = not shown"""
    if now is None or ref is None or mode == "none":
        return ""
    if mode == "pp":
        return f"{now - ref:+.0f} pp"
    return "" if ref == 0 else f"{(now - ref) / abs(ref) * 100:+.0f}%"


def build_rows(through: pd.Timestamp | None) -> tuple[list[tuple[str, list[tuple]]], str]:
    """Returns sections [(title, [(label, value, vs previous day, vs previous 7 days)])] and the day as text."""
    core = read("core_daily.csv")
    if core is None or core.empty:
        return [], "no data"
    day = through if through is not None and through in core.index else core.index.max()
    prev, wk = core.loc[:day].iloc[:-1].tail(1), core.loc[:day].iloc[:-1].tail(7)

    def item(label, col, scale=1.0, digits=0, unit="", frame=core, when=day, mode="rel"):
        v = num(frame.loc[when, col]) if (when in frame.index and col in frame.columns) else None
        v = None if v is None else v * scale
        p = None if prev.empty or col not in prev.columns else num(prev[col].iloc[0])
        w = None if col not in wk.columns else num(pd.to_numeric(wk[col], errors="coerce").mean())
        p = None if p is None else p * scale
        w = None if w is None else w * scale
        return (label, fmt(v, digits, unit), change(v, p, mode), change(v, w, mode))

    sections = []
    sections.append(("Prices", [
        item("Day-ahead price (PTF), average", "ptf_mean", 1, 0, "TL/MWh"),
        item("PTF in euro", "ptf_eur_mean", 1, 1, "EUR/MWh"),
        item("PTF, lowest hour", "ptf_min", 1, 0, "TL/MWh"),
        item("PTF, highest hour", "ptf_max", 1, 0, "TL/MWh"),
        item("Imbalance price (SMP), average", "smf_mean", 1, 0, "TL/MWh"),
        item("Share of hours with a system deficit", "deficit_share", 100, 0, "%", mode="pp"),
    ]))
    row = core.loc[day]
    tot = num(row.get("total_mwh"))
    mix = []
    if tot:
        def share(cols):
            vals = [num(row.get(c)) or 0 for c in cols]
            return sum(vals) / tot * 100
        mix = [
            ("Gas share of metered generation", fmt(share(["gas_mwh"]), 0, "%"), "", ""),
            ("Coal and lignite share", fmt(share(["lignite_mwh", "imported_coal_mwh", "hard_coal_mwh"]), 0, "%"), "", ""),
            ("Hydro share", fmt(share(["hydro_dam_mwh", "hydro_river_mwh"]), 0, "%"), "", ""),
            ("Wind share", fmt(share(["wind_mwh"]), 0, "%"), "", ""),
            ("Solar share (metered only)", fmt(share(["solar_mwh"]), 0, "%"), "", ""),
        ]
    sections.append(("Demand and generation", [
        item("Consumption", "consumption_mwh", 1e-3, 0, "GWh"),
        item("Peak consumption", "peak_consumption_mw", 1, 0, "MW"),
        item("Metered generation", "total_mwh", 1e-3, 0, "GWh"),
        item("Net imports (positive = import)", "net_imports_mwh", 1e-3, 0, "GWh", mode="none"),
        item("Unlicensed generation fed into the grid (estimate)", "embedded_gen_est_mwh", 1e-3, 0, "GWh"),
    ] + mix))
    sections.append(("Markets", [
        item("Day-ahead market volume", "gop_mwh", 1e-3, 0, "GWh"),
        item("Bilateral contracts share", "bilateral_share", 100, 0, "%", mode="pp"),
        item("Intraday market share", "idm_share", 100, 1, "%", mode="pp"),
    ]))

    # series that publish later have their own newest day
    later = []
    for fname, title, cols in (
        ("gas_daily.csv", "Gas", [("Spot gas, day-ahead (SGP)", "sgp_day_ahead", 1, 0, "TL/1,000 Sm³"),
                                  ("Gas balancing price, buy", "bgp_buy", 1, 0, "TL/1,000 Sm³")]),
        ("balancing_daily.csv", "Balancing", [("Up-regulation delivered", "up_delivered_mwh", 1e-3, 0, "GWh"),
                                              ("Down-regulation delivered", "down_delivered_mwh", 1e-3, 0, "GWh")]),
        ("wind_daily.csv", "Wind", [("Wind generation", "wind_gen_mwh", 1e-3, 0, "GWh"),
                                    ("Day-ahead forecast error", "wind_mae_pct_of_gen", 1, 0, "% of generation")]),
    ):
        f = read(fname)
        if f is None or f.empty:
            continue
        w = f.index.max()
        rows = []
        for label, col, sc, dg, un in cols:
            rows.append(item(f"{label} ({w:%d %b})", col, sc, dg, un, frame=f, when=w))
        # the previous-day and 7-day columns above were taken from core's dates; blank them for these frames
        later.append((title, [(a, b, "", "") for a, b, _, _ in rows]))
    sections += later

    res = read("reservoirs_daily.csv")
    if res is not None and not res.empty:
        w = res.index.max()
        lvl = pd.to_numeric(res.loc[res.index == w, "active_fullness_pct"], errors="coerce").mean()
        sections.append(("Reservoirs", [(f"Average active fullness of the monitored dams, unweighted ({w:%d %b})", fmt(num(lvl), 0, "%"), "", "")]))
    return sections, f"{day:%A %d %B %Y}"


def health_lines() -> tuple[list[str], list[str], list[str], bool]:
    p = PROC / "update_status.json"
    if not p.exists():
        return [], [], [], True
    st = json.loads(p.read_text(encoding="utf-8"))
    files = []
    for n, i in st.get("files", {}).items():
        if i.get("added") or i.get("changed"):
            files.append(f"{n}: {i.get('added', 0)} new rows, {i.get('changed', 0)} revised, newest {i.get('last', '')}")
    return files, st.get("warnings", []), st.get("errors", []), bool(st.get("ok", True))


def render(sections, day_text, trial, deploy_note, update_outcome="", day=None) -> tuple[str, str, str]:
    files, warns, errs, ok = health_lines()
    errs = list(errs)
    today = pd.Timestamp.now(tz="Europe/Istanbul").tz_localize(None).normalize()
    stale = None
    if day is not None:
        stale = (today - pd.Timedelta(days=1) - day).days
    status_old = False
    try:
        st0 = json.loads((PROC / "update_status.json").read_text(encoding="utf-8"))
        status_old = pd.Timestamp(st0["checked"]).normalize() < today
    except Exception:
        status_old = True
    if update_outcome == "failure" and status_old:
        errs.insert(0, "The update step failed before it could write its status file, so nothing was added in this run. "
                       "Open the build job and read the log of the step \"Fetch new data from EPİAŞ\".")
        ok = False
    if stale is not None and stale > 1:
        errs.append(f"The newest day in the data is {day:%d %B %Y}, {stale} days behind yesterday. This run did not bring the data up to date.")
        ok = False
    core = read("core_daily.csv")
    ptf = None
    try:
        st = json.loads((PROC / "update_status.json").read_text(encoding="utf-8"))
        through = pd.Timestamp(st["data_through"]["core_daily.csv"])
        ptf = num(core.loc[through, "ptf_mean"])
    except Exception:
        through = None
    state = "completed" if ok else ("FAILED, data is out of date" if (stale or 0) > 1 else "completed with problems")
    subject = (("TRIAL: " if trial else "") + f"TR Power Lab data update {state}: {day_text.split(' ', 1)[1] if ' ' in day_text else day_text}"
               + (f", average PTF {ptf:,.0f} TL/MWh" if ptf else ""))

    txt = [subject, "", f"Latest complete day: {day_text}", ""]
    if deploy_note:
        txt += [deploy_note, ""]
    for title, items in sections:
        txt.append(title.upper())
        for label, val, d1, d7 in items:
            parts = [x for x in ((f"vs previous day {d1}" if d1 else ""), (f"vs previous 7 days {d7}" if d7 else "")) if x]
            extra = f"   ({', '.join(parts)})" if parts else ""
            txt.append(f"  {label}: {val}{extra}")
        txt.append("")
    if files:
        txt += ["FILES CHANGED IN THIS RUN"] + [f"  {f}" for f in files] + [""]
    for title, items in (("ERRORS", errs), ("WARNINGS", warns)):
        if items:
            txt += [title] + [f"  {x}" for x in items] + [""]
    txt.append(f"{SITE}")

    td = 'style="padding:4px 10px;border-bottom:1px solid #e3e3e3;"'
    h = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1b1b1b;max-width:680px">',
         f'<h2 style="margin:0 0 4px">{html.escape(subject)}</h2>',
         f'<p style="margin:0 0 12px;color:#555">Latest complete day: <b>{html.escape(day_text)}</b></p>']
    if deploy_note:
        h.append(f'<p style="margin:0 0 12px">{html.escape(deploy_note)}</p>')
    for title, items in sections:
        h.append(f'<h3 style="margin:16px 0 4px;font-size:15px">{html.escape(title)}</h3><table style="border-collapse:collapse;width:100%">')
        for label, val, d1, d7 in items:
            parts = [x for x in ((f"vs prev. day {d1}" if d1 else ""), (f"vs prev. 7 days {d7}" if d7 else "")) if x]
            cmp_ = f'<span style="color:#777">{" · ".join(parts)}</span>' if parts else ""
            h.append(f"<tr><td {td}>{html.escape(label)}</td><td {td} align=\"right\"><b>{html.escape(val)}</b></td><td {td}>{cmp_}</td></tr>")
        h.append("</table>")
    if files:
        h.append('<h3 style="margin:16px 0 4px;font-size:15px">Files changed in this run</h3><ul style="margin:0;padding-left:18px">'
                 + "".join(f"<li>{html.escape(f)}</li>" for f in files) + "</ul>")
    for title, items, colour in (("Errors", errs, "#b00020"), ("Warnings", warns, "#8a5a00")):
        if items:
            h.append(f'<h3 style="margin:16px 0 4px;font-size:15px;color:{colour}">{title}</h3><ul style="margin:0;padding-left:18px">'
                     + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>")
    h.append(f'<p style="margin-top:16px;color:#777">Sums and averages are for the Istanbul day. Generation is the metered real-time data; '
             f'unlicensed generation is an estimate. <a href="{SITE}">{SITE}</a></p></div>')
    return subject, "\n".join(txt), "\n".join(h)


def send(subject: str, text: str, body_html: str) -> bool:
    user, pwd = os.environ.get("MAIL_USERNAME"), os.environ.get("MAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO") or user
    if not (user and pwd and to):
        print("Mail not configured (MAIL_USERNAME / MAIL_APP_PASSWORD missing); nothing sent.")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")
    host = os.environ.get("MAIL_SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"Mail sent to {to}.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "_digest"))
    ap.add_argument("--trial", action="store_true", help="the data was not committed or published")
    ap.add_argument("--deploy", default="", help="result of the publish job, for one line in the mail")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--update-outcome", default="", help="result of the update step (success or failure)")
    ap.add_argument("--send-only", action="store_true", help="send the files already written in --out (used by the notify job)")
    a = ap.parse_args()

    if a.send_only:
        out = Path(a.out)
        subject = (out / "subject.txt").read_text(encoding="utf-8")
        text = (out / "digest.txt").read_text(encoding="utf-8")
        body_html = (out / "digest.html").read_text(encoding="utf-8")
        if not a.trial and a.deploy and a.deploy != "success":
            note = f"The site publish step finished with status: {a.deploy}. The data itself is committed."
            subject += f" (site publish: {a.deploy})"
            text = note + "\n\n" + text
            body_html = f'<p style="font-family:Arial,sans-serif;color:#b00020"><b>{html.escape(note)}</b></p>' + body_html
        try:
            send(subject, text, body_html)
        except Exception as exc:
            print(f"::warning::The summary mail could not be sent: {type(exc).__name__}: {exc}")
        return 0

    through = None
    try:
        st = json.loads((PROC / "update_status.json").read_text(encoding="utf-8"))
        through = pd.Timestamp(st["data_through"]["core_daily.csv"])
    except Exception:
        pass
    sections, day_text = build_rows(through)
    _core = read("core_daily.csv")
    day_ = (through if through is not None and _core is not None and through in _core.index else (_core.index.max() if _core is not None else None))
    note = ""
    if a.trial:
        note = "Trial run: the new data was not committed and the site was not published."
    elif a.deploy and a.deploy != "success":
        note = f"The site publish step finished with status: {a.deploy}. The data itself is committed."
    subject, text, body_html = render(sections, day_text, a.trial, note, a.update_outcome, day_)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "subject.txt").write_text(subject, encoding="utf-8")
    (out / "digest.txt").write_text(text, encoding="utf-8")
    (out / "digest.html").write_text(body_html, encoding="utf-8")
    print(text)
    if a.send:
        try:
            send(subject, text, body_html)
        except Exception as exc:  # a mail problem must not hide the data result
            print(f"::warning::The summary mail could not be sent: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
