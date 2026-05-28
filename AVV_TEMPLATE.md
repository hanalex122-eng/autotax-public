# Auftragsverarbeitungsvertrag (AVV) — Template

**Vorlage gemäß Art. 28 DSGVO**
**Stand:** 2026-05-28
**Version:** 1.0

Dieser Vertrag wird zwischen dem Verantwortlichen (Kunde, z.B. Steuerberater oder B2B-Geschäftskunde) und AutoTax-Cloud als Auftragsverarbeiter geschlossen.

---

## § 1 Vertragsparteien

### Auftragsverarbeiter (im Folgenden "Auftragnehmer"):

```
Hüseyin Hancer
Wiesenstr. 10
66115 Saarbrücken
Deutschland

E-Mail: datenschutz@autotax.cloud
Tel.:   (auf Anfrage)
```

### Verantwortlicher (im Folgenden "Auftraggeber"):

```
[Vom Auftraggeber ausgefüllt]

Firma:    _______________________
Anschrift: _______________________
Vertretungsberechtigter: _______________________
E-Mail:   _______________________
USt-IdNr: _______________________ (sofern vorhanden)
```

---

## § 2 Gegenstand + Dauer des Auftrags

### 2.1 Gegenstand

Der Auftragnehmer verarbeitet personenbezogene Daten im Auftrag des Auftraggebers im Rahmen folgender Dienstleistung:

> **AutoTax-Cloud** — SaaS-Plattform für digitale Belegerfassung, OCR-basierte Datenextraktion, buchhalterische Archivierung und DATEV-konformen Export.

### 2.2 Dauer

Dieser Vertrag tritt mit der Annahme der Nutzungsbedingungen (AGB) durch den Auftraggeber in Kraft und endet mit:

- Kündigung durch eine der Vertragsparteien (Frist: 30 Tage zum Monatsende), oder
- Beendigung der zugrundeliegenden Service-Vereinbarung (Abonnement-Kündigung)

Die Aufbewahrungs- und Löschpflichten (§ 7) gelten über die Vertragslaufzeit hinaus.

---

## § 3 Art + Zweck der Verarbeitung

| Art der Verarbeitung | Zweck |
|---|---|
| Speicherung von Belegfotos / PDFs | Buchhalterische Archivierung (§ 147 AO) |
| OCR-Auswertung (Texterkennung) | Strukturierung von Belegdaten |
| Automatische Kategorisierung | DATEV-Konten-Zuordnung |
| Datenbankhaltung | Mehrjährige Aufbewahrung |
| Generierung von Berichten | EÜR, KDV, Bilanz |
| Versand von Benachrichtigungen | Erinnerungen, Reports |

Die Verarbeitung erfolgt ausschließlich auf Weisung des Auftraggebers (über die Nutzungsschnittstelle der Software). Eine Verarbeitung außerhalb dieses Zwecks erfolgt nicht.

---

## § 4 Art der personenbezogenen Daten + Kategorien betroffener Personen

### 4.1 Datenkategorien

- **Kontaktdaten** (Name, Anschrift, E-Mail, Telefon)
- **Vertragsdaten** (Kundennummer, Vertragsbeginn)
- **Inhaltsdaten** (Belege, Rechnungen, Quittungen, Kontoauszüge)
- **Finanzdaten** (Betrag, Steuersätze, Zahlungsmodalitäten)
- **Steuerliche Identifikatoren** (USt-IdNr., Steuernummer, IBAN)
- **Authentifizierungsdaten** (verschlüsselte Passwörter, Sessions)
- **Nutzungsdaten** (IP-Adresse anonymisiert, Logs)

### 4.2 Kategorien Betroffener

- Kunden / Lieferanten des Auftraggebers (deren Daten auf Belegen enthalten sind)
- Mitarbeiter des Auftraggebers (sofern sie Login-Konten haben)
- Mandanten / Klienten (bei Steuerberater-Nutzung)

---

## § 5 Pflichten des Auftragnehmers

Der Auftragnehmer verpflichtet sich gemäß Art. 28(3) DSGVO:

