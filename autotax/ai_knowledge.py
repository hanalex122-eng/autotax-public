"""AI Tax Knowledge Cache Layer.

Amac: Claude API cagrilarini azaltmak.
- Kullanici soru sorar -> once cache'e bakilir
- Benzerlik skoru >= THRESHOLD -> cache'ten don ($0)
- Yoksa Claude'a sor -> cevabi kaydet -> don ($0.012)

V1 — pure PostgreSQL, vector DB yok:
- pg_trgm similarity (extension)
- Keyword Jaccard
- Combined score = max(trigram, jaccard)

Kategorize / normalize / keyword extraction klasik teknikler — regex + sozluk.

Ileride RAG/embedding upgrade icin embedding field hazir bekliyor.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from autotax.models import AIKnowledgeEntry

logger = logging.getLogger("autotax.ai_knowledge")

# ─────────────────────────────────────────────
# Normalization & keyword extraction
# ─────────────────────────────────────────────

# Almanca stopwords (yaygin gereksiz kelimeler)
GERMAN_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines",
    "einem", "einen", "und", "oder", "aber", "doch", "weil", "wenn", "als",
    "wie", "wo", "was", "wer", "warum", "ist", "sind", "war", "waren",
    "wird", "werden", "wurde", "wurden", "haben", "hat", "hatte", "hatten",
    "kann", "konnte", "können", "muss", "musste", "müssen", "soll", "sollte",
    "sollen", "darf", "durfte", "dürfen", "will", "wollte", "wollen", "möchte",
    "möchten", "mich", "mir", "ich", "du", "dich", "dir", "er", "sie", "es",
    "wir", "ihr", "uns", "euch", "ihm", "ihnen", "mein", "meine", "dein",
    "deine", "sein", "seine", "ihr", "ihre", "in", "im", "an", "am", "auf",
    "für", "von", "vom", "zu", "zum", "zur", "bei", "beim", "mit", "nach",
    "über", "unter", "durch", "ohne", "gegen", "um", "bis", "ab", "aus",
    "nicht", "kein", "keine", "auch", "noch", "nur", "schon", "sehr", "ganz",
    "viel", "viele", "mehr", "weniger", "wo", "doch", "dass", "dann", "denn",
    "so", "zwar", "etwa", "etwas", "irgendwie", "irgendwo", "hier", "da",
    "bitte", "danke", "ja", "nein",
}

# Almanca vergi synonyms — esanlamlilar tek kelimeye normalize edilir
GERMAN_TAX_SYNONYMS = {
    # Miete varyantlari
    "buromiete": "miete",
    "büromiete": "miete",
    "raummiete": "miete",
    "gewerbemiete": "miete",
    "geschaftsmiete": "miete",
    "geschäftsmiete": "miete",
    # KFZ
    "auto": "kfz",
    "wagen": "kfz",
    "fahrzeug": "kfz",
    "firmenwagen": "kfz",
    "dienstwagen": "kfz",
    "pkw": "kfz",
    # Absetzbar varyantlari
    "abzugsfahig": "absetzbar",
    "abzugsfähig": "absetzbar",
    "abziehbar": "absetzbar",
    "betriebsausgabe": "absetzbar",
    "betriebsausgaben": "absetzbar",
    "geltend machen": "absetzbar",
    # Versicherung
    "vers": "versicherung",
    "krankenkasse": "krankenversicherung",
    "kv": "krankenversicherung",
    "rv": "rentenversicherung",
    "rente": "rentenversicherung",
    "rentenkasse": "rentenversicherung",
    # Bewirtung
    "essen": "bewirtung",
    "restaurant": "bewirtung",
    "geschaeftsessen": "bewirtung",
    "geschäftsessen": "bewirtung",
    "kundenbewirtung": "bewirtung",
    # Software
    "saas": "software",
    "abo": "software",
    "lizenz": "software",
    "app": "software",
    # USt
    "ust": "umsatzsteuer",
    "mwst": "umsatzsteuer",
    "mehrwertsteuer": "umsatzsteuer",
    "vorsteuer": "umsatzsteuer",
    # Homeoffice
    "heimbüro": "homeoffice",
    "heimbuero": "homeoffice",
    "arbeitszimmer": "homeoffice",
    "homeoffice-pauschale": "homeoffice",
    # AfA
    "abschreibung": "afa",
    "abschreiben": "afa",
    "anschaffung": "afa",
    "afatabelle": "afa",
    # Reise
    "reisen": "reise",
    "geschaftsreise": "reise",
    "geschäftsreise": "reise",
    "verpflegungspauschale": "reise",
    "uebernachtung": "reise",
    "übernachtung": "reise",
    # Geschenk
    "geschenke": "geschenk",
    "kundengeschenk": "geschenk",
    # Lohn
    "gehalt": "lohn",
    "personal": "lohn",
    "minijob": "lohn",
    "mini-job": "lohn",
}

# Kategori tahmin sozlugu — keyword -> kategori
CATEGORY_KEYWORDS = {
    "Bewirtung": ["bewirtung", "essen", "restaurant", "kaffee", "café", "cafe", "kundenessen"],
    "KFZ": ["kfz", "auto", "fahrtenbuch", "1%-regelung", "tankstelle", "benzin", "diesel", "pendlerpauschale"],
    "Miete": ["miete", "vermieter", "hausverwaltung", "nebenkosten", "kaltmiete", "warmmiete"],
    "Versicherung": ["versicherung", "krankenversicherung", "rentenversicherung", "haftpflicht",
                     "berufsunfaehig", "berufsunfähig"],
    "Software": ["software", "abo", "lizenz", "saas", "cloud", "app", "tool", "claude", "openai", "github"],
    "Homeoffice": ["homeoffice", "arbeitszimmer", "arbeitsplatz zuhause"],
    "Reise": ["reise", "uebernachtung", "übernachtung", "verpflegung", "flug", "bahn", "taxi", "hotel"],
    "AfA": ["afa", "abschreibung", "anschaffung", "anlagevermoegen", "anlagevermögen", "investition"],
    "Geschenk": ["geschenk", "praesent", "präsent", "kundengeschenk"],
    "Lohn": ["lohn", "gehalt", "minijob", "mini-job", "538€", "midijob", "personalkosten"],
    "Sozialabgaben": ["sozialabgaben", "knappschaft", "sv-beitrag"],
    "Umsatzsteuer": ["umsatzsteuer", "ust", "mwst", "vorsteuer", "mehrwertsteuer", "ustva"],
    "Privatanteil": ["privatanteil", "privat", "private nutzung"],
    "Buero": ["buero", "büro", "büromaterial", "papier", "stift"],
    "Material": ["material", "wareneinkauf", "rohstoff"],
}


def normalize_question(text: str) -> tuple[str, list[str]]:
    """Soruyu normalize et + keywords cikar.

    Donen: (normalized_string, keywords_list)

    Adimlar:
    1. lowercase
    2. noktalama temizle
    3. tokenize
    4. stopword cikart
    5. synonym map uygula
    6. tekrar listele, alfabetik sirala (idempotent normalize)
    7. keywords return
    """
    if not text:
        return ("", [])
    t = text.lower().strip()
    # Noktalama temizle (UTF-8 friendly)
    t = re.sub(r"[^\w\säöüß-]", " ", t, flags=re.UNICODE)
    # Tokenize
    tokens = [w for w in re.split(r"\s+", t) if w]
    # Stopwords cikart + cok kisa kelimeler
    tokens = [w for w in tokens if w not in GERMAN_STOPWORDS and len(w) >= 2]
    # Synonym normalize
    tokens = [GERMAN_TAX_SYNONYMS.get(w, w) for w in tokens]
    # Tekrar tekrar gelen kelimeleri uniq
    seen = set()
    unique = []
    for t2 in tokens:
        if t2 not in seen:
            seen.add(t2)
            unique.append(t2)
    # Alfabetik sirala — ayni anlam farkli kelime siralamasi
    normalized = " ".join(sorted(unique))
    return normalized, unique


def detect_category(keywords: list[str]) -> Optional[str]:
    """Keyword listesinden vergi kategorisi tahmin et."""
    scores: dict[str, int] = {}
    for cat, cat_keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for k in keywords if k in cat_keywords)
        if score > 0:
            scores[cat] = score
    if not scores:
        return None
    return max(scores.items(), key=lambda x: x[1])[0]


def _jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard benzerligi: |intersection| / |union|."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union > 0 else 0.0


# ─────────────────────────────────────────────
# Cache lookup + save
# ─────────────────────────────────────────────

MATCH_THRESHOLD = 0.55  # 0.0-1.0 (0.55 = ortalama benzerlik kabul edilebilir)


def find_cached_answer(db: Session, question: str, language: str = "de",
                        tax_year: Optional[int] = None) -> Optional[dict]:
    """Cache'te eslesen cevabi bul. Yoksa None.

    Donen dict: {entry_id, original_question, answer, score, source_model,
                 confidence, usage_count, last_used_at, cache_hit: True}
    """
    norm, keywords = normalize_question(question)
    if not norm or len(keywords) < 1:
        return None

    # PostgreSQL: pg_trgm similarity ile filtre + sort
    # SQLite: sadece exact normalized match (basit fallback)
    is_postgres = db.bind.dialect.name == "postgresql"
    candidates: list[AIKnowledgeEntry] = []

    if is_postgres:
        try:
            stmt = sql_text("""
                SELECT id, original_question, normalized_question, answer,
                       category, keywords, source_model, confidence,
                       usage_count, last_used_at, tax_year,
                       similarity(normalized_question, :nq) AS sim
                FROM ai_knowledge
                WHERE is_deprecated = false
                  AND language = :lang
                  AND similarity(normalized_question, :nq) > 0.3
                ORDER BY sim DESC
                LIMIT 5
            """)
            rows = db.execute(stmt, {"nq": norm, "lang": language}).fetchall()
            ids = [r.id for r in rows]
            if ids:
                candidates = db.query(AIKnowledgeEntry).filter(
                    AIKnowledgeEntry.id.in_(ids)
                ).all()
                # Order korunsun
                id_to_sim = {r.id: float(r.sim) for r in rows}
                candidates.sort(key=lambda c: -id_to_sim.get(c.id, 0))
        except Exception:
            logger.exception("pg_trgm search failed, falling back")

    if not candidates:
        # Fallback: exact normalized match
        candidates = db.query(AIKnowledgeEntry).filter(
            AIKnowledgeEntry.normalized_question == norm,
            AIKnowledgeEntry.is_deprecated == False,
            AIKnowledgeEntry.language == language,
        ).limit(3).all()

    # En iyi adayi sec — combined score
    best = None
    best_score = 0.0
    for c in candidates:
        # Keywords Jaccard
        c_keywords = []
        try:
            c_keywords = json.loads(c.keywords or "[]")
        except Exception:
            pass
        j = _jaccard(keywords, c_keywords)
        # Trigram (postgres) yoksa basit string overlap
        if is_postgres:
            try:
                stmt = sql_text("SELECT similarity(:a, :b) AS s")
                row = db.execute(stmt, {"a": norm, "b": c.normalized_question}).fetchone()
                trig = float(row.s) if row else 0.0
            except Exception:
                trig = 0.0
        else:
            # Basit fallback: ortak token / max token
            ct = set(c.normalized_question.split())
            nt = set(norm.split())
            trig = len(ct & nt) / max(len(ct), len(nt), 1)
        score = max(j, trig)
        if score > best_score:
            best_score = score
            best = c

    if not best or best_score < MATCH_THRESHOLD:
        return None

    # Tax year mismatch — degisik yil ise cache miss kabul et
    if tax_year and best.tax_year and best.tax_year != tax_year:
        return None

    # Hit — usage_count artir, last_used_at guncelle
    best.usage_count += 1
    best.last_used_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "entry_id": best.id,
        "original_question": best.original_question,
        "answer": best.answer,
        "category": best.category,
        "score": round(best_score, 3),
        "source_model": best.source_model,
        "confidence": best.confidence,
        "usage_count": best.usage_count,
        "manually_verified": best.manually_verified,
        "cache_hit": True,
    }


def save_to_cache(db: Session, question: str, answer: str, *,
                   user_id: Optional[int] = None,
                   source_model: str = "claude-opus-4-7",
                   confidence: float = 0.9,
                   language: str = "de",
                   tax_year: Optional[int] = None) -> int:
    """AI cevabini cache'e kaydet. Yeni ID doner."""
    norm, keywords = normalize_question(question)
    if not norm:
        return 0
    cat = detect_category(keywords)
    entry = AIKnowledgeEntry(
        original_question=question[:2000],
        normalized_question=norm[:500],
        answer=answer[:8000],
        category=cat,
        keywords=json.dumps(keywords),
        language=language,
        source_model=source_model,
        confidence=confidence,
        tax_year=tax_year,
        first_asked_by=user_id,
        usage_count=0,
    )
    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)
        logger.info("Cached AI answer: id=%s cat=%s norm=%r", entry.id, cat, norm[:100])
        return entry.id
    except Exception:
        db.rollback()
        logger.exception("Failed to save cache entry")
        return 0


