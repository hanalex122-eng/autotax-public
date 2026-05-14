"""Almanya vergi takvimi — Steuer deadline reminders.

Sabit vade takvimi ve kullaniciya kisisel hatirlatma. Reminder kodlari:
  7d / 3d / 1d / on_day / overdue (ilk gun gecince)

Dedup: SteuerReminderLog tablosunda (user_id, deadline_type, deadline_date,
code) tuple'i kayitli olursa ayni reminder atlanir. Ust degisirse (yeni
ay) yeni deadline_date olur, reminder akisi tekrar baslar.

Kleinunternehmer (§19 UStG) USt'den muaf — UST reminder'i atlanir.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Iterable
from calendar import monthrange

from autotax.db import SessionLocal
from autotax.models import User, SteuerReminderLog, SteuerReminder
from autotax.reminders import send_telegram

logger = logging.getLogger("autotax.steuer")


# ───────────────────────────────────────────────────────────────────
# Deadline takvimi
# ───────────────────────────────────────────────────────────────────

DEADLINE_LABELS_DE = {
    "ust": "USt-Voranmeldung",
    "ust_q": "USt-Voranmeldung (Quartal)",
    "est": "ESt-Vorauszahlung",
    "gewst": "GewSt-Vorauszahlung",
    "jahres": "Jahressteuererklärung",
}


def next_ust_monthly(today: date) -> date:
    """USt-Voranmeldung aylik — her ayin 10'u (onceki ay icin).
    Bugun 10'undan sonra ise sonraki ayin 10'u."""
    if today.day <= 10:
        return today.replace(day=10)
    # Sonraki ay
    if today.month == 12:
        return today.replace(year=today.year + 1, month=1, day=10)
    return today.replace(month=today.month + 1, day=10)


def next_ust_quarterly(today: date) -> date:
    """USt-Voranmeldung ceyreklik — 10 Nisan / Temmuz / Ekim / Ocak."""
    quarters = [(1, 10), (4, 10), (7, 10), (10, 10)]  # ay, gun
    year = today.year
    for m, d in quarters:
        candidate = date(year, m, d)
        if candidate >= today:
            return candidate
    return date(year + 1, 1, 10)  # sonraki yil ocak


def next_est(today: date) -> date:
    """ESt-Vorauszahlung — 10 Mart / Haziran / Eylul / Aralik."""
    quarters = [(3, 10), (6, 10), (9, 10), (12, 10)]
    year = today.year
    for m, d in quarters:
        candidate = date(year, m, d)
        if candidate >= today:
            return candidate
    return date(year + 1, 3, 10)


def next_gewst(today: date) -> date:
    """GewSt-Vorauszahlung — 15 Subat / Mayis / Agustos / Kasim."""
    quarters = [(2, 15), (5, 15), (8, 15), (11, 15)]
    year = today.year
    for m, d in quarters:
        candidate = date(year, m, d)
        if candidate >= today:
            return candidate
    return date(year + 1, 2, 15)


def next_jahresmeldung(today: date) -> date:
    """Jahressteuererklarung — 31 Temmuz (bir onceki yil icin).
    2018'den beri 31 Mayis'tan 31 Temmuz'a uzatildi."""
    candidate = date(today.year, 7, 31)
    if candidate >= today:
        return candidate
    return date(today.year + 1, 7, 31)


def build_deadlines_for_user(today: date, user_subs: Optional[list] = None,
                              is_klein: bool = False) -> list[dict]:
    """Tek kullanici icin yaklasan deadline listesi.
    Default: hepsi (Kleinunternehmer'a USt yok). Kullanici muteyleyebilir
    user.steuer_subscriptions alani ile."""
    if user_subs is None:
        # Default: hepsi (Klein'a USt yok)
        user_subs = ["est", "gewst", "jahres"]
        if not is_klein:
            user_subs.append("ust")

    deadlines = []
    if "ust" in user_subs and not is_klein:
        # Aylik default — kullanici 'ust_q' istiyorsa ceyreklik
        if "ust_q" in user_subs:
            deadlines.append({"type": "ust", "label": DEADLINE_LABELS_DE["ust_q"],
                              "date": next_ust_quarterly(today)})
        else:
            deadlines.append({"type": "ust", "label": DEADLINE_LABELS_DE["ust"],
                              "date": next_ust_monthly(today)})
    if "est" in user_subs:
        deadlines.append({"type": "est", "label": DEADLINE_LABELS_DE["est"],
                          "date": next_est(today)})
    if "gewst" in user_subs:
        deadlines.append({"type": "gewst", "label": DEADLINE_LABELS_DE["gewst"],
                          "date": next_gewst(today)})
    if "jahres" in user_subs:
        deadlines.append({"type": "jahres", "label": DEADLINE_LABELS_DE["jahres"],
                          "date": next_jahresmeldung(today)})

    deadlines.sort(key=lambda d: d["date"])
    return deadlines


