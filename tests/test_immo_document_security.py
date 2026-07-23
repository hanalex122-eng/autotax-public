"""Security Hotfix — belge yükleme/indirme sertleştirmesi (immo + vault).

Kilitlenen davranışlar:
  SH-1a download: Content-Disposition attachment · güvenli (bytes'tan türetilmiş) MIME ·
    filename sanitize · X-Content-Type-Options nosniff · eski HTML kayıt origin'de çalışmaz
  SH-1b upload:  boyut limiti · magic doğrulama · server-derived MIME · sahte içerik reddi
  Ortak: PDF/JPEG/PNG/WebP kabul, geri kalan (XML/HTML/…) red

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_document_security.py
"""
import os
import sys
import io

os.environ.setdefault("JWT_SECRET", "x" * 44)

from autotax.validators import sniff_upload_mime, sanitize_filename, ALLOWED_UPLOAD_MIME

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print("  PASS  " + m)
    else:
        FAIL += 1; print("  FAIL  " + m)


PDF = b"%PDF-1.4\n%..."
JPG = b"\xff\xd8\xff\xe0\x00\x10JFIF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"VP8 "
HTML = b"<html><script>alert(document.cookie)</script></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
XML = b'<?xml version="1.0"?><root/>'


def main():
    print("== sniff_upload_mime — yalnız 4 izinli tip ==")
    ok(sniff_upload_mime(PDF) == "application/pdf", "PDF → application/pdf")
    ok(sniff_upload_mime(JPG) == "image/jpeg", "JPEG → image/jpeg")
    ok(sniff_upload_mime(PNG) == "image/png", "PNG → image/png")
    ok(sniff_upload_mime(WEBP) == "image/webp", "WebP → image/webp")
    ok(sniff_upload_mime(HTML) is None, "HTML → None (reddedilir)")
    ok(sniff_upload_mime(SVG) is None, "SVG+script → None (reddedilir)")
    ok(sniff_upload_mime(XML) is None, "XML → None (kapsam dışı)")
    ok(sniff_upload_mime(b"") is None and sniff_upload_mime(b"ab") is None, "boş/kısa → None")
    # sahte uzantı: HTML içeriği .pdf iddiasıyla → yine None (magic bytes)
    ok(sniff_upload_mime(HTML) is None, "sahte .pdf (HTML içerik) → None (magic bytes kazanır)")
    ok(set(ALLOWED_UPLOAD_MIME) == {"application/pdf", "image/jpeg", "image/png", "image/webp"},
       "izinli set = PDF/JPEG/PNG/WebP")

    print("\n== sanitize_filename — header injection kapalı ==")
    ok(sanitize_filename('a"b.pdf') == "ab.pdf", "çift tırnak silinir")
    ok(sanitize_filename("a\r\nb.pdf") == "ab.pdf", "CRLF silinir")
    ok(sanitize_filename("../../etc/passwd") == "passwd", "path bileşeni atılır")
    ok(sanitize_filename("C:\\Windows\\x.pdf") == "x.pdf", "windows path atılır")
    ok(sanitize_filename("") == "dokument" and sanitize_filename(None) == "dokument", "boş → dokument")

    # ── SH-1a/1b integration (TestClient) ──────────────────────────────
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autotax.models import Base, ImmoProperty, ImmoDocument
    from autotax import immo_api, storage
    from autotax.auth import get_current_user

    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    d0 = S()
    d0.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    d0.commit(); d0.close()
    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n== SH-1a — download sertleştirme (eski kayıt dahil) ==")
    # ESKİ, kötü kayıt: HTML içerik, content_type text/html (SH öncesi yüklenmiş gibi)
    rel = storage.save_file(1, HTML, "evil.html")
    dh = S(); dh.add(ImmoDocument(id=1, property_id=10, user_id=1, typ="other",
                                  filename='ev"il.html', file_path=rel, file_content_type="text/html"))
    dh.commit(); dh.close()
    r = cl.get("/immo/documents/1/download")
    ok(r.status_code == 200, "eski kayıt indiriliyor (200)")
    ok(r.headers.get("content-disposition", "").startswith("attachment"), "Content-Disposition: attachment (inline değil)")
    ok(r.headers.get("content-type", "").split(";")[0] != "text/html", "media_type text/html DEĞİL → origin'de render olmaz")
    ok('"' not in r.headers.get("content-disposition", "").split("filename=")[-1].strip('"'), "filename sanitize (tırnak yok)")
    ok(r.headers.get("x-content-type-options") == "nosniff", "nosniff header")

    # Geçerli PDF kaydı → download octet-stream/attachment, güvenli
    relp = storage.save_file(1, PDF, "vertrag.pdf")
    dp = S(); dp.add(ImmoDocument(id=2, property_id=10, user_id=1, typ="contract",
                                  filename="vertrag.pdf", file_path=relp, file_content_type="application/pdf"))
    dp.commit(); dp.close()
    r = cl.get("/immo/documents/2/download")
    ok(r.status_code == 200 and r.content == PDF, "geçerli PDF indiriliyor (içerik aynı)")
    ok(r.headers.get("content-type", "").split(";")[0] == "application/pdf", "PDF → application/pdf (bytes'tan türedi)")

    print("\n== SH-1b — upload sertleştirme ==")
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "contract"},
                files={"file": ("v.pdf", PDF, "application/pdf")})
    ok(r.status_code == 200, "geçerli PDF upload 200")
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ("evil.pdf", HTML, "application/pdf")})
    ok(r.status_code == 400, "sahte .pdf (HTML içerik) → 400 (magic bytes)")
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ("x.svg", SVG, "image/svg+xml")})
    ok(r.status_code == 400, "SVG+script → 400")
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ("z.xml", XML, "application/xml")})
    ok(r.status_code == 400, "XML → 400 (kapsam dışı)")
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ("e.pdf", b"", "application/pdf")})
    ok(r.status_code == 400, "boş dosya → 400")
    big = b"%PDF" + b"0" * (11 * 1024 * 1024)
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ("big.pdf", big, "application/pdf")})
    ok(r.status_code == 400, "11MB PDF → 400 (boyut limiti)")
    # server-derived MIME: yalancı content_type'a rağmen bytes'tan türetilir
    r = cl.post("/immo/documents", data={"property_id": 10, "typ": "other"},
                files={"file": ('a"b.pdf', PDF, "text/html")})
    ok(r.status_code == 200, "geçerli PDF (yalancı content_type + bozuk ad) → 200")
    did = r.json().get("id")
    dd = S(); row = dd.query(ImmoDocument).get(did); ct = row.file_content_type; fn = row.filename; dd.close()
    ok(ct == "application/pdf", "saklanan content_type bytes'tan TÜREDİ (yalancı text/html değil)")
    ok('"' not in fn, "saklanan filename sanitize (tırnak yok)")

    print("\n== Regresyon — list/delete davranışı ==")
    ok(cl.get("/immo/properties/10/documents").status_code == 200, "belge listesi çalışıyor")
    ok(cl.delete("/immo/documents/2").status_code == 200, "belge silme çalışıyor")

    print("\n=== Security Hotfix SH-1a+1b: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