def get_cache_stats(db: Session) -> dict:
    """Admin panel icin istatistikler."""
    from sqlalchemy import func
    total = db.query(func.count(AIKnowledgeEntry.id)).scalar() or 0
    total_uses = db.query(func.coalesce(func.sum(AIKnowledgeEntry.usage_count), 0)).scalar() or 0
    deprecated = db.query(func.count(AIKnowledgeEntry.id)).filter(
        AIKnowledgeEntry.is_deprecated == True
    ).scalar() or 0
    verified = db.query(func.count(AIKnowledgeEntry.id)).filter(
        AIKnowledgeEntry.manually_verified == True
    ).scalar() or 0
    # Top kategori
    cat_rows = db.query(
        AIKnowledgeEntry.category, func.count(AIKnowledgeEntry.id),
        func.sum(AIKnowledgeEntry.usage_count),
    ).filter(AIKnowledgeEntry.category.isnot(None)).group_by(
        AIKnowledgeEntry.category
    ).all()
    by_category = [
        {"category": c, "entries": int(n), "total_uses": int(u or 0)}
        for c, n, u in cat_rows
    ]
    by_category.sort(key=lambda x: -x["total_uses"])
    # Cache hit rate hesabi: kullanim toplami / (kullanim + entries) approximation
    # Daha dogru: kullanim toplami = total_uses; toplam soru = total_uses + entries
    total_questions = total_uses + total
    hit_rate = (total_uses / total_questions * 100) if total_questions > 0 else 0.0
    # Maliyet tasarrufu (Opus 4.7 ~$0.012/soru)
    saved_dollars = total_uses * 0.012
    return {
        "total_entries": int(total),
        "total_uses": int(total_uses),
        "deprecated": int(deprecated),
        "manually_verified": int(verified),
        "estimated_hit_rate_pct": round(hit_rate, 1),
        "estimated_saved_usd": round(saved_dollars, 2),
        "by_category": by_category,
    }
