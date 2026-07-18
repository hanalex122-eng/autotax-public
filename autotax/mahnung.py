"""Mahnung (formal payment dunning) automation.

Senin musterine kestigin INCOME faturalar (invoice_type='income') icin:
  - Mahnung 1 (kibar):     vade + 7 gun
  - Mahnung 2 (ciddi):     vade + 21 gun (Mahnung 1 + 14 gun)
  - Mahnung 3 (son uyari): vade + 35 gun (Mahnung 2 + 14 gun)
  Sonrasi: manuel inkasso (admin'e telegram alert)

PDF + Telegram alert. Email opsiyonel (SMTP yoksa skip).

Mahnung seviyesi inv.mahnung_level = 0|1|2|3 olarak DB'de saklanir.
last_mahnung_at: ardisik 14 gun siniri kontrolu icin.
"""

import io
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text as sql_text

from autotax.db import SessionLocal
from autotax.models import Invoice, User
from autotax.reminders import send_telegram, send_email

logger = logging.getLogger("autotax.mahnung")

MAHNUNG_DAYS = {1: 7, 2: 21, 3: 35}  # vade + N gun
MAHNUNG_INTERVAL_DAYS = 14  # ardisik Mahnung'lar arasi minimum bekleme


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def determine_mahnung_level(inv: Invoice, today: Optional[date] = None) -> int:
    """Bu fis icin BUGUN gonderilmesi gereken Mahnung seviyesi (0|1|2|3).
    0 = henuz gonderilmesi gereken Mahnung yok."""
    if today is None:
        today = _today_utc()
    if not inv.due_date:
        return 0
    try:
        due = datetime.strptime(inv.due_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    days_overdue = (today - due).days
    if days_overdue < MAHNUNG_DAYS[1]:
        return 0
    current_level = int(getattr(inv, "mahnung_level", 0) or 0)
    # Hangi seviyeye gelmis?
    new_level = 0
    for level in (1, 2, 3):
        if days_overdue >= MAHNUNG_DAYS[level]:
            new_level = level
    if new_level <= current_level:
        return 0  # zaten gonderildi
    # Ardisik 14 gun siniri (cron her gun calisirsa Mahnung 1 ardindan
    # 1 gun sonra Mahnung 2 olmasin)
    if inv.last_mahnung_at:
        last_d = inv.last_mahnung_at.date() if hasattr(inv.last_mahnung_at, "date") else inv.last_mahnung_at
        if (today - last_d).days < MAHNUNG_INTERVAL_DAYS and new_level > current_level + 1:
            new_level = current_level + 1  # bir seferde sadece bir seviye atla
    return new_level


# ───────────────────────────────────────────────────────────────────
# Mahnung PDF
# ───────────────────────────────────────────────────────────────────

_MAHNUNG_TEXTS = {
    1: {
        "title": "Zahlungserinnerung",
        "intro": "wir möchten Sie freundlich daran erinnern, dass die folgende Rechnung noch offen ist. Bitte begleichen Sie den Betrag innerhalb der nächsten 7 Tage.",
        "tone": "freundlich",
        "fee": 0.0,
    },
    2: {
        "title": "2. Mahnung",
        "intro": "trotz unserer Zahlungserinnerung haben wir bisher keine Zahlung von Ihnen erhalten. Bitte begleichen Sie den ausstehenden Betrag umgehend, spätestens jedoch innerhalb von 7 Tagen.",
        "tone": "ernst",
        "fee": 5.0,
    },
    3: {
        "title": "3. und letzte Mahnung",
        "intro": "trotz mehrfacher Mahnungen ist die folgende Forderung weiterhin offen. Sollten wir bis spätestens 7 Tagen nach Erhalt dieses Schreibens keine Zahlung erhalten, sehen wir uns gezwungen, ohne weitere Ankündigung das Mahn- bzw. gerichtliche Verfahren einzuleiten und die Forderung an ein Inkassobüro zu übergeben.",
        "tone": "rechtlich",
        "fee": 15.0,
    },
}


def generate_mahnung_pdf(inv: Invoice, level: int, sender_user: User) -> bytes:
    """Mahnung PDF olustur. sender_user = senin firma bilgilerin (operator).
    inv = senin musterine kestigin fatura."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.lib.units import cm
        from reportlab.lib.colors import HexColor
    except ImportError:
        raise RuntimeError("PDF generation not available (reportlab missing)")

    cfg = _MAHNUNG_TEXTS[level]
    SENDER_NAME = sender_user.full_name or os.getenv("BILLING_NAME", "AutoTax Cloud")
    SENDER_ADDR = os.getenv("BILLING_ADDRESS", "Wiesenstr. 10")
    SENDER_CITY = os.getenv("BILLING_CITY", "66115 Saarbrücken")
    SENDER_EMAIL = sender_user.email or os.getenv("BILLING_EMAIL", "")
    SENDER_IBAN = os.getenv("BILLING_IBAN", "DE00 0000 0000 0000 0000 00")
    SENDER_USTID = os.getenv("BILLING_USTID", "")

    today_str = _today_utc().strftime("%d.%m.%Y")
    due_fmt = inv.due_date or "—"
    if inv.due_date:
        try:
            due_fmt = datetime.strptime(inv.due_date[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            pass

    fee = cfg["fee"]
    base_amount = inv.total_amount or 0.0
    total_with_fee = round(base_amount + fee, 2)

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Header
    accent = HexColor("#dc2626") if level >= 2 else HexColor("#f59e0b")
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 26)
    c.drawString(2 * cm, h - 2.5 * cm, cfg["title"].upper())
    c.setFillColor(HexColor("#64748b"))
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 3.1 * cm, f"Datum: {today_str}")
    c.drawString(2 * cm, h - 3.55 * cm, f"Mahnstufe: {level} / 3")

    # Sender (Absender)
    c.setFillColor(HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, h - 5 * cm, SENDER_NAME)
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, h - 5.45 * cm, SENDER_ADDR)
    c.drawString(2 * cm, h - 5.9 * cm, SENDER_CITY)
    if SENDER_EMAIL:
        c.drawString(2 * cm, h - 6.35 * cm, f"E-Mail: {SENDER_EMAIL}")
    if SENDER_USTID:
        c.drawString(2 * cm, h - 6.8 * cm, f"USt-IdNr.: {SENDER_USTID}")

    # Recipient
    c.setFont("Helvetica-Bold", 10)
    c.drawString(12 * cm, h - 5 * cm, "Empfänger:")
    c.setFont("Helvetica", 10)
    c.drawString(12 * cm, h - 5.45 * cm, inv.vendor or "(Kunde)")
    if inv.vendor_address:
        c.drawString(12 * cm, h - 5.9 * cm, inv.vendor_address[:60])
    if inv.vendor_email:
        c.drawString(12 * cm, h - 6.35 * cm, inv.vendor_email)

    # Salutation + intro
    y = h - 9 * cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, f"Sehr geehrte Damen und Herren,")
    c.setFont("Helvetica", 10)
    y -= 0.9 * cm
    # Wrap intro paragraph
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet()
    style = styles["BodyText"]
    style.fontName = "Helvetica"
    style.fontSize = 10
    style.leading = 14
    p = Paragraph(cfg["intro"], style)
    pwidth = w - 4 * cm
    p.wrapOn(c, pwidth, 200)
    p.drawOn(c, 2 * cm, y - p.height)
    y -= p.height + 0.5 * cm

    # Invoice details box
    y -= 0.5 * cm
    c.setStrokeColor(HexColor("#cbd5e1"))
    c.setFillColor(HexColor("#f8fafc"))
    c.rect(2 * cm, y - 3 * cm, w - 4 * cm, 3 * cm, fill=1, stroke=1)
    c.setFillColor(HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2.4 * cm, y - 0.6 * cm, "Offene Rechnung")
    c.setFont("Helvetica", 10)
    c.drawString(2.4 * cm, y - 1.2 * cm, f"Rechnungs-Nr.: {inv.invoice_number or '—'}")
    c.drawString(2.4 * cm, y - 1.65 * cm, f"Rechnungsdatum: {inv.date or '—'}")
    c.drawString(2.4 * cm, y - 2.1 * cm, f"Fällig am: {due_fmt}")
    c.drawRightString(w - 2.4 * cm, y - 1.2 * cm, f"Betrag: {base_amount:.2f} EUR")
    if fee > 0:
        c.drawRightString(w - 2.4 * cm, y - 1.65 * cm, f"Mahngebühr: {fee:.2f} EUR")
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(accent)
        c.drawRightString(w - 2.4 * cm, y - 2.4 * cm, f"Gesamt: {total_with_fee:.2f} EUR")
    else:
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(accent)
        c.drawRightString(w - 2.4 * cm, y - 2.4 * cm, f"Gesamt: {base_amount:.2f} EUR")
    y -= 3.5 * cm

    # Bank info
    c.setFillColor(HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Zahlung per SEPA-Überweisung:")
    c.setFont("Helvetica", 10)
    y -= 0.5 * cm
    c.drawString(2 * cm, y, f"Empfänger: {SENDER_NAME}")
    y -= 0.45 * cm
    c.drawString(2 * cm, y, f"IBAN: {SENDER_IBAN}")
    y -= 0.45 * cm
    c.drawString(2 * cm, y, f"Verwendungszweck: {inv.invoice_number or 'Mahnung'} / Mahnung {level}")
    y -= 0.7 * cm

    # Closing
    y -= 0.5 * cm
    c.drawString(2 * cm, y, "Mit freundlichen Grüßen,")
    y -= 0.5 * cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, SENDER_NAME)

    # Footer
    c.setFillColor(HexColor("#94a3b8"))
    c.setFont("Helvetica", 8)
    c.drawString(2 * cm, 1.5 * cm, f"{SENDER_NAME} · {SENDER_ADDR} · {SENDER_CITY}")
    if SENDER_EMAIL:
        c.drawString(2 * cm, 1.1 * cm, f"E-Mail: {SENDER_EMAIL}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


# ───────────────────────────────────────────────────────────────────
# Cron tick
# ───────────────────────────────────────────────────────────────────

async def process_mahnungen() -> dict:
    """Tum kullanicilarin overdue income faturalarini tarar, gerekli
    Mahnung seviyesini hesaplar, yenisi varsa PDF + Telegram + email
    gonderir."""
    today = _today_utc()
    db = SessionLocal()
    stats = {"checked": 0, "sent": 0, "level1": 0, "level2": 0, "level3": 0,
             "inkasso_alerts": 0, "errors": 0}
    try:
        invoices = (
            db.query(Invoice)
            .filter(Invoice.invoice_type == "income")
            .filter(Invoice.payment_status != "paid")
            .filter(Invoice.due_date.isnot(None))
            .filter((Invoice.is_deleted == False) | (Invoice.is_deleted == None))
            .all()
        )
        stats["checked"] = len(invoices)

        for inv in invoices:
            try:
                new_level = determine_mahnung_level(inv, today)
                # Inkasso threshold (level 3'ten 14 gun sonra) — admin alert
                if (inv.mahnung_level >= 3 and inv.last_mahnung_at):
                    last_d = inv.last_mahnung_at.date() if hasattr(inv.last_mahnung_at, "date") else inv.last_mahnung_at
                    if (today - last_d).days >= 14 and inv.payment_status != "paid":
                        # Inkasso uyarisi (sadece bir kez — last_mahnung_at'i guncelle)
                        await send_telegram(
                            f"⚖️ <b>INKASSO empfohlen</b>\n"
                            f"Kunde: {inv.vendor or '(Kunde)'}\n"
                            f"Rechnung: {inv.invoice_number or '—'}\n"
                            f"Betrag: {inv.total_amount or 0:.2f} EUR\n"
                            f"<i>Mahnung 3 vor {((today - last_d).days)} Tagen verschickt — keine Zahlung. Manuelle Übergabe an Inkassobüro empfohlen.</i>",
                            user_id=inv.user_id, kind="mahnung",
                            ref_type="invoice", ref_id=inv.id,
                        )
                        inv.last_mahnung_at = datetime.now(timezone.utc)
                        stats["inkasso_alerts"] += 1
                        continue

                if new_level == 0:
                    continue

                # Sender (operator) bilgisi
                sender = db.query(User).filter(User.id == inv.user_id).first()
                if not sender:
                    continue

                # PDF olustur
                try:
                    pdf_bytes = generate_mahnung_pdf(inv, new_level, sender)
                except Exception as e:
                    logger.warning("[MAHNUNG] PDF gen failed for inv %s: %s", inv.id, e)
                    stats["errors"] += 1
                    continue

                # Save PDF to disk for retrieval — vault path
                try:
                    from autotax import storage
                    fname = f"mahnung-{inv.id}-stufe{new_level}.pdf"
                    storage.save_file(inv.user_id, pdf_bytes, fname)
                except Exception:
                    logger.exception("[MAHNUNG] PDF save failed (continuing)")

                # Telegram alert (operator user'a — kendi chat'i)
                cfg = _MAHNUNG_TEXTS[new_level]
                await send_telegram(
                    f"📨 <b>{cfg['title']} versandt</b>\n"
                    f"Kunde: {inv.vendor or '(Kunde)'}\n"
                    f"Rechnung-Nr: {inv.invoice_number or '—'}\n"
                    f"Betrag: {inv.total_amount or 0:.2f} EUR + {cfg['fee']:.2f} Gebühr\n"
                    f"<i>PDF wurde im Vault gespeichert.</i>",
                    user_id=inv.user_id, kind="mahnung",
                    ref_type="invoice", ref_id=inv.id,
                )

                # Email to customer (vendor_email) — Mahnung PDF eki ile
                if inv.vendor_email:
                    body = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:600px">
                    <p>Sehr geehrte Damen und Herren,</p>
                    <p>{cfg['intro']}</p>
                    <p><strong>Rechnungs-Nr:</strong> {inv.invoice_number or '—'}<br>
                    <strong>Betrag:</strong> {inv.total_amount or 0:.2f} EUR
                    {f'+ Mahngebühr {cfg["fee"]:.2f} EUR' if cfg['fee'] > 0 else ''}<br>
                    <strong>Fällig am:</strong> {inv.due_date or '—'}</p>
                    <p>Die formale Mahnung als PDF finden Sie im Anhang.</p>
                    <p>Mit freundlichen Grüßen,<br>{sender.full_name or sender.email}</p>
                    </body></html>"""
                    fname = f"Mahnung-{new_level}-{inv.invoice_number or inv.id}.pdf"
                    send_email(
                        inv.vendor_email,
                        f"{cfg['title']} — Rechnung {inv.invoice_number or ''}",
                        body,
                        attachments=[(fname, pdf_bytes, "application/pdf")],
                        user_id=inv.user_id,
                        kind=f"mahnung_l{new_level}",
                        ref_type="invoice",
                        ref_id=inv.id,
                    )

                inv.mahnung_level = new_level
                inv.last_mahnung_at = datetime.now(timezone.utc)
                stats["sent"] += 1
                stats[f"level{new_level}"] += 1

            except Exception:
                logger.exception("[MAHNUNG] error processing inv %s", inv.id)
                stats["errors"] += 1

        db.commit()
        if stats["sent"] or stats["inkasso_alerts"]:
            logger.info("[MAHNUNG] cycle: %s", stats)
    except Exception:
        db.rollback()
        logger.exception("[MAHNUNG] fatal")
    finally:
        db.close()
    return stats
