# Verfahrensdokumentation gemäß GoBD

**Version:** 1.0
**Stand:** 2026-05-28
**Verantwortlicher:** Hüseyin Hancer, Wiesenstr. 10, 66115 Saarbrücken
**Dienst:** AutoTax-Cloud (https://autotax.cloud)

Diese Verfahrensdokumentation entspricht den Anforderungen der **GoBD** (Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form sowie zum Datenzugriff, BMF-Schreiben vom 28.11.2019).

Sie ist auf Anfrage des Finanzamtes vorzuhalten und muss bei einer Außenprüfung (§ 147 AO) verfügbar sein. Jeder Nutzer von AutoTax-Cloud ist verpflichtet, eine eigene unternehmensindividuelle Verfahrensdokumentation zu erstellen — dieses Dokument liefert die systemseitigen Grundlagen.

---

## 1. Allgemeine Angaben

### 1.1 Anbieter

```
Hüseyin Hancer
Wiesenstr. 10
66115 Saarbrücken
Deutschland

E-Mail (allgemein):  info@autotax.cloud
E-Mail (Datenschutz): datenschutz@autotax.cloud
Steuernummer: <wird nachgereicht / Kleinunternehmer gemäß § 19 UStG>
```

### 1.2 Software

- **Produktname:** AutoTax-Cloud
- **Version:** 5.5.5 (Stand 2026-05-28)
- **Architektur:** SaaS, gehostet auf Railway (EU)
- **Quellcode-Repository:** privates GitHub-Repo `autotax-public`
- **Live-URL:** https://autotax.cloud

### 1.3 Geltungsbereich

Diese Dokumentation beschreibt:
- Wie Belege in das System gelangen (Eingangskanäle)
- Wie sie verarbeitet werden (OCR, Klassifizierung, Speicherung)
- Wie sie archiviert werden (10-Jahres-Aufbewahrung)
- Wer Zugriff hat (Berechtigungen, Audit)
- Wie das System gesichert ist (Datensicherung, Wiederherstellung)
- Wie Änderungen nachvollziehbar bleiben (Audit-Log, Soft-Delete)

---

## 2. Ordnungsmäßigkeit (Grundsätze nach § 145 AO)

### 2.1 Nachvollziehbarkeit + Nachprüfbarkeit (Rn. 30 GoBD)

Jeder Beleg ist über folgende Felder eindeutig identifizierbar:
- Eindeutige ID (Datenbank-Primärschlüssel)
- Erfassungszeitpunkt (`created_at`)
- Eingangskanal (Upload / E-Mail / API)
- Original-Dateipfad (file_path) + Hash (file_hash)
- Bearbeitungshistorie (audit_log + corrections)

### 2.2 Vollständigkeit (Rn. 35)

- Alle hochgeladenen Belege werden persistiert (kein "stilles Verwerfen")
- Duplikat-Erkennung markiert (`possible_duplicate`), löscht aber nicht
- Soft-Delete-Pattern: `is_deleted` Flag — Daten werden NICHT physisch entfernt
- Status-Maschine: `pending` → `ready` → `confirmed`

### 2.3 Richtigkeit (Rn. 41)

- OCR-Extraktion erfolgt automatisch, ist aber nicht bindend
- Nutzer kann jeden Wert manuell korrigieren
- Korrekturen werden in `corrections` Tabelle protokolliert
- KI-Bewertung ist optional und nicht-direktiv ("Vorschlag" / "Empfehlung")

### 2.4 Zeitgerechte Buchungen (Rn. 46)

- Belege werden zum Eingangszeitpunkt erfasst (`created_at` automatisch)
- Datum des Beleges (`date`) wird separat geführt (Beleg-Datum vs. Erfassungs-Datum)
- Periodengerechte Zuordnung über `date` Feld möglich

### 2.5 Ordnung (Rn. 50)

- Standardisierte Datenstruktur (Tabellen: invoices, cash_entries, ...)
- Eindeutige Belegnummer-Vergabe möglich (`invoice_number` Feld)
- Kategorisierung nach festen Werten (food, restaurant, fuel, ...)
- DATEV-Konten-Zuordnung automatisch (siehe `autotax/datev.py`)

### 2.6 Unveränderbarkeit (Rn. 58)

| Mechanismus | Umsetzung |
|---|---|
| Soft-Delete | Belege werden NIE physisch gelöscht; `is_deleted=true` + `deleted_at` |
| Audit-Log | Aktion + Zeitstempel + Nutzer-ID + Ressource für jede schreibende Operation |
| Original-Datei | Wird unverändert auf Disk gespeichert (`file_path`) + Hash (`file_hash`) gegen Veränderung prüfbar |
| `processed=true` Flag | Markiert "geprüfte" Belege; Änderungen darauf werden im audit-log festgehalten |
| Backups | Wöchentliche Off-Site-Sicherung (R2) verhindert Datenverlust |

---

## 3. Verfahrensablauf — Beleg-Lebenszyklus

```
[1] EINGANG
    ├── Foto / Scan / PDF Upload      (POST /invoices/upload)
    ├── E-Mail-Import (IMAP)           (background loop)
    ├── Manuelle Eingabe (Web-Formular) (POST /cash-entries)
    └── E-Rechnung (XRechnung/ZUGFeRD)  (POST /invoices/upload-erechnung)

[2] VERARBEITUNG
    ├── Magic-Byte-Validierung (Datei-Typ)
    ├── OCR (Tesseract → OCR.space → Claude Haiku Vision Fallback)
    ├── Parsing (Heuristik: vendor, amount, VAT, date, IBAN, …)
    ├── KI-Bewertung (optional, asynchron, mit Hinweis "Empfehlung")
    └── DATEV-Konto-Zuordnung (automatisch nach Kategorie)

[3] SPEICHERUNG
    ├── Original-Datei: Disk-Volume (file_path) + SHA-Hash
    ├── Strukturierte Daten: PostgreSQL `invoices` Tabelle
    ├── Rohtext: invoices.raw_text (für spätere Nachprüfung)
    └── Hochgeladen-Zeitstempel: created_at

[4] PRÜFUNG (Nutzer-Aktion)
    ├── Status pending → ready (automatisch, wenn total_amount vorhanden)
    ├── Status ready → confirmed (manuell durch Nutzer)
    └── Korrekturen werden in `corrections` Tabelle protokolliert

[5] EXPORT
    ├── DATEV-Export (CSV) — /export/datev
    ├── Excel-Export — /export/excel
    ├── EÜR-Bericht — /steuer/eur
    └── PDF-Bericht — /export/pdf

[6] AUFBEWAHRUNG (10 Jahre, § 147 AO)
    ├── Aktive Datenbank: PostgreSQL (Railway)
    ├── Originaldateien: Disk-Volume (Railway)
    ├── Wöchentliche Off-Site-Backups: Cloudflare R2 EU-Frankfurt
    └── Soft-Delete: Daten bleiben 10 Jahre nach "Löschung" erhalten
```

---

## 4. Sicherheit (gem. GoBD Rn. 100ff)

### 4.1 Zugangsschutz

- Authentifizierung: E-Mail + bcrypt-Passwort
- E-Mail-Verifizierung obligatorisch
- JWT-basierte Sitzungen (HttpOnly Cookies + Bearer)
- Rate-Limiting auf Auth-Endpoints
- Admin-Zugang nur über ADMIN_EMAILS-Allowlist

Vollständige Details: `ACCESS_CONTROL.md`

### 4.2 Datensicherung

- Wöchentliche pg_dump + gzip + Upload zu Cloudflare R2
- 4 Wochen rolling Retention (operativ)
- 10-Jahres Cold-Archive geplant (S5 Sprint)
- RPO ≤ 7 Tage, RTO ≤ 4 Stunden

Vollständige Details: `BACKUP_POLICY.md`

### 4.3 Übertragungssicherheit

- TLS 1.2+ erzwungen
- HSTS 2 Jahre + preload
- Cloudflare WAF + DDoS-Schutz am Edge
- Webhook-Signaturen (Stripe, AI Reviewer HMAC)

### 4.4 Veränderungssicherheit

- Audit-Log für alle Schreib-Operationen
- Soft-Delete statt physischer Löschung
- Datei-Hash zur Integritätsprüfung
- Versionierung über `corrections` Tabelle

---

## 5. Datenzugriff (gem. GoBD Rn. 158-180)

Bei einer Außenprüfung gewährt die Software folgende Zugriffsmöglichkeiten:

### Z1 — Unmittelbarer Datenzugriff
Nicht direkt unterstützt (Finanzamt erhält keine Login-Daten).

### Z2 — Mittelbarer Datenzugriff (Auswertung durch Steuerpflichtigen)
Der Nutzer kann auf Anfrage des Prüfers konkrete Auswertungen in der UI generieren und exportieren.

### Z3 — Datenträgerüberlassung ✅ unterstützt
Der Nutzer kann jederzeit folgende Exporte erstellen:
- **DATEV-CSV** (`/export/datev`): Standard-Format für Steuerprüfer
- **Excel-Bericht** (`/export/excel`): umfangreich + formatiert
- **JSON-Datenexport** (Profil → Daten exportieren): vollständige Maschinen-lesbare Form
- **EÜR-Bericht** (`/steuer/eur`): Einnahmen-Überschuss-Rechnung als PDF

---

## 6. Aufbewahrungspflicht (§ 147 AO)

| Art der Unterlage | Frist |
|---|---|
| Rechnungen, Belege, Kontoauszüge | 10 Jahre |
| Geschäftsbriefe, Verträge | 6 Jahre |
| Programmdokumentation (diese Datei) | über die gesamte Nutzungsdauer |

### Verantwortlichkeit:

- **Nutzer:** Verantwortlich für die Vollständigkeit seiner geschäftlichen Aufzeichnungen
- **AutoTax-Cloud (Anbieter):** Sorgt für die technische Bereitstellung, Verfügbarkeit, Sicherung und Wiederherstellbarkeit über den gesamten Aufbewahrungszeitraum

Wird das Nutzungsverhältnis beendet, hat der Nutzer Anspruch auf:
- Vollständigen Datenexport (Art. 20 DSGVO + § 147 AO)
- 30 Tage Übergangszeitraum zur Datenextraktion

---

## 7. Änderungsmanagement

### 7.1 Software-Updates

- Quellcode wird über Git versioniert
- Jede Änderung dokumentiert in Commit-Messages
- Production-Deployments protokolliert (Railway dashboard)
- Sicherheits-Audits halbjährlich (Stand 2026-05-26 → 8.5/10)

### 7.2 Dokumentations-Updates

- Diese Verfahrensdokumentation wird mindestens jährlich überprüft
- Bei wesentlichen Systemänderungen sofort aktualisiert
- Version + Datum oben im Dokument

### 7.3 Notfallplan

Bei System-Ausfall siehe `INCIDENT_RESPONSE.md`.

---

## 8. Hinweis zur Steuerberatung

AutoTax-Cloud ist **keine Steuerberatungssoftware** i.S.d. Steuerberatungsgesetzes (StBerG § 3). Der Dienst stellt technische Werkzeuge bereit für:

- Belegerfassung
- OCR-Auswertung
- Buchhalterische Archivierung
- DATEV-Export

Steuerliche Beratung bleibt ausschließlich zugelassenen Steuerberatern vorbehalten. KI-Empfehlungen sind als "Vorschlag" gekennzeichnet, nicht als verbindliche Auskunft.

---

## 9. Geltungsbereich + Beschränkung

Diese Verfahrensdokumentation beschreibt:

✅ Was AutoTax-Cloud tut (technisch)
✅ Wie Daten verarbeitet werden
✅ Welche Sicherungs- und Aufbewahrungsmaßnahmen vorhanden sind

❌ Die unternehmensindividuelle Verfahrensdokumentation des Nutzers
   (jede Firma muss zusätzlich ihre eigene Dokumentation der internen
   Prozesse erstellen — diese Datei deckt nur die System-Ebene ab)

---

## 10. Verweise auf weitere Dokumente

- `SECURITY_AUDIT.md` — Sicherheitsbewertung
- `BACKUP_POLICY.md` — Datensicherungs-Verfahren
- `INCIDENT_RESPONSE.md` — Notfall-Verfahren
- `ACCESS_CONTROL.md` — Zugriffskontrollen
- `PRIVACY_POLICY.md` — Datenschutz (DSGVO)
- `TOMs.md` — Technische und Organisatorische Maßnahmen (Art. 32 DSGVO)
- `VENDOR_RISK_ASSESSMENT.md` — Auftragsverarbeiter-Übersicht
- `ARCHITECTURE.md` — System-Architektur

---

## Änderungshistorie

| Datum | Version | Änderung |
|---|---|---|
| 2026-05-28 | 1.0 | Erstellung der Verfahrensdokumentation |
