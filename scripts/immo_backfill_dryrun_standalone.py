"""IMMO PAYMENT BACKFILL — DRY-RUN, STANDALONE (READ-ONLY. NO WRITES. NO MIGRATION.)

Identical rules to autotax/immo_rules.py + immo_payments.py, but self-contained: it runs
inside the Railway container, which still has the OLD deployed code. It executes ONLY
SELECT statements.

  🟢 HIGH    the rent month can be inferred safely  → the only rows that may ever be auto-migrated
  🟡 MEDIUM  probably right, needs a human decision → left untouched
  🔴 LOW     cannot be inferred reliably            → left untouched
"""
import json
import os
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import create_engine, text

HIGH, MED, LOW = "HIGH", "MEDIUM", "LOW"
TODAY = date.today()

# ── rules (mirrors autotax/immo_rules.py) ────────────────────────────


def active(t, y, m):
    ms, me = date(y, m, 1), date(y, m, monthrange(y, m)[1])
    von = t["von"] or date(1900, 1, 1)
    bis = t["bis"] or date(2999, 12, 31)
    return von <= me and bis >= ms


def proration(t, y, m):
    dim = monthrange(y, m)[1]
    ms, me = date(y, m, 1), date(y, m, dim)
    von = t["von"] or date(1900, 1, 1)
    bis = t["bis"] or date(2999, 12, 31)
    s, e = max(von, ms), min(bis, me)
    if e < s:
        return 0.0
    return max(0.0, min(1.0, ((e - s).days + 1) / dim))


def eff_kalt(t, y, m):
    base = float(t["kaltmiete"] or 0)
    raw = t["miete_historie"]
    if not raw:
        return base
    try:
        hist = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        return base
    me = date(y, m, monthrange(y, m)[1])
    best_ab, best = None, base
    for c in hist or []:
        try:
            ab = datetime.strptime(str(c.get("ab"))[:10], "%Y-%m-%d").date()
            k = float(c.get("kalt"))
        except Exception:
            continue
        if ab <= me and (best_ab is None or ab > best_ab):
            best_ab, best = ab, k
    return best


def monat_soll(t, y, m):
    """Warmmiete = (Kalt + NK) × Tagesanteil; vereinbarte Erstmiete is gross."""
    em = t["erstmonat_betrag"]
    if em is not None and t["von"] and t["von"].year == y and t["von"].month == m:
        return round(float(em), 2)
    warm = eff_kalt(t, y, m) + float(t["nk_voraus"] or 0)
    return round(warm * proration(t, y, m), 2)


def exc_list(t):
    raw = t["offene_monate"]
    if not raw:
        return []
    try:
        lst = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        return []
    out = []
    for e in lst or []:
        if isinstance(e, dict) and e.get("ym"):
            out.append({"ym": str(e["ym"])[:7], "typ": e.get("typ") or "unpaid", "offen": e.get("offen")})
        elif isinstance(e, str) and len(e) >= 7:
            out.append({"ym": e[:7], "typ": "unpaid", "offen": None})
    return out


def exc_for(t, y, m):
    ym = "%04d-%02d" % (y, m)
    for e in exc_list(t):
        if e["ym"] == ym:
            return e
    return None


def month_open(t, y, m):
    if not active(t, y, m):
        return 0.0
    e = exc_for(t, y, m)
    if not e:
        return 0.0
    if e["typ"] == "partial":
        return round(float(e.get("offen") or 0), 2)
    if e["typ"] == "settled":
        return 0.0
    return monat_soll(t, y, m)


def due_months(t):
    start = t["von"] or date(TODAY.year, 1, 1)
    y, m = start.year, start.month
    out = []
    while (y, m) <= (TODAY.year, TODAY.month):
        if active(t, y, m):
            out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def open_debt(t):
    tot = 0.0
    months = []
    for (y, m) in due_months(t):
        o = month_open(t, y, m)
        if o > 0:
            months.append((y, m, o))
            tot = round(tot + o, 2)
    return tot, months


def simulate_payment(t, y, m, paid):
    """What the Payment Service would do to that month's exception (in memory only)."""
    if not active(t, y, m):
        return None
    soll = monat_soll(t, y, m)
    if paid <= 0:
        return exc_for(t, y, m)
    if paid >= soll - 0.01:
        return {"ym": "%04d-%02d" % (y, m), "typ": "settled"}
    return {"ym": "%04d-%02d" % (y, m), "typ": "partial", "offen": round(soll - paid, 2)}


