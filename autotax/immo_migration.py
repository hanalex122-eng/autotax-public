"""PHASE 1 — READ-ONLY migration ANALYZER: Soll−Ist arrears → Exception Engine.

DRY RUN + CLASSIFY + SNAPSHOT + REPORT only. Writes NOTHING to the database — no
INSERT / UPDATE / DELETE. Any write attempt is a bug. APPLY and VERIFY are separate
later phases. The waterfall preserves the OLD year-level total exactly:
    Σ exceptions(year) == max(0, Σ Soll_due − Σ Ist)   (the migration invariant)

Classification:
  GREEN  invariant holds AND data reliable           → auto-migratable (Phase 3)
  YELLOW invariant holds BUT ambiguous data           → NEVER written, manual review
         (Ist=0, soft-deleted payments, negative betrag, date anomaly)
  RED    invariant BROKEN                              → migration FAILS (no partial apply)
"""
import json
from datetime import date, datetime, timezone

from autotax.models import ImmoTenancy, ImmoRent
from autotax import immo_api as A


def _classify(invariant_ok, flags, new_total=0.0, old_arrears=0.0):
    """Decide GREEN / YELLOW / RED. RED (invariant broken) can only arise from a code
    bug or data anomaly — the waterfall preserves the total by construction — so it is
    a hard STOP signal, not an expected data state."""
    if not invariant_ok:
        return "RED", "Invariant gebrochen (new=%.2f != old=%.2f)" % (new_total, old_arrears)
    if flags:
        return "YELLOW", "; ".join(flags)
    return "GREEN", "Zahlungen plausibel, Invariant ok"


def _first_active_year(t, today):
    vy = t.von.year if t.von else today.year
    return min(vy, today.year)


def _analyze_tenant(db, uid, t, today):
    """Pure read: compute OLD Soll−Ist arrears + the waterfall exception list +
    classification + invariant. NO writes."""
    rents_all = db.query(ImmoRent).filter(ImmoRent.tenancy_id == t.id, ImmoRent.user_id == uid).all()
    rents = [r for r in rents_all if not getattr(r, "is_deleted", False) and r.datum]
    deleted = [r for r in rents_all if getattr(r, "is_deleted", False)]

    exceptions = []
    soll_total = ist_total = old_arrears = new_total = 0.0
    for y in range(_first_active_year(t, today), today.year + 1):
        last = 12 if y < today.year else today.month
        due = [m for m in range(1, last + 1) if A._tenancy_active_in_month(t, y, m)]
        soll_by_m = {m: A._monat_soll(t, y, m) for m in due}
        soll_y = round(sum(soll_by_m.values()), 2)
        ist_y = round(sum(float(r.betrag or 0) for r in rents if r.datum.year == y), 2)
        soll_total += soll_y
        ist_total += ist_y
        old_arrears += max(0.0, round(soll_y - ist_y, 2))
        remaining = ist_y                                   # waterfall: allocate Ist to months in order
        for m in due:
            soll_m = soll_by_m[m]
            if soll_m <= 0:
                continue
            ym = "%04d-%02d" % (y, m)
            if remaining >= soll_m:
                remaining -= soll_m                         # month covered → no exception
            elif remaining <= 0.005:
                exceptions.append({"ym": ym, "typ": "unpaid"}); new_total += soll_m
            else:
                offen = round(soll_m - remaining, 2)
                exceptions.append({"ym": ym, "typ": "partial", "offen": offen}); new_total += offen
                remaining = 0.0

    soll_total = round(soll_total, 2); ist_total = round(ist_total, 2)
    old_arrears = round(old_arrears, 2); new_total = round(new_total, 2)
    invariant_ok = abs(new_total - old_arrears) < 0.01

    flags = []
    if ist_total == 0 and old_arrears > 0:
        flags.append("Ist=0 (keine Zahlungsdatensätze) → Schuldenwand-Risiko")
    if deleted:
        flags.append("%d gelöschte Zahlung(en) in Historie" % len(deleted))
    if any(float(r.betrag or 0) < 0 for r in rents):
        flags.append("negative Zahlung")
    if any((t.von and r.datum < t.von) or (t.bis and r.datum > t.bis) for r in rents):
        flags.append("Zahlungsdatum außerhalb Mietzeitraum")

    cls, reason = _classify(invariant_ok, flags, new_total, old_arrears)

    return {
        "tenant_id": t.id, "tenant_name": t.mieter_name,
        "old_soll": soll_total, "old_ist": ist_total, "old_arrears": old_arrears,
        "new_exceptions": exceptions, "new_exception_total": new_total,
        "classification": cls, "reason": reason, "invariant_ok": bool(invariant_ok),
    }


def dry_run(db, uid, today=None):
    """READ-ONLY analysis of every active tenant of `uid`. Returns the snapshot dict.
    Performs NO writes."""
    today = today or date.today()
    tens = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, A._notdel(ImmoTenancy)).all()
    rows = [_analyze_tenant(db, uid, t, today) for t in tens]
    g = [r for r in rows if r["classification"] == "GREEN"]
    yel = [r for r in rows if r["classification"] == "YELLOW"]
    red = [r for r in rows if r["classification"] == "RED"]
    summary = {
        "tenants": len(rows), "green": len(g), "yellow": len(yel), "red": len(red),
        "old_arrears_total": round(sum(r["old_arrears"] for r in rows), 2),
        "green_total": round(sum(r["old_arrears"] for r in g), 2),
        "yellow_total": round(sum(r["old_arrears"] for r in yel), 2),
        "red_total": round(sum(r["old_arrears"] for r in red), 2),
        "migration_blocked": len(red) > 0,
    }
    return {
        "phase": "1-dry-run", "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_id": uid, "today": str(today), "tenants": rows, "summary": summary,
    }


def write_snapshot(snapshot, path):
    """Write the AUDIT snapshot to a FILE (not the DB). Makes no migration decision."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return path


def format_report(snapshot):
    s = snapshot["summary"]
    out = ["MIGRATION DRY-RUN (Phase 1, READ-ONLY) · user=%s · %s" % (snapshot["user_id"], snapshot["today"]),
           "%-22s %10s %10s %10s  %-7s %s" % ("Tenant", "OldArrears", "NewExc", "Inv", "Class", "Reason")]
    for r in snapshot["tenants"]:
        out.append("%-22s %10.2f %10.2f %10s  %-7s %s" % (
            (r["tenant_name"] or "")[:22], r["old_arrears"], r["new_exception_total"],
            "OK" if r["invariant_ok"] else "FAIL", r["classification"], r["reason"]))
    out.append("─" * 70)
    out.append("GREEN=%d  YELLOW=%d  RED=%d  | old_total=%.2f green=%.2f yellow=%.2f red=%.2f | blocked=%s" % (
        s["green"], s["yellow"], s["red"], s["old_arrears_total"], s["green_total"],
        s["yellow_total"], s["red_total"], s["migration_blocked"]))
    return "\n".join(out)
