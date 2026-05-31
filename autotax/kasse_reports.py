"""Kasa MVP (Sprint 2) — PDF report generation.

daily/weekly/monthly reports rendered from the SAME aggregation source
(kasse_service.summarize) → numbers always match the dashboard. PDF bytes are
stored in R2 (or local fallback) and tracked in cash_reports. reportlab is
imported lazily so the module loads even where reportlab is absent.
"""
from __future__ import annotations

import io
from datetime import date, datetime

from autotax import kasse_r2, kasse_service
from autotax.models import CashReport


def _summary_for(db, user_id: int, report_type: str, period: str) -> dict:
    if report_type == "daily":
        d = datetime.strptime(period, "%Y-%m-%d").date()
        return kasse_service.daily(db, user_id, d)
    if report_type == "weekly":
        d = datetime.strptime(period, "%Y-%m-%d").date()
        return kasse_service.weekly(db, user_id, d)
    if report_type == "monthly":
        y, m = int(period[:4]), int(period[5:7])
        return kasse_service.monthly(db, user_id, y, m)
    raise ValueError("report_type must be daily|weekly|monthly")


def _render_pdf(report_type: str, summary: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Kassenbuch {report_type}")
    styles = getSampleStyleSheet()
    el = [
        Paragraph(f"Kassenbuch-Auszug — {report_type.capitalize()}", styles["Title"]),
        Paragraph(f"Zeitraum: {summary['period_start']} – {summary['period_end']}", styles["Normal"]),
        Spacer(1, 12),
    ]
    totals = [
        ["Position", "Betrag (EUR)"],
        ["Einnahmen", f"{summary['total_income']:.2f}"],
        ["Ausgaben", f"{summary['total_expense']:.2f}"],
        ["Gewinn", f"{summary['profit']:.2f}"],
        ["USt vereinnahmt", f"{summary['vat_collected']:.2f}"],
        ["Vorsteuer", f"{summary['vat_paid']:.2f}"],
        ["Buchungen", str(summary['entry_count'])],
    ]
    t = Table(totals, hAlign="LEFT", colWidths=[220, 120])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    el.append(t)
    el.append(Spacer(1, 16))
    if summary.get("by_category"):
        el.append(Paragraph("Kategorieverteilung", styles["Heading2"]))
        rows = [["Kategorie", "Art", "Betrag (EUR)"]]
        for c in summary["by_category"]:
            rows.append([c["name"], c["kind"], f"{c['total']:.2f}"])
        ct = Table(rows, hAlign="LEFT", colWidths=[220, 90, 120])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]))
        el.append(ct)
    el.append(Spacer(1, 20))
    el.append(Paragraph("Kassenbuch-Auszug — keine steuerberatende Beratung (StBerG).", styles["Italic"]))
    doc.build(el)
    return buf.getvalue()


def build_report(db, user_id: int, report_type: str, period: str) -> tuple[bytes, dict]:
    summary = _summary_for(db, user_id, report_type, period)
    pdf = _render_pdf(report_type, summary)
    return pdf, summary


def store_report(db, user_id: int, report_type: str, summary: dict, pdf: bytes) -> CashReport:
    stored = kasse_r2.put_image(user_id, pdf, "application/pdf")
    rep = CashReport(
        user_id=user_id, report_type=report_type,
        period_start=date.fromisoformat(summary["period_start"]),
        period_end=date.fromisoformat(summary["period_end"]),
        r2_key=stored["key"],
        total_income=summary["total_income"], total_expense=summary["total_expense"], profit=summary["profit"],
        created_at=datetime.utcnow(),
    )
    db.add(rep); db.commit(); db.refresh(rep)
    return rep