def determine_steuer_code(deadline_d: date, today: date) -> Optional[str]:
    """Hangi reminder code uygulanacak — 7d / 3d / 1d / on_day / overdue."""
    diff = (deadline_d - today).days
    if diff == 7:
        return "7d"
    if diff == 3:
        return "3d"
    if diff == 1:
        return "1d"
    if diff == 0:
        return "on_day"
    if diff == -1:
        return "overdue"
    return None


# ───────────────────────────────────────────────────────────────────
# Cron tick
# ───────────────────────────────────────────────────────────────────

def _format_steuer_msg(label: str, deadline_d: date, code: str, user_email: str) -> str:
    code_de = {
        "7d": "in 7 Tagen", "3d": "in 3 Tagen", "1d": "morgen",
        "on_day": "HEUTE", "overdue": "ÜBERFÄLLIG (gestern)",
    }.get(code, code)
    if code == "overdue":
        head = "🚨 <b>STEUER-FRIST ÜBERFÄLLIG</b>"
    elif code == "on_day":
        head = "🔴 <b>STEUER-FRIST HEUTE</b>"
    elif code == "1d":
        head = "🟠 <b>Steuer-Frist morgen</b>"
    else:
        head = "📅 <b>Steuer-Frist Erinnerung</b>"
    return (
        f"{head}\n\n"
        f"<b>{label}</b>\n"
        f"Fällig: {deadline_d.strftime('%d.%m.%Y')} ({code_de})\n"
        f"Kunde: {user_email}\n\n"
        f"<i>Bitte rechtzeitig einreichen oder Bescheid an deinen Steuerberater.</i>"
    )


async def process_steuer_reminders() -> dict:
    """Tum kullanicilarin yaklasan vergi vadelerini tarar, code uygulanan
    deadline'lar icin Telegram reminder gonderir. Dedup: SteuerReminderLog."""
    import json as _json
    today = date.today()
    db = SessionLocal()
    stats = {"checked": 0, "sent": 0, "skipped_dedup": 0}
    try:
        users = db.query(User).all()
        stats["checked"] = len(users)

        for u in users:
            try:
                # Admin hesaplari skip — sen kendi reminder'ini almak istemezsin
                # (istersen ADMIN_EMAILS'tan cikar)
                user_subs = None
                if u.steuer_subscriptions:
                    try:
                        user_subs = _json.loads(u.steuer_subscriptions)
                    except Exception:
                        pass

                is_klein = bool(getattr(u, "is_kleinunternehmer", False))
                deadlines = build_deadlines_for_user(today, user_subs, is_klein)

                for dl in deadlines:
                    code = determine_steuer_code(dl["date"], today)
                    if code is None:
                        continue
                    # Dedup: ayni (user, type, date, code) varsa atla
                    existing = db.query(SteuerReminderLog).filter(
                        SteuerReminderLog.user_id == u.id,
                        SteuerReminderLog.deadline_type == dl["type"],
                        SteuerReminderLog.deadline_date == dl["date"].isoformat(),
                        SteuerReminderLog.code == code,
                    ).first()
                    if existing:
                        stats["skipped_dedup"] += 1
                        continue

                    msg = _format_steuer_msg(dl["label"], dl["date"], code, u.email)
                    if await send_telegram(msg):
                        stats["sent"] += 1
                    # Log her halukarda — gonderim hatasi olsa bile dedup et
                    # (yoksa botun retry'si spam'e cevirir)
                    db.add(SteuerReminderLog(
                        user_id=u.id,
                        deadline_type=dl["type"],
                        deadline_date=dl["date"].isoformat(),
                        code=code,
                    ))

            except Exception:
                logger.exception("[STEUER] error processing user %s", u.id)

        db.commit()
        if stats["sent"] or stats["skipped_dedup"]:
            logger.info("[STEUER] cycle: %s", stats)
    except Exception:
        db.rollback()
        logger.exception("[STEUER] fatal")
    finally:
        db.close()
    return stats