# ── main ──────────────────────────────────────────────────────────────


def main():
    e = create_engine(os.environ["DATABASE_URL"])
    c = e.connect()
    cols = {r[0] for r in c.execute(text(
        "select column_name from information_schema.columns where table_name='immo_rent'"))}
    has_new = {"fuer_jahr", "fuer_monat"} <= cols
    sel = "id, tenancy_id, user_id, datum, betrag" + (", fuer_jahr, fuer_monat" if has_new else "")
    rents = [dict(zip(sel.replace(" ", "").split(","), r)) for r in c.execute(text(
        f"select {sel} from immo_rent where is_deleted is not true order by tenancy_id, datum"))]
    for r in rents:
        r.setdefault("fuer_jahr", None)
        r.setdefault("fuer_monat", None)

    tcols = "id, user_id, mieter_name, unit_id, von, bis, kaltmiete, nk_voraus, erstmonat_betrag, miete_historie, offene_monate"
    tens = {r[0]: dict(zip(tcols.replace(" ", "").split(","), r)) for r in c.execute(text(
        f"select {tcols} from immo_tenancy where is_deleted is not true"))}
    units = {r[0]: r[1] for r in c.execute(text("select id, property_id from immo_unit"))}
    props = {r[0]: (r[1] or r[2] or "") for r in c.execute(text("select id, adresse, name from immo_property"))}

    print("=" * 76)
    print("IMMO PAYMENT BACKFILL — DRY-RUN   (READ-ONLY · nothing is written)")
    print(f"today {TODAY} · fuer_jahr/fuer_monat columns exist in prod DB: {has_new}")
    print("=" * 76)

    todo = [r for r in rents if r["fuer_jahr"] is None or r["fuer_monat"] is None]
    aff = sorted({r["tenancy_id"] for r in todo if r["tenancy_id"]})
    print(f"\n1. payment records (immo_rent, not deleted) : {len(rents)}")
    print(f"   candidates without fuer_jahr/fuer_monat  : {len(todo)}")
    print(f"2. tenancies affected                        : {len(aff)}")
    print(f"   payments with NO tenancy                  : {sum(1 for r in todo if not r['tenancy_id'])}")

    by_ym = defaultdict(list)
    for r in todo:
        if r["tenancy_id"] and r["datum"]:
            by_ym[(r["tenancy_id"], r["datum"].year, r["datum"].month)].append(r)

    def classify(r, t):
        if not r["tenancy_id"] or t is None:
            return LOW, ["no tenancy — belongs to no rent account"]
        if r["datum"] is None:
            return LOW, ["no date — no month can be inferred"]
        if r["betrag"] is None or float(r["betrag"]) <= 0:
            return LOW, ["amount missing or <= 0"]
        y, m = r["datum"].year, r["datum"].month
        if r["datum"] > TODAY:
            return LOW, [f"date {r['datum']} is in the FUTURE"]
        if not active(t, y, m):
            return LOW, [f"tenancy not active in {y}-{m:02d} (Einzug {t['von']}, Auszug {t['bis'] or '—'})"]
        soll = monat_soll(t, y, m)
        amt = round(float(r["betrag"]), 2)
        why = []
        if r["datum"].day <= 3:
            why.append(f"booked on day {r['datum'].day} — may be the PREVIOUS month's rent paid late")
        same = by_ym.get((r["tenancy_id"], y, m), [])
        if len(same) > 1:
            why.append(f"{len(same)} payments for this tenant in {y}-{m:02d} (instalments? duplicate?)")
        if soll <= 0:
            why.append("month Soll is 0 — no cross-check possible")
        elif amt > soll + 0.01:
            why.append(f"amount {amt:.2f} EXCEEDS the month Soll {soll:.2f} — may cover several months")
        elif amt < soll - 0.01:
            why.append(f"amount {amt:.2f} is BELOW the month Soll {soll:.2f} (partial payment?)")
        if why:
            return MED, why
        return HIGH, [f"amount == month Soll ({soll:.2f}), tenancy active, booked mid-month"]

    print("\n3. ROW BY ROW")
    print("-" * 76)
    cnt = defaultdict(int)
    high_by_ten = defaultdict(list)
    for tid in aff + ([None] if any(not r["tenancy_id"] for r in todo) else []):
        t = tens.get(tid)
        rows = [r for r in todo if r["tenancy_id"] == tid]
        if t:
            addr = props.get(units.get(t["unit_id"]), "")
            warm = round(float(t["kaltmiete"] or 0) + float(t["nk_voraus"] or 0), 2)
            print(f"\n  {t['mieter_name']}  (tenancy {tid})  {addr}")
            print(f"    Einzug {t['von']} · Auszug {t['bis'] or '—'} · Kalt {t['kaltmiete']} + NK {t['nk_voraus']} = Warm {warm}")
        else:
            print("\n  ⚠ payments WITHOUT a tenancy")
        for r in rows:
            conf, why = classify(r, t)
            cnt[conf] += 1
            if conf == HIGH:
                high_by_ten[tid].append(r)
            d = r["datum"]
            fy = d.year if d else "—"
            fm = f"{d.month:02d}" if d else "—"
            amt = f"{float(r['betrag']):8.2f}" if r["betrag"] is not None else "    none"
            print(f"    id {r['id']:<5} datum {str(d or '—'):<10} betrag {amt} → fuer {fy}-{fm}   [{conf}]")
            for w in why:
                print(f"        · {w}")

    print("\n" + "-" * 76)
    print("4. AMBIGUOUS / PROBLEM ROWS")
    print(f"   missing tenancy    : {[r['id'] for r in todo if not r['tenancy_id']]}")
    print(f"   missing date       : {[r['id'] for r in todo if r['datum'] is None]}")
    print(f"   missing/0 amount   : {[r['id'] for r in todo if r['betrag'] is None or float(r['betrag'] or 0) <= 0]}")
    print(f"   future-dated       : {[r['id'] for r in todo if r['datum'] and r['datum'] > TODAY]}")
    dups = {k: v for k, v in by_ym.items() if len(v) > 1}
    print(f"   same tenant+month  : {len(dups)} group(s)")
    for (tid, y, m), rs in dups.items():
        nm = tens[tid]["mieter_name"] if tid in tens else "?"
        print(f"      {nm} {y}-{m:02d}: ids {[r['id'] for r in rs]} amounts {[float(r['betrag'] or 0) for r in rs]}")

    print("\n" + "-" * 76)
    print("5. BEFORE / AFTER — would any DEBT change?   (only HIGH rows are applied)")
    print()
    changed = []
    for tid, t in tens.items():
        before, bm = open_debt(t)
        sim = dict(t)
        excs = {e["ym"]: e for e in exc_list(t)}
        for r in high_by_ten.get(tid, []):
            y, m = r["datum"].year, r["datum"].month
            new = simulate_payment(t, y, m, round(float(r["betrag"]), 2))
            if new:
                excs["%04d-%02d" % (y, m)] = new
        sim["offene_monate"] = json.dumps(list(excs.values())) if excs else None
        after, am = open_debt(sim)
        mark = "CHANGED" if abs(after - before) > 0.005 else "unchanged"
        if mark == "CHANGED":
            changed.append((t, before, after, high_by_ten.get(tid, [])))
        print(f"   {t['mieter_name']:<22} debt BEFORE {before:9.2f} → AFTER {after:9.2f}   {mark}"
              f"   ({len(high_by_ten.get(tid, []))} HIGH rows)")
        if before > 0:
            print(f"      open months now: {[f'{y}-{m:02d}: {o:.2f}' for (y, m, o) in bm]}")

    print("\n   WHY:")
    if not changed:
        print("     no tenant's debt changes — the HIGH rows land on months that carry no")
        print("     reported problem (Dauerzahlung already counts them as paid), so settling")
        print("     them with money changes nothing.")
    for t, b, a, rows in changed:
        print(f"     {t['mieter_name']}: {b:.2f} → {a:.2f}")
        for r in rows:
            y, m = r["datum"].year, r["datum"].month
            print(f"        payment id {r['id']} ({float(r['betrag']):.2f}) → {y}-{m:02d} "
                  f"(Soll {monat_soll(t, y, m):.2f}) settles that month's reported problem")

    print("\n" + "=" * 76)
    print("SUMMARY")
    print(f"   HIGH   : {cnt[HIGH]:>3} rows — safe to migrate automatically")
    print(f"   MEDIUM : {cnt[MED]:>3} rows — NOT migrated, need your decision")
    print(f"   LOW    : {cnt[LOW]:>3} rows — NOT migrated, cannot be inferred")
    print(f"   tenants whose debt would change: {len(changed)}")
    print("\n   NOTHING WAS WRITTEN. No migration. No deployment.")
    print("=" * 76)
    c.close()


main()