1. **Weisungsgebundenheit** — Verarbeitung nur nach dokumentierten Weisungen des Auftraggebers (technisch implementiert über die Software-Schnittstelle)

2. **Geheimhaltung** — Verpflichtung aller mit der Verarbeitung betrauten Personen auf Vertraulichkeit

3. **Sicherheit der Verarbeitung** — Implementierung der technischen und organisatorischen Maßnahmen gemäß `TOMs.md` (Anlage 1 zu diesem AVV)

4. **Unterauftragsverarbeiter** — Einbindung weiterer Auftragsverarbeiter nur mit allgemeiner schriftlicher Genehmigung (§ 6 unten)

5. **Mitwirkung bei Betroffenenrechten** — Unterstützung des Auftraggebers bei Anfragen Betroffener (Art. 15-22 DSGVO) durch:
   - Datenexport-Funktion (Art. 20)
   - Korrektur-Funktionalität (Art. 16)
   - Löschungs-Workflow (Art. 17)
   - Auskunfts-Funktion via Datenexport (Art. 15)

6. **Mitwirkung bei Compliance-Pflichten** — Unterstützung bei:
   - Datenschutz-Folgenabschätzung (Art. 35)
   - Vorherige Konsultation (Art. 36)
   - Meldung von Datenschutzverletzungen (Art. 33)

7. **Datenschutzverletzungen** — Meldung an den Auftraggeber innerhalb von 48 Stunden nach Bekanntwerden (per E-Mail an die im AVV angegebene Adresse + datenschutz@autotax.cloud nachrichtlich)

8. **Datenrückgabe / Löschung nach Vertragsende** — Wahlweise:
   - Vollständige Rückgabe aller personenbezogenen Daten in maschinen-lesbarem Format (JSON / DATEV / CSV)
   - Sichere Löschung — wobei gesetzliche Aufbewahrungspflichten (§ 147 AO, 10 Jahre) beachtet werden

9. **Audit-Rechte** — Bereitstellung aller erforderlichen Informationen zum Nachweis der Einhaltung dieses AVV. Vor-Ort-Prüfungen nach 14-tägiger Vorankündigung möglich (Kosten trägt der Auftraggeber, sofern nicht eine bestätigte Verletzung vorliegt)

---

## § 6 Unterauftragsverarbeiter

### 6.1 Genehmigung

Der Auftraggeber erteilt mit Vertragsschluss die allgemeine schriftliche Genehmigung zur Einbindung folgender Unterauftragsverarbeiter:

| Unterauftragsverarbeiter | Land | Zweck |
|---|---|---|
| Railway Inc. | USA / EU | Hosting (PaaS) |
| Cloudflare, Inc. | USA / EU | DNS, CDN, Backup-Speicher, E-Mail-Routing |
| Stripe Payments Europe Ltd. | Irland | Zahlungsabwicklung |
| Anthropic PBC | USA | KI-OCR-Fallback + Steuer-Fragen |
| OCR.space (a9t9 Software GmbH) | Deutschland | Cloud-OCR-Fallback |
| Resend | USA | Transaktionale E-Mails |
| Telegram Messenger Inc. | UK / VAE | Optionale Bot-Benachrichtigungen (Opt-in) |

Eine detaillierte Risikobewertung jedes Subprozessors befindet sich in `VENDOR_RISK_ASSESSMENT.md`.

### 6.2 Änderungen

Der Auftragnehmer informiert den Auftraggeber mit 30 Tagen Vorlauf über:
- Einbindung neuer Unterauftragsverarbeiter
- Wechsel bestehender Anbieter
- Wesentliche Änderungen der Datenverarbeitung

Der Auftraggeber hat ein Widerspruchsrecht bei berechtigten Gründen. Im Widerspruchsfall besteht Sonderkündigungsrecht.

### 6.3 Standardvertragsklauseln + EU-US DPF

Für Datenübermittlungen in Drittländer (insbesondere USA) gelten:
- **EU-Standardvertragsklauseln** (SCC) gemäß Beschluss (EU) 2021/914, und/oder
- **EU-US Data Privacy Framework** (DPF) für zertifizierte Anbieter

