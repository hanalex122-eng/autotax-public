"""Security Hotfix SH-1c — Vault upload (/vault/{id}/upload) sertleştirmesi.

/immo/documents (SH-1a/1b) ile AYNI kural seti (validators.sniff_upload_mime):
PDF/JPEG/PNG/WebP magic doğrulaması · server-derived MIME · sanitized filename · boyut limiti.
İki upload yolu ayrı davranış bırakmasın (ürün kararı 2026-07-23).

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_vault_upload_security.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "x" * 44)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import autotax.main as M
from autotax.models import Base, Invoice
from autotax.auth import get_current_user

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print("  PASS  " + m)
    else:
        FAIL += 1; print("  FAIL  " + m)


PDF = b"%PDF-1.4\n%..."
HTML = b"<html><script>alert(document.cookie)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def main():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    S = sessionmaker(bind=eng)
    db = S()
    db.add(Invoice(id=1, user_id=1, filename="alt.pdf", file_content_type="application/pdf",
                   raw_text="", invoice_type="expense", status="pending"))
    db.commit(); db.close()
    M.SessionLocal = S
    M.app.dependency_overrides[get_current_user] = lambda: {"sub": 1, "email": "o@test.de"}
    cl = TestClient(M.app)

    print("== SH-1c — Vault upload ==")
    r = cl.post("/vault/1/upload", files={"file": ("v.pdf", PDF, "application/pdf")})
    ok(r.status_code == 200, "geçerli PDF upload 200 (%s)" % r.status_code)
    d = S(); inv = d.query(Invoice).get(1); ct = inv.file_content_type; d.close()
    ok(ct == "application/pdf", "saklanan content_type bytes'tan TÜREDİ")

    r = cl.post("/vault/1/upload", files={"file": ("evil.pdf", HTML, "application/pdf")})
    ok(r.status_code == 400, "sahte .pdf (HTML) → 400")
    r = cl.post("/vault/1/upload", files={"file": ("x.svg", SVG, "image/svg+xml")})
    ok(r.status_code == 400, "SVG+script → 400")
    r = cl.post("/vault/1/upload", files={"file": ("e.pdf", b"", "application/pdf")})
    ok(r.status_code == 400, "boş → 400")
    big = b"%PDF" + b"0" * (11 * 1024 * 1024)
    r = cl.post("/vault/1/upload", files={"file": ("big.pdf", big, "application/pdf")})
    ok(r.status_code == 400, "11MB → 400 (boyut limiti)")

    # yalancı content_type + bozuk ad → türetilir + sanitize
    r = cl.post("/vault/1/upload", files={"file": ('a"b.pdf', PDF, "text/html")})
    ok(r.status_code == 200, "geçerli PDF (yalancı ct + bozuk ad) → 200")
    d = S(); inv = d.query(Invoice).get(1); ct = inv.file_content_type; fn = inv.filename; d.close()
    ok(ct == "application/pdf" and '"' not in (fn or ""), "content_type türedi + filename sanitize")

    M.app.dependency_overrides.clear()
    print("\n=== SH-1c Vault: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