def ensure_reminders_for_user(user_id: int) -> int:
    """Gelecek 12 ayın deterministic vergi vadelerini DB'ye UPSERT eder.
    UNIQUE (user_id, type, due_date) sayesinde idempotent — varsa atlar.
    Döndürür: kaç yeni satır eklendi."""
    import json as _json
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        if not u:
            return 0
        user_subs = None
        if u.steuer_subscriptions:
            try:
                user_subs = _json.loads(u.steuer_subscriptions)
            except Exception:
                pass
        is_k = bool(getattr(u, "is_kleinunternehmer", False))

        # 12 ayın deterministic deadline'larını hesapla (build_deadlines_for_user
        # bir günlük slice veriyor — 12 ay için döngü ile birden çok kez çağırırız)
        today = date.today()
        end_window = today + timedelta(days=365)
        all_slots: list[dict] = []
        cur = today
        seen = set()
        while cur < end_window:
            for d in build_deadlines_for_user(cur, user_subs, is_k):
                key = (d["type"], d["date"])
                if key in seen:
                    continue
                if d["date"] > end_window:
                    continue
                seen.add(key)
                all_slots.append(d)
            cur = cur + timedelta(days=31)  # bir sonraki ay'a yakla

        # UPSERT
        existing = db.query(SteuerReminder).filter(
            SteuerReminder.user_id == user_id,
            SteuerReminder.due_date >= today,
        ).all()
        existing_keys = {(r.type, r.due_date) for r in existing}

        added = 0
        for slot in all_slots:
            k = (slot["type"], slot["date"])
            if k in existing_keys:
                continue
            sr = SteuerReminder(
                user_id=user_id,
                type=slot["type"],
                due_date=slot["date"],
                reminder_date=slot["date"] - timedelta(days=7),
                status="active",
                label=slot["label"],
            )
            db.add(sr)
            added += 1
        if added > 0:
            db.commit()
            logger.info("ensure_reminders: user=%s seeded=%d new slots", user_id, added)
        return added
    except Exception:
        logger.exception("ensure_reminders_for_user failed for %s", user_id)
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    finally:
        db.close()


def upcoming_for_user(user_id: int, is_klein: bool = False, limit: int = 5) -> list[dict]:
    """Kullanıcının önündeki N yaklaşan vergi vadesi — DB'den çeker.
    İlk çağrıda DB boşsa otomatik seed (ensure_reminders_for_user).
    Snooze edilmiş + done + dismissed olanlar görünmez.
    """
    today = date.today()
    db = SessionLocal()
    try:
        active = db.query(SteuerReminder).filter(
            SteuerReminder.user_id == user_id,
            SteuerReminder.status == "active",
            SteuerReminder.due_date >= today,
        ).order_by(SteuerReminder.due_date.asc()).limit(limit).all()

        if not active:
            # İlk kullanım — seed yap ve tekrar çek
            db.close()
            ensure_reminders_for_user(user_id)
            db = SessionLocal()
            active = db.query(SteuerReminder).filter(
                SteuerReminder.user_id == user_id,
                SteuerReminder.status == "active",
                SteuerReminder.due_date >= today,
            ).order_by(SteuerReminder.due_date.asc()).limit(limit).all()

        out = []
        for r in active:
            diff = (r.due_date - today).days
            out.append({
                "id": r.id,
                "type": r.type,
                "label": r.label or DEADLINE_LABELS_DE.get(r.type, r.type),
                "date": r.due_date.isoformat(),
                "days_until": diff,
                "status": r.status,
                "snoozed_until": r.snoozed_until.isoformat() if r.snoozed_until else None,
            })
        return out
    finally:
        db.close()