---

## § 7 Aufbewahrung + Löschung

### 7.1 Aufbewahrungspflicht

Buchhalterische Belege sind gemäß § 147 AO **10 Jahre** aufzubewahren. Diese Pflicht trifft primär den Auftraggeber. AutoTax-Cloud unterstützt durch:

- Speicherung in PostgreSQL mit Soft-Delete
- Wöchentliche Backups in Cloudflare R2 (EU/Frankfurt)
- 10-Jahres Cold-Archive (S5 Sprint geplant)

### 7.2 Löschung nach Vertragsende

Bei Vertragsende:

1. **Tag 0** — Vertragsende
2. **Tag 1-30** — Auftraggeber kann jederzeit vollständigen Datenexport ziehen (DATEV / JSON / Excel)
3. **Tag 30** — Operative Daten werden aus aktiver Datenbank entfernt (anonymisiert / hard-delete falls möglich)
4. **Tag 30 - Jahr 10** — Daten verbleiben in archivierten Backups gemäß § 147 AO. Auftraggeber kann jederzeit Wiederherstellung beantragen.
5. **Nach Jahr 10** — Vollständige Löschung aller Daten

---

## § 8 Haftung + Schadensersatz

- Haftung richtet sich nach den allgemeinen gesetzlichen Bestimmungen + AGB
- Beschränkungen gemäß DSGVO Art. 82 bleiben unberührt
- Bei groben Verstößen gegen diesen AVV: Sonderkündigungsrecht + Schadensersatzansprüche

---

## § 9 Sonstige Bestimmungen

### 9.1 Schriftform

Änderungen + Ergänzungen dieses AVV bedürfen der Textform (E-Mail genügt).

### 9.2 Salvatorische Klausel

Sollte eine Bestimmung dieses Vertrags unwirksam sein, bleibt der übrige Vertrag wirksam.

### 9.3 Gerichtsstand

Erfüllungsort und Gerichtsstand ist Saarbrücken, Deutschland.

### 9.4 Anwendbares Recht

Es gilt deutsches Recht unter Beachtung der DSGVO.

---

## § 10 Anlagen

Folgende Dokumente sind Bestandteil dieses AVV:

| Anlage | Dokument | Zweck |
|---|---|---|
| 1 | `TOMs.md` | Technische und Organisatorische Maßnahmen (Art. 32) |
| 2 | `VENDOR_RISK_ASSESSMENT.md` | Bewertung der Unterauftragsverarbeiter |
| 3 | `BACKUP_POLICY.md` | Sicherungs- und Wiederherstellungsverfahren |
| 4 | `ACCESS_CONTROL.md` | Zugriffskontrollen |
| 5 | `INCIDENT_RESPONSE.md` | Notfallplan bei Vorfällen |
| 6 | `GOBD_VERFAHRENSDOKUMENTATION.md` | GoBD-konforme Verfahrensdokumentation |

---

## Unterschriften

```
Ort, Datum: _______________________

Für den Auftraggeber:                Für den Auftragnehmer:

_______________________               _______________________
Name:                                  Hüseyin Hancer
Position:                              Inhaber
```

---

## Hinweise zur Verwendung dieser Vorlage

1. **B2B Kunde anfragt AVV** → Diese Vorlage als Word/PDF konvertieren
2. **Felder ausfüllen** → § 1 (Auftraggeber-Daten), § 6 (sofern Subprozessor-Liste sich änderte)
3. **Beide Seiten unterzeichnen** (digitale Signatur oder ausgedruckt + Scan)
4. **Aufbewahren** → 10 Jahre (Vertragsunterlage)

Für Standard-Kunden auf Web-Plattform: Die Annahme der AGB beim Registrieren beinhaltet bereits eine vereinfachte AVV-Klausel. Eine vollständige AVV nach Art. 28 ist nur bei B2B-Vertragspartnern erforderlich, die sensible Daten in größerem Umfang verarbeiten lassen.

---

## Versionsgeschichte

- 2026-05-28: Initiale AVV-Vorlage erstellt
