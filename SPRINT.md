# SPRINT — one active sprint at a time

**Rule:** `Finish > New Features`. See CLAUDE.md → "Sprint discipline". No topic switching, no new
features proposed, until the active sprint passes the Definition of Done below.

---

## Definition of Done (all 8 must be true)

- [ ] Code complete
- [ ] Tests green
- [ ] UX checked (real user flow, not just endpoints)
- [ ] Contradicting legacy flows removed (no two screens telling different truths)
- [ ] Review done
- [ ] Deployed
- [ ] Smoke-tested on production
- [ ] No critical gap left from the user's point of view

---

## NO ACTIVE SPRINT — Sprint 3.0 closed & production-verified 2026-07-21

## ✅ SPRINT 3.0 — Faz 3 doğruluk sprinti + örtüşme guardrail'i — CLOSED (canlı `bee9043`, 2026-07-21)

**Tek hedef:** bugün *sessizce* yanlış hesaplanan unit-seviye türetmeleri düzeltmek ve aynı Unit'te
ikinci bir sözleşmenin fark edilmeden oluşmasını engellemek — **yeni özellik yok, şema değişikliği yok.**
Sprint 3.0 WG desteği **getirmez**; NK motoru bunu doğru hesaplayana kadar (3.1) **engeller**.
Tasarım: `docs/design/Sprint_3_0_Technical_Design.md` · ADD Rev.3 `docs/design/Phase3_WG_Zimmervermietung.md`.

**Düzeltilenler:** `act[0]` yerine tüm aktif tenancy'lerin toplamı (`immo_api.py` `_accounting` + `_portfolio`)
→ property/portföy Soll'u artık eksik değil, cockpit inkasso oranı (ist/soll) şişmiyor, rapor içinde
"Rückstand > Soll" görülemiyor · Wohnung Akte artık N sözleşme gösteriyor (`akteActiveTens`; `akteActiveTen`
listenin ilki → **N=1'de görünüm birebir aynı**) + salt-okunur "Offen gesamt".

**Guardrail (ADD Rev.3 — HARD VALIDATION):** aynı Unit'te tarih aralığı **örtüşen** ikinci tenancy 400 ile
reddedilir; **override yok, sadece-uyarı yok.** Aynı gün devir (`bis == von`) ve ardışık sözleşmeler serbest.
PATCH ile örtüşme yaratmak da reddedilir. **Geçmişe dönük doğrulama yok** — mevcut kayıtlar hiç denetlenmez.

**Commit'ler (3):**
| Commit | İçerik |
|---|---|
| `950decd` | Sprint 3.0 teknik tasarım + ADD Revision 3 (guardrail kararı, Akte "Toplam Açık" kararı) |
| `1119da5` | 3.0a backend — `act[0]` → toplam · `_ranges_overlap` + `_assert_no_overlap` · yeni test (23 kontrol) |
| `bee9043` | 3.0b frontend — Akte N sözleşme + salt-okunur "Offen gesamt" |

**Go/No-Go — kanıtlar:**
1. **Commit:** HEAD == origin/main == `bee9043`.
2. **Suite 47/47 PASS** (46 → +1). Yeni `test_immo_sprint_3_0.py`: örtüşme mantığı 7 senaryo · guardrail
   400/200 yolları · reddedilen PATCH kaydı değiştirmiyor · geçmişe dönük doğrulama yok · Soll toplamı
   bağımsız türetmeyle doğrulandı (**9201.67 doğru vs 7980.00 `act[0]` → 1221.67 eksik raporlanıyordu**).
3. **Gate H4 kanıtı:** `git diff --stat` → `models.py` · `db.py` · `immo_payments.py` · `immo_rules.py` ·
   `immo_payment_models.py` · `immo_payment_repository.py` · `immo_nebenkosten.py` · `immo_ledger.py`
   = **0 satır**. Muhasebe, Mahnung, NK motoru, Single Ledger dokunulmadı. Şema/migration yok.
4. **Gate T2 deploy öncesi tekrar:** 3 tenancy · 3 unit · **0 örtüşme** → deploy koşulu sağlandı,
   hiçbir mevcut rakam değişmedi.
5. **Prod smoke:** `/health` ok · db connected · `/app` 200 (914 KB) · `akteActiveTens` 3× · "Offen gesamt" 1× ·
   Faz 2 Untermieter UI bozulmadı 3× · auth guard 401 · console error yok.
6. **Guardrail canlı doğrulaması (tarayıcı, gerçek hesap):** dolu daireye (Whg 1, aktif kiracı 2026-06-15→açık)
   örtüşen ikinci sözleşme denendi → **HTTP 400** · UI mesajı doğru ve iki çıkış yolunu gösteriyor
   (*„… ist in diesem Zeitraum bereits vermietet … → Auszugsdatum … → je Zimmer eine eigene Einheit"*) ·
   **kayıt OLUŞMADI** (kiracı sayısı 3 → 3, "TEST Guardrail" yok) · console error yok.

**Definition of Done: 12/12.**

**Bilinçli ertelenen:** `anteil_flaeche`/`zimmer` + alan korunumu + NK ağırlıkları → **3.1** ·
Verbrauch çift sayımı (K3) + Zähler şeffaflığı → **3.2** · Mahnung/WGB oda gösterimi, "2/3 oda dolu" → **3.3** ·
oda bazlı tüketim dağıtımı → **Professional Review Required** (açık) · aynı Unit'te Untermieter,
Eigennutzung+kiracı aynı dairede → **Faz 4**.

**Açık riskler / borçlar:** Akte'nin N>1 dalı prod'da render **olmuyor** (guardrail örtüşmeyi engelliyor,
mevcut örtüşme 0) → 3.1 için savunma kodu; tarayıcı doğrulaması bilinçli olarak yapılmadı ·
`/app` ilk render ~14 s (Babel in-browser, bu sprintin regresyonu değil) · [OPS] Railway Postgres
PGPASSWORD senkronsuzluğu (bu backlog'da, Faz 3 dışı).

**Bu sprint gerçekten bitti mi? EVET.** Kapsamın tamamı canlı ve kanıtlı; kullanıcı gözünden kritik boşluk yok.

---

## ✅ SPRINT 2.2 — Housekeeping / Closure — CLOSED (canlı `792398c`, 2026-07-21)

**Amaç:** Sprint 2.1'i kayda geçirmek ve arkasında kalan düzensizliği temizlemek. Yeni iş kuralı YOK ·
muhasebe / Mietkonto / Mahnung / NK motoru / Single Ledger'a dokunulmadı · Faz 3 kapsam dışı ·
backend tek satır bile değişmedi.

**Kapsam 4/4 + onaylı 1 ek (5 commit):**
| Commit | İçerik |
|---|---|
| `6cbd0d3` | Sprint 2.1 tasarım dokümanları repoya girdi; roadmap Faz 2 ✅ işaretlendi (aynı-daire maddesi Faz 4'e taşındı, Seçenek B'nin sonucu). Eski taslak SUPERSEDED banner'ıyla korundu → iki belge çelişmiyor. |
| `871d070` | `SPRINT.md` — Sprint 2.1 Final Closure Report |
| `bbdeef0` | **`Neuer Mieter` sihirbazına Untermieter** — aday kuralı Form A/B ile birebir (aynı bina · farklı Unit · `typ≠unter`). Üçüncü giriş yolu kapandı. |
| `04ea414` | `.gitignore` — harness **çıktıları** yoksayıldı (`tests/_*.html|txt`, `tests/*.png|pdf`, `*.log`, `*.tmp`) |
| `792398c` | Geliştirici **araçları** repoya alındı: `_babelcheck.js` + 4 `build_*_harness.py` (kaynak; çıktı değil) |

**Kanıtlar:** suite **46/46 PASS** · babel PARSE OK · JSX BALANCED · 6 harness script'i commit sonrası
çalışıyor, çıktıları `git status`'e sızmıyor (0 sızıntı) · gizli bilgi taraması temiz.
Tarayıcı: sihirbazın aday dropdown'ında tek aday, POST gövdeleri `typ:"unter",parent:1` /
`typ:"haupt",parent:-1`.
**Post-deploy smoke:** `/health` ok · db connected · `/app` 200 (912 KB) · Untermieter kutusu canlıda
**3×** (Form A + Form B + sihirbaz) · `erfHmCands` 4× · **console error yok**. Sihirbazın görsel
açılışını ev sahibi manuel doğruladı.

**Repo:** untracked 98 → 50 · `main` == `origin/main` == `792398c`.

**Açık teknik borçlar (devreden, kritik değil):** `ImmobilienView` satırında rozet yok · Hauptmieter
silinirse `parent_tenancy_id` sarkıyor · bina eşleşmesi ad+adres string'ine dayanıyor (feed'de
`property_id` yok) · `tFull` yüklenmeden Form A filtresi kısa süre eksik (backend 400 yakalar) ·
kök dizindeki 27 tek-seferlik script + 23 `.claude` notu → ayrı **Repository Cleanup** görevi ·
ölçüm notu: `/app` ilk render 13.6 s (Babel in-browser; bu sprintin regresyonu değil).

**Bu sprint gerçekten bitti mi? EVET.** Kapsamın tamamı tamamlandı, kanıtlandı ve canlıda.

---

## ✅ SPRINT 2.1 — Untermieter (Flexible Mietmodelle Faz 2) — CLOSED (canlı `70cd732`, 2026-07-21)

**Tek hedef:** ev sahibi bir kiracının Untermieter olduğunu ve hangi Hauptmieter'e bağlı olduğunu
kaydedebilsin — **muhasebeye hiç dokunmadan**. Sprintin başarısı eklediği özellik değil,
**değiştirmediği şey**: `typ` / `parent_tenancy_id` hiçbir hesaba girmez.

**Mimari kararlar:** Untermieter **ayrı bir Unit**'te (Seçenek B) → aynı-daire NK m²-payı sorunu hiç
doğmaz · her tenancy kendi Mietkonto/borç/ödeme/Mahnung akışını korur (**Single Ledger**) · alanlar
additive/nullable, hard FK yok, `typ=NULL` = `haupt` (mevcut kayıtlar birebir aynı) · tek seviye
(Untermieter'in Untermieter'i yok). Sunucu 4 kuralı zorunlu kılar: parent aynı user · kendine bağlanamaz ·
parent `unter` olamaz · **farklı Unit**. Tasarım: `docs/design/Sprint_2_1_Untermieter.md`.

**Commit'ler (6):**
| Commit | İçerik |
|---|---|
| `3bbdf40` | `typ` + `parent_tenancy_id` (model + idempotent migration) |
| `c92f49e` | API create/patch + `_norm_typ` + `_validate_parent` + okuma yüzeyleri |
| `d833120` | Form A (`ImmoTenancyForm`) — toggle + Hauptmieter dropdown |
| `28175c5` | 2.1c — Form B (satır-içi düzenleme) + kiracı kartı & Mietkonto başlığı rozeti |
| `b3e7223` | 2.1d — Form A'nın tasarımdan sapan 3 noktası (typ filtresi · K3 uyarısı · `unit_id` fallback) |
| `70cd732` | 2.1e — E2E regresyon testi + görsel doğrulama harness'i |

**Go/No-Go — kanıtlar (iddia değil, ölçüm):**
1. **Commit:** HEAD == origin/main == `70cd732`.
2. **Suite 46/46 PASS.** Kritik kanıt `test_immo_sprint_2_1_e2e.py` (25 kontrol): Untermieter
   eklenince Hauptmieter'in Mietkonto'su **SHA256 birebir aynı** (`4bba7996a9ac6cf5`), borç 680→680,
   Mahnung geçmişi aynı; Untermieter kendi borcunu (370) ve kendi Mahnung'unu taşıyor; bağ koparılınca
   yine hiçbir tutar değişmiyor. `monat_soll` 645 == 645 (typ eklenince değişmez).
3. **Görsel doğrulama (Chrome, gerçek `index.html` kodu):** iki formda da aday dropdown'ı **tek kişi**
   (başka binadaki kiracı ve Untermieter'in kendisi elendi) · rozet 1× `🔗 Untermieter → [ad]` ·
   PATCH gövdesi işaretliyken `typ:"unter",parent:1`, kaldırılınca `typ:"haupt",parent:-1` · konsol hatası yok.
4. **Canlı kod:** `/openapi.json` → `TenancyIn`/`TenancyPatch` içinde `typ` + `parent_tenancy_id`;
   `/app` → Untermieter kutusu 2× (Form A+B), K3 uyarısı 2×, rozet 2×, `hmCands` 7×. Health: status ok · db connected.
5. **Prod smoke (ev sahibi, manuel, 11/11 PASS):** ayrı Unit'te Untermieter oluşturuldu, aynı Unit
   dropdown'da görünmedi, rozet doğru (Hauptmieter'de yok / Untermieter'de var), **Hauptmieter'in Offen
   tutarı + Mietkonto'su + Mahnung geçmişi değişmedi**, Untermieter kendi Mietkonto'su ve kendi borcuyla çalışıyor.

**Definition of Done: 8/8** — kod ✅ · testler ✅ · UX ✅ · çelişen legacy akış yok ✅ (2.1d ile iki form
birebir aynı davranıyor) · review ✅ (tasarımla satır satır karşılaştırma, 5 sapma bulundu ve kapatıldı) ·
deploy ✅ · prod smoke ✅ · kritik boşluk yok ✅.

**Bilinçli ertelenen:** aynı dairede Untermieter → **Faz 4** · WG / Zimmervermietung → **Faz 3**.

**Açık teknik borçlar (backlog, kritik değil):**
- `Neuer Mieter` sihirbazı Untermieter'i desteklemiyor (üçüncü giriş yolu) → **Sprint 2.2 kapsamında**.
- `ImmobilienView` kiracı satırında rozet yok (rozet MieterView kartı + Mietkonto başlığında).
- Hauptmieter silinirse `parent_tenancy_id` sarkıyor (rozet ada çözülemez → sadece `🔗 Untermieter`; borç etkilenmez).
- Aday listesi bina eşleşmesi `property_name + property_address` string'ine dayanıyor (feed'de `property_id` yok).
- `tFull` yüklenmeden Form A'da filtre kısa süre eksik kalabilir → backend 400 ile yakalar.
- Prod'da Untermieter Mahnung PDF'i ayrıca denenmedi (E2E'de kanıtlı).

**Bu sprint gerçekten bitti mi? EVET.** Kullanıcı gözünden kalan kritik boşluk yok; açık maddeler
ya bilinçli sonraki faz ya da Sprint 2.2 housekeeping kapsamında.

---

## ✅ SPRINT — P0 Guided year picker (no empty wrong-year statement) — CLOSED (canlı `0955961`, 2026-07-17)
**Single goal (the one approved P0 from the QA sprint):** the bare `prompt()` for the settlement year let
a landlord open an empty statement for a year with no tenants → "the app is broken". Replaced with an
in-app year picker: the most recent year WITH tenants is "★ empfohlen"; a year with an existing draft
shows "✎ Bearbeitung fortsetzen" and opens it (no silent duplicate); a no-tenant year is dimmed
"⚠ kein Mieter" and, if clicked, warns "trotzdem anlegen?" (not blocked — owner's choice); manual year
kept. Backend `GET /immo/properties/{pid}/nk-jahre` (mieter_aktiv per year + entwurf_id). No schema
change. P1/P2 untouched. Design: `.claude/nk_jahr_picker_ux.md`. Tests: +8. Suite 43/43.

**Go/No-Go — production-verified (5 evidences, not just "PASS"):**
1. Commit: HEAD == origin/main == `0955961c534ced6d7d956eb6bad3da1c12f8f591`.
2. Health: **PASS** (status ok · db connected).
3. No browser prompt() in the year flow: live `/app` button = `onClick={openNewPicker}` (1×),
   `onClick={newNk}` = 0× (removed). Remaining prompt() lives only in dead ImmobilienView inline-NK.
4. Picker in prod HTML: `/immo/properties/{pid}/nk-jahre` fetch + "★ empfohlen" / "kein Mieter" markers.
5. nk-jahre smoke on prod (throwaway building, tenant active 2024-08…2025-12): returned 2026=0, 2025=1,
   2024=1, no drafts — correct; then HARD-deleted, all tables SHA256 == baseline.

Nebenkosten stays feature-complete. Changes only from critical bugs or user feedback; next sprint fully
separate; this sprint not reopened.

## ✅ SPRINT — Zählerstände-Zugang aus Nebenkosten — CLOSED (canlı `5b54654`, 2026-07-17)
**Single goal (user feedback):** meter entry belongs where the landlord works (Nebenkosten), not as a
property-Details tab. Done: removed the 🔢 Zählerstände tab from Immobilien → Objekt; an open Nebenkosten
statement now has a **"🔢 Zählerstände eingeben / verwalten"** button → full-screen modal with the whole
meter matrix for that property+year; closing refreshes the statement. The per-line State-B wizard stays
for a single missing meter. index.html only — no backend/schema change. Suite 43/43, JSX OK.

**Go/No-Go — production-verified from the live server (evidence, not just "PASS"):**
- Commit SHA: HEAD == origin/main == `5b546548e86f516ea15d7ef17ef1b6ad124f9cf6`.
- Health: **PASS** (status ok · db connected).
- Button live: `/app` serves `onClick={()=>setNkZaehlerOpen(true)}>🔢 Zählerstände eingeben / verwalten`.
- Tab gone: live TABS = Übersicht · Einheiten · Mieteingang · Ausgaben · Nebenkosten · Dokumente;
  `tab==="zaehler"` = 0 occurrences. Proof artifact published.

Backlog: Allgemeinstrom single-meter (tracking-only) · €/Einheit price. Nebenkosten stays
feature-complete; changes only from critical bugs or user feedback; next sprint fully separate.

## ✅ SPRINT — Nebenkosten Verbrauch Wizard (in-place) — CLOSED (canlı `f57ad0a`, 2026-07-17)
**Single goal:** the landlord bills consumption without leaving Nebenkosten. "My bill arrived" → enter
the total → Verbrauch → if a meter is missing, an inline panel opens ON THE LINE (missing flats +
"show all") → Anfang/Ende → "Speichern & verteilen" → recomputes in place. No menu trip. Supporting
pieces: allowed-Umlageschlüssel matrix per category (server-validated, Heizkosten locked to
HeizkostenV), data-driven smart default (metered → Verbrauch), Allgemeinstrom fixed to area, standalone
🔢 Zählerstände tab kept as bulk/annual maintenance. Design: `.claude/nk_verbrauch_wizard_ux.md`,
`.claude/nk_schluessel_matrix.md`.

**Go/No-Go (production-verified with a throwaway test building, then HARD-deleted):**
- Migration: **N/A** (no schema change — reuses ImmoZaehlerstand + existing columns).
- Production Health: **PASS** (status ok · db connected).
- Smoke: **PASS** (nk-config allowed-map · State B fallback note when no meters · forbidden key → 400 ·
  enter meters in place → NK recomputes M1 640 / M2 360, no fallback).
- Regression: **PASS** — 7 core tables byte-identical to the pre-deploy baseline; the only delta is one
  owner-created NK draft (nk_abrechnung id 29, property 10) made in the browser during the deploy window
  — real usage, not test residue (test data fully hard-deleted) and not deploy corruption.

> **Bu sprint feature-complete olarak kapatılmıştır. Sonraki değişiklikler yalnızca kritik hata
> düzeltmeleri veya kullanıcı geri bildirimleri sonucunda yapılacaktır.**

Nebenkosten module is now feature-complete. No new features; new ideas → BACKLOG only. This sprint is
not reopened (critical bugs excepted).

## ✅ SPRINT 4 — Verbrauch / Zählerstand engine + HeizkostenV (canlı `15ddc5b`, 2026-07-16)
Metered costs split by ACTUAL consumption (Zählerstände); heating/hot-water obey HeizkostenV (§7):
Grundkosten % by area + Verbrauch % by meter (default 30/70, per-line 30–50, snapshot-frozen). A
moved-out tenant is billed for their real consumption (Zwischenablesung). Missing readings → Wohnfläche
fallback + note. CALC_VERSION 3→4. Report: `.claude/heizkosten_v_architecture.md`.
- Schema: one additive+nullable column `nk_kostenposition.grund_prozent` (boot-ALTER, no backfill).
- Tests: engine 32/32 + **E2E 27/27 through the real API** (create→readings→NK→finalize→PDF). Suite 42/42.
- **Go/No-Go GREEN — production-verified with a throwaway test building (created via API, HARD-deleted):**
  Backup PASS · Migration PASS (grund_prozent added t+210s) · Health PASS · Regression PASS (8 tables
  SHA256 identical) · **Smoke PASS on prod** (Wasser 700→750/510/440 · HeizkostenV 1000→640/360, Grund
  300 + Verbrauch 700 · Finalize+Snapshot: meter 70→9999 after finalise, result stayed 640 · PDF ok) ·
  **Data clean PASS** (after HARD-delete, all 8 core tables byte-identical to the pre-deploy baseline).
- NOTE: prod has 0 Zählerstände — the owner must enter unit meter readings before their own Verbrauch
  lines compute; until then they fall back to Wohnfläche with a note.

## ✅ SPRINT 3 — Allocation Engine (Personenzahl · Individuell · Eigennutzung)
**Engine-only part deployed `16a3bb5` (2026-07-15).** Extension (in-screen UI + Individuell +
Eigennutzung) code+tests+docs complete — closing with ONE production deploy (Go/No-Go below).
Full report: `.claude/sprint3_final_report.md`. Arch decisions: `.claude/nk_architecture.md` → D1–D3.

**4 of 5 Umlageschlüssel now fully automatic** (Wohnfläche · Wohneinheiten · Personenzahl · Individuell):
enter the invoice total once → the engine reads the data and splits per tenant × Zeitanteil.
- **Personenzahl** — persons per flat; vacant flat = 0; missing count → honest Wohnfläche fallback
  naming the tenant. `a4fb6bb` adds the in-screen person entry.
- **Individuell** (`3217cb7`) — exact euro per tenant; rest→landlord; over-assignment scaled+note;
  reads `NkKostenposition.individuell` (no schema change). Schlüssel-driven **dynamic cost form**.
- **Eigennutzung** (`2b1f382`, model B) — owner-occupied flat carries `ImmoUnit.eigennutzung_personen`;
  counted in the person split, borne by the owner, never a tenant/debtor. Eigennutzung ≠ Leerstand.
- Invariant `Σ tenants + Eigennutzung + Leerstand == total` holds for all keys. CALC_VERSION 2 → 3.
- Tests: engine 71/71, full suite 40/40, JSX OK. `a8897a9` locks the 3 Eigennutzung behaviours.
- **Schema:** one additive+nullable column (`immo_unit.eigennutzung_personen`) — the only deviation
  from the original "code-only" scope, deliberately accepted (see report §2.5).
- **Deferred → Sprint 4:** Verbrauch engine + HeizkostenV (separate legal design).

---

## CLOSED — Sprint 3: "Personenzahl Allocation Engine"

**Opened:** 2026-07-15
**Scope (approved):** switch on the Personenzahl allocation key ONLY. Verbrauch = next; HeizkostenV =
a separate later sprint with its own legal/architecture design (no HeizkostenV rules added here).
**Constraints (binding):** NO DB change (use the existing `immo_tenancy.personenzahl`) · keep the
Zeitanteil logic · Leerstand stays with the landlord · the invariant Σ(tenant shares)+Leerstand ==
umlagefähige total holds · Snapshot/Finalize behaviour unchanged · Single-Ledger preserved · all new
computation in the rules layer (`immo_nebenkosten.py`).
**Key design (person-based):** a vacant unit has 0 persons → contributes 0 weight (no invented head
count); the cost is split among the actual occupants by personenzahl × Zeitanteil. If any active
tenant lacks personenzahl, the position falls back to Wohnfläche WITH a note (no silent wrong split).

- [ ] C1 Rules: personenzahl computed in `basis_weight`/`verteile`; bump CALCULATION_VERSION. Unit +
      invariant + regression tests. No DB, no UI change (picker+field already exist from Sprint 2 C4).
- [ ] C2 Deploy + production smoke (single-water-meter statement split by persons) + sprint close.

---

## CLOSED — Sprint 2 and earlier below

## ✅ SPRINT 2 CLOSED (2026-07-15) — full report: `.claude/sprint2_final_report.md`
Deployed `0c001c4` · Go/No-Go fully green (migration/smoke 12-12/regression 9-9/rollback ready) ·
suite 39/39 · all business data SHA256-identical. A landlord can now produce a legally usable
Nebenkostenabrechnung per tenant (Wohnfläche×Zeitanteil + Leerstand → landlord, Vorauszahlung from
`monat_nk_soll`, Guthaben/Nachzahlung, immutable snapshot, finalise=lock, per-tenant + overview PDF).
Personenzahl/Verbrauch/HeizkostenV/OCR are data-ready and deferred to Sprint 3 (code-only, no
migration). Masterplan #8 done for Faz-1.

---

## CLOSED — Sprint 2: "Nebenkostenabrechnung" (Masterplan #8 ⭐⭐⭐)

**Opened:** 2026-07-15
**Goal:** a small landlord produces a legally usable annual utility-cost statement (§556 BGB) per
tenant — inside AutoTax, no Excel, no Steuerberater. NOT expense tracking.
**Architecture (approved):** `.claude/nk_architecture.md` — 3 binding principles: (A) immutable
settlement snapshot is the record of truth, not the PDF; (B) finalise = legal lock; (C) Single-Ledger
— Vorauszahlung only from `monat_nk_soll`. Full DB now; Sprint 2 computes Wohnfläche/Wohneinheiten,
Heizkosten/Personenzahl/Verbrauch/Individuell are data-ready and stubbed (Sprint 3, code-only).

- [x] C1 Schema (2 tables + personenzahl/mea) + `immo_nebenkosten.py` rules + tests (57). No endpoint/UI.
- [ ] C2 Endpoints + per-tenant & overview PDF + tests (final=immutable, umlagefähig defaults, snapshot)
- [ ] C3 Nebenkosten tab: cost entry + result cards + Leerstand card
- [ ] C4 Finalise (freeze snapshot) + PDF + 12-month warning + polish
- [ ] C5 Deploy + production smoke (a real 3-flat statement) + sprint close

**Sprint exit report goes here when closing.**

---

## CLOSED — earlier sprints below

---

## ✅ SPRINT 1 EXIT REPORT — closed 2026-07-15

**Deployed:** `45fa928` · production `/health` ok · **production smoke 17/17 + regression 11/11** ·
suite **37/37** · **all existing business data byte-for-byte unchanged (sha256 before == after)**.

### Completed — a landlord can now do an entire handover inside AutoTax
| Masterplan | What is live | Proof (production) |
|---|---|---|
| **#6 Übergabeprotokoll** ⭐ | 5-step wizard on the tenant screen (Start · Räume · Zähler · Schlüssel · Unterschrift). Rooms pre-filled with their elements, 4-step condition scale, notes, defects derived automatically. | smoke ①②: 5 rooms pre-filled, Mängel derived from a "beschädigt" floor |
| **Fotos** | 📷 opens the phone camera directly; photos are attached per room and downscaled server-side | smoke ③: 186 KB → **11 KB**, EXIF rotation honoured |
| **#7 Zählerstände** ⭐ | Strom/Wasser/Warmwasser/Gas/Heizung with meter number, unit and photo — during the handover AND standalone. History + consumption + bar chart on the tenant screen. | smoke ④⑪: 12345,5 → 13000 kWh = **654,5 kWh derived** |
| **Digitale Unterschriften** | Two canvases signed with the finger. A typed name or an empty canvas is refused. | smoke ⑥ |
| **Lock** | Both signatures → `abgeschlossen`. Every write is refused with **409**: edit, re-sign, add a meter, add a photo, delete. A correction is a new Nachtrag. | smoke ⑨: **5/5 refused** |
| **PDF** | Letterhead · flat + parties · room-by-room table (defects in red) · Mängel list · meter table · keys · photos by room · **both signatures as images** + date | smoke ⑧: 9.4 KB PDF with photo + signatures |
| **#5 Wohnungsgeberbestätigung** | §19 BMG PDF next to a real **"Anmeldung erledigt"** checkbox — the chip existed since the module was written and **no UI could ever tick it** | smoke ⑩: WGB 200 + chip ticked and it sticks |

### Found by the production smoke test (fixed before closing)
- **Mahnung history read backwards** for letters written on the same day (`datum.desc()` had no
  id tiebreak). The dunned amounts were always right; only the order was wrong. Fixed in
  `45fa928`, verified live: 1. Mahnung → Zahlungserinnerung → … newest first.
- (A false alarm worth recording: a smoke assertion marked a FUTURE month unpaid and expected
  debt. The product was right — a month that is not due yet is not debt. The test was wrong.)

### Regression — every existing landlord function still works (rule 5)
Bu Ay/Mieter (+`summe`) · Mietkonto (12 rows) · Mahnung (amount = the card, escalation) ·
Berichte + Dashboard (Rückstand == the card — no third book) · Immobilien · Accounting ·
and the Sprint-0 core: **NK in the Soll (470, not 400)**, previous-month arrears, and a
Mieteingang payment settling the debt (470 → 0). **11/11 green.**

### Deliberately deferred
- E-mailing the protocol/WGB to the tenant → **Sprint 3** (together with the Mahnung e-mail).
- Nachtrag flow (a "correction of" link between two protocols) — the rule is enforced, the
  convenience link is not built.
- Übergabe from the Immobilien screen (today it lives on the tenant, where the landlord looks).

### Open risks
1. Photos live on the Railway disk (830 GB free). A landlord with many handovers will grow it;
   no retention policy exists yet.
2. The signature is a **document signature** (like a scanned one), not a qualified electronic
   signature (QES). The UI does not claim otherwise — keep it that way.
3. Still open from Sprint 0: the ledger's Soll is Kalt-only (audit domain only, no user sees it)
   · the Railway *Postgres* service variables hold an outdated password · the acquisition funnel
   is still broken (landing CTA opens login, not registration).

### Is this sprint really finished?  **YES.**
All eight DoD conditions: code complete · 37/37 tests · UX checked (the wizard is the screen a
landlord uses standing in a flat) · no contradicting legacy flow (the handover is new ground;
the lock makes the document unambiguous) · reviewed commit by commit · deployed · smoke-tested
on production with a complete real workflow · no critical gap in the handover.

**Next: Sprint 2 = Nebenkostenabrechnung** — now genuinely unblocked: NK is tracked as owed
(Sprint 0) and the meter readings that Heizkosten/Wasser must be split by exist (Sprint 1,
`verbrauch_zeitraum()` is already written and tested).

---

## CLOSED — Sprint 1: "Move-in / Move-out Package"

**Opened:** 2026-07-14 (right after Sprint 0 closed)
**Serves:** `VERMIETER_MASTERPLAN.md` #6 Übergabeprotokoll ⭐ · #7 Zählerstände ⭐ · #5 WGB
**Goal (user):** *a landlord must complete an entire tenant handover inside AutoTax* — no Word,
no Excel, no paper, no PDF hunting.
**Scope:** Übergabeprotokoll · Zählerstände · Fotos · digitale Unterschriften · PDF.
**Plan + design:** `.claude/sprint1_plan.md`. **Not in scope:** e-mailing the PDF (Sprint 3).

Next: **Sprint 2 = Nebenkostenabrechnung** · **Sprint 3 = Mahnung improvements + e-mail sending.**
Customer value first, automation second.

- [ ] C1 Schema (immo_protokoll, immo_zaehlerstand, ImmoDocument.protokoll_id/raum) + pure rules
      module + unit tests. No endpoint, no UI, no behaviour change.
- [ ] C2 Endpoints + PDF + tests (incl. "abgeschlossen = immutable")
- [ ] C3 The 5-step wizard UI, phone-first (rooms · meters · keys · signatures)
- [ ] C4 Zählerstände history + consumption chart + WGB step that finally ticks `anmeldung_done`
- [ ] C5 Deploy + production smoke (a real end-to-end handover) + sprint close report

---

## CLOSED — Sprint 0: "Fundament — make Mietkonto tell the truth"

**Opened:** 2026-07-14
**Serves:** `VERMIETER_MASTERPLAN.md` items #1 #2 #3 (marked ✅ there, **not actually done**) and
unblocks #8 Nebenkostenabrechnung.

**Why this one, and not straight to the masterplan's 🔴 items:** the Exception Engine sprint
(2026-06-23…26) shipped at ~80%. The new model was added but the old flows were never removed, so the
product now tells three different truths about the same money (Bu Ay vs. Mieteingang tab vs. Berichte),
and the debt figure itself is wrong (NK missing, previous months + previous years invisible).
Nebenkostenabrechnung (#8, ⭐⭐⭐) sits directly on top of this: it needs a correct Soll incl.
NK-Vorauszahlung. Building #6/#7/#8 on a Mietkonto that miscounts money would mean shipping a second
floor onto a cracked foundation — exactly what "Finish > New Features" forbids.

**Scope (evidence: code review 2026-07-14, file:line in `.claude/immo_finish_review.md`)**

### A. Truth bugs — the product currently lies about money (P0)
- [ ] A1 Arrears from *previous months* are invisible on "Bu Ay" → screen can say "✅ Alles bezahlt"
      while the tenant owes €1.200. (`index.html:2487-2492`, `immo_api.py:1488-1502`)
- [ ] A2 Arrears are year-scoped → unpaid December vanishes on 1 January and cannot be dunned.
      (`immo_api.py:1488-1502`, `190`, `1616`)
- [ ] A3 Nebenkosten not part of Soll → debt and the Mahnung amount are short by the NK every month.
      (`immo_api.py:832-838`, `1520`, `1631` vs `index.html:2685`)
- [ ] A4 Orphan delete: deleting a property/unit leaves its tenants live on Mieter + Bu Ay.
      (`immo_api.py:375-385`, `930-940`, `193-199`) — was OPEN_ITEMS P1
- [ ] A5 Mahnung letter: no tenant address, no concrete deadline date, signed "Die Hausverwaltung"
      instead of the landlord. (`immo_api.py:1627-1636`)

### B. Contradicting legacy flows — DoD condition #4 (P0)
- [ ] B1 **ONE accounting model, many UIs** (user decision 2026-07-14 — Mieteingang is NOT removed).
      Introduce a single **Payment Service**; every payment path is only a UI on top of it:
      "Bezahlt" button · partial payment · Mieteingang tab · (future) bank import.
      All of them write the **Exception Engine** model; every read surface (Bu Ay, Mietkonto, Mahnung
      amount, Berichte, Nebenkosten) derives from it and never recomputes its own truth.
      Today the Mieteingang tab writes ImmoRent rows that change no debt number → payment recorded,
      debt unchanged. (`immo_api.py:1104`, `1505-1508`; `index.html:2914-2921`)
      **Mandatory: never two parallel debt systems.** See CLAUDE.md → "Architecture law".
- [ ] B2 "📊 Berichte" contradicts itself and Bu Ay: Gewinn negative while its own detail list is
      positive, income chart always zero, "Miete Jun fehlt" for tenants Bu Ay calls ✓ sorgenfrei.
      (`immo_api.py:1155-1162`, `1213`, `1319`, `1379-1387`)
- [ ] B3 Dead columns/flags: `auto_paid` (dead, still ALTER TABLE'd every boot), `offene_monate`
      wrongly commented "(dormant)" although it stores the live exception data. (`models.py:918-919`)

### C. UX — the module is unusable/untrustworthy without these (P1)
- [ ] C1 German UI shows Turkish buttons: "✓ Ödendi" / "✗ Ödenmedi" are the primary actions.
      (`index.html:2695-2696`, `2634-2635`)
- [ ] C2 "✗ Ödenmedi" and "📨 Mahnung" fire with no confirmation; Mahnung persists a legal record
      with no way to delete it. (`index.html:2503`, `2696`, `2709`)
- [ ] C3 Error = wrong empty state ("Noch keine Immobilie" on API failure), Berichte hangs on
      "Lädt…" forever, no retry. (`index.html:2785`, `2334`, `2483`)
- [ ] C4 Mahnung is hardcoded `stufe:1` → escalation (2./3. Mahnung) unreachable; Mahnung history
      endpoint exists but has no UI. (`index.html:2486`, `2566`; `immo_api.py:1428`, `1529`)
- [ ] C5 "Dauerzahlung" is never explained *inside* the module — the app assumes rent is paid and
      shows ✓ without telling the landlord. One sentence on Bu Ay + Mieter.
- [ ] C6 Bu Ay (the app's landing screen for every user) is not mobile-aware. (`index.html:2493-2506`)
- [ ] C7 Field hints (3 languages) on Immobilien inputs — user reported the forms are "çok karışık".
- [ ] C8 Tenancy Detail: no year switcher → last year's Mietkonto unreachable. (`index.html:2579`)

---

## ✅ SPRINT 0 EXIT REPORT — closed 2026-07-14

**Deployed:** `32ace6f` · production `/health` ok · **production smoke test 9/9 green** ·
suite **35/35 green** (incl. the ledger flag forced ON).

### Completed
| | What | Proof |
|---|---|---|
| A1 | Arrears from previous months surface — "✅ alles bezahlt" can no longer hide 940 € | smoke 4+5 |
| A2 | Arrears cross the year boundary — unpaid December survives 1 January | test_immo_payment_service |
| A3 | **Nebenkosten are part of the Soll.** Debt + Mahnung = Warmmiete (470, not 400) | smoke 4 |
| A4 | Deleting a property/unit deletes its tenants — no orphans accruing debt | smoke 10 |
| A5 | The Mahnung is a real letter: recipient address, itemised months, concrete deadline date, landlord's IBAN + signature (no more "Die Hausverwaltung") | test_immo_delete_mahnung |
| B1 | **The sprint bug:** a Mieteingang payment now reduces the debt (940 → 470); deleting it restores it | smoke 6+7 |
| B2 | Reports derive from the Exception Engine: no negative Gewinn, no flat-zero income chart, no false "Miete fehlt" | smoke 9 |
| B3 | Dead `auto_paid` documented; `offene_monate` correctly marked as the live debt store | models.py |
| C1–C8 | German buttons, confirm dialogs, loading/error/retry, Dauerzahlung explained in-module, mobile Bu Ay, year selector, 3-language field hints, Mahnung escalation + history | commits 3B/4 |
| — | **Architecture:** Payment Service is the only writer; `PaymentRepository` port (immo_rent today, ledger tomorrow); no frontend computes debt | test_immo_no_third_book |

### Found by the production smoke test (would have shipped otherwise)
**The third book was LIVE.** `IMMO_LEDGER_READ=1` is set in production, and `portfolio_view()`
overwrote the debt fields with the ledger's Kalt-only arrears: the Berichte screen said
**2.800 €** while the Mieter card, Bu Ay and the Mahnung all said **940 €**. Every unit test
passed because they ran with the flag OFF. Fixed in code (`32ace6f`) — the ledger can no
longer be a debt source for any user-facing screen, whatever the environment says. New
regression test forces the flag ON.

### Deliberately deferred
- **Historical Payment Backfill** — dry-run proved 0 HIGH rows and no debt change → skipped (see backlog).
- `auto_paid` column drop (destructive migration).
- Untermieter (TDD spec still skipped).
- Ledger Phase 1+ / cutover.

### Open risks
1. **The ledger's Soll is still Kalt-only** and knows nothing about the exception engine. It
   is now a pure audit domain (`/immo/_ledger/*`), so no user sees it — but it MUST be
   aligned before any ledger cutover, or the third book returns.
2. `IMMO_LEDGER_READ=1` is still set in production. It is now inert for user-facing debt,
   but the variable is misleading — consider removing it.
3. The Railway *Postgres* service variables hold an **outdated password** (the working one is
   in AutoTax-Hub's `DATABASE_URL`) → backup/restore scripts reading them fail silently.
4. The screens were verified through the API and the JSX compiler, **not** by a human looking
   at the rendered UI on a phone. First real landlord session may still surface layout nits.
5. The acquisition funnel is still broken (the landing CTA opens the login form, not
   registration) — out of this sprint's scope, parked in the backlog.

### Is this sprint really finished?  **YES.**
The eight DoD conditions are met: code complete · 35/35 tests green · UX checked · the
contradicting legacy flows are gone (two payment books AND the ledger third book) · reviewed
commit by commit with BEFORE/AFTER evidence · deployed · smoke-tested on production · no
critical gap left in the landlord accounting flow. The residual items above are named, owned
and parked — none of them makes the product tell a landlord a wrong number.

Masterplan #1 #2 #3 are now genuinely ✅. #8 (Nebenkostenabrechnung) is unblocked: the
NK-Vorauszahlung is finally tracked as owed.

---

## BACKLOG — parked, do NOT start before the active sprint closes

### [OPS] Railway Postgres servisinin PGPASSWORD / DATABASE_PUBLIC_URL senkronsuzluğu  (bulundu 2026-07-21)
Faz 3 ön kontrolü sırasında ortaya çıktı: Postgres servisinin `PGPASSWORD` (ve dolayısıyla
`DATABASE_PUBLIC_URL`) değeri, çalışan veritabanının gerçek şifresiyle **uyuşmuyor**. Hem TCP proxy
üzerinden (`roundhouse.proxy.rlwy.net`) hem de Postgres container'ının içinden
`FATAL: password authentication failed for user "postgres"` alınıyor.

**Etkilenmeyen:** uygulama (`/health` → `db: true`) ve **haftalık R2 yedeklemesi** — ikisi de
AutoTax-Hub servisinin kendi `DATABASE_URL`'ini kullanıyor (`autotax/backup.py:43,94`), o çalışıyor.
**Etkilenen:** elle `psql` / proxy ile bağlanma yolu — yani bir **restore veya acil elle sorgu** anında
ihtiyaç duyulacak erişim. Geçici çözüm: sorgular `railway ssh --service AutoTax-Hub` ile app
container'ından çalıştırılabiliyor (Faz 3 ön kontrolü böyle yapıldı).

**Yapılacak:** Railway panelinden Postgres şifresinin yenilenmesi/senkronlanması + `psql` ile bağlantının
bir kez doğrulanması. **Faz 3 kapsamına DAHİL DEĞİL** — bağımsız ops işi.

### Allgemeinstrom single (building-level) meter field  (user feedback 2026-07-17 — parked)
The landlord asked for an Allgemeinstrom meter field. It would NOT change the NK split (common
electricity has no per-flat measurement → split by Wohnfläche/Wohneinheiten from the total invoice), so
it's a tracking-only building-level reading. Parked to keep the current sprint single-goal; revisit if
the tracking value is confirmed.

### Optional €/Einheit price on a Verbrauch line  (idea 2026-07-17 — NOT this sprint)
Some landlords know only the unit price (e.g. 4 €/m³), not the total invoice. An optional "€/Einheit"
field could compute total = consumption × price. Standard German NK splits the TOTAL by ratio (no price
needed), which is what we ship. Park as a power-user extra; do not add to the daily flow.

### HeizkostenV Exceptions  (deferred 2026-07-16 — needs separate legal design)
The ≤2-unit building where the owner occupies one flat may split heating/hot water FREELY (§2
HeizkostenV) — i.e. Wohnfläche is allowed instead of the mandatory Grund/Verbrauch split. Deliberately
NOT built now: Sprint 4's goal was the general, safe HeizkostenV engine; this is a legal special case.
Standard scenarios must be flawless first. To be handled later under "HeizkostenV Exceptions" with its
own design + legal review. Until then Heizkosten/Warmwasser are locked to Verbrauch (HeizkostenV) for
everyone (safest default). See `.claude/nk_schluessel_matrix.md`.

### Historical Payment Backfill  (decided 2026-07-14: SKIPPED for Sprint 0)
Fill `immo_rent.fuer_jahr` / `fuer_monat` on the 10 pre-Sprint-0 payment rows so that old
payments are attributed to the rent month they settle.

**Why it was skipped:** it delivers no user-visible value today and adds deployment risk.
The read-only dry-run (`scripts/immo_backfill_dryrun_standalone.py`, run against production
2026-07-14) proved it: **0 rows classified HIGH** (the only class that may ever be migrated
automatically), 8 MEDIUM, 2 LOW — and **no tenant's debt would change** (both live tenants
carry no reported exception, so Dauerzahlung already counts those months as paid: 0,00 → 0,00).
Sprint 0's goal is the accounting foundation, not perfect historical metadata.

**When it is picked up** it must be a standalone migration with its own tests:
- classification rule to revisit: a payment booked on day 1–3 is, in German practice, THAT
  month's rent (due by the 3rd working day) — not a late payment for the previous month.
  With that fixed, YURONG's Jan–May rows (400,00 = exact Warmmiete) become HIGH.
- rows that need a human decision regardless:
  - VANELLE id 37: 540,00 paid on 2026-06-25 while June's Soll is 270,00 (vereinbarte
    Erstmiete) → covers more than one month, or includes the deposit.
  - YURONG ids 30 + 32: two identical 400,00 payments on 2026-06-01 → instalments or a
    duplicate row.
  - ids 14 + 31: payments with **no tenancy_id** at all (270,00 / 460,00).
- decide only after real pilot users exist — it may never be worth it.

**Ops finding while running the dry-run (separate small task):** the Railway *Postgres*
service's `PGPASSWORD` / `DATABASE_PUBLIC_URL` hold an OUTDATED password; the working one is
in the *AutoTax-Hub* service's `DATABASE_URL`. Backup/restore scripts that read the Postgres
service vars would fail silently.


### Funnel / conversion (next sprint candidate — evidence in `.claude/immo_finish_review.md`)
- Landing CTAs point to `/app?action=register` but the SPA never reads the param → every visitor
  who clicks "Kostenlos starten" lands on the **login** form. (`index.html:492`)
- Signup screen is in English on a German funnel ("Welcome back", "John Smith"); brand flips from
  AutoTax.Cloud to AutoTax-HUB + BETA badge. (`index.html:615-630`)
- Password rules disagree in 3 places (client ≥6, hint 8+special, backend 8+upper+digit) → 400s.
  (`index.html:557`, `621`; `main.py:5470-5475`)
- Register throws away the returned token and forces a second login. (`index.html:568-569`)
- "14 Tage kostenlos" is advertised but never provisioned (`DEFAULT_REGISTRATION_PLAN=free`,
  `trial_ends_at` only set when default is `pro`). (`main.py:5484-5489`) — also a misleading-ad risk.
- Prices disagree in 4 places (landing 15/39/89 · backend PRICING 9/29 · admin 15/39/89/149 ·
  chatbot "Pro €20"). (`landing.html:872-929`; `main.py:12613-12619`, `5078`, `13157`)
- Stripe kill switch defaults ON → checkout 503 unless `STRIPE_KILL_SWITCH=0` is set. (`billing.py:61`)
- **Zero analytics anywhere** → no funnel step is measurable today.
- Landing never mentions Mahnung / Leerstand / Nebenkostenabrechnung / Kaution / Rückstand — the
  landlord module is invisible to a visitor, while the app is landlord-first for everyone
  (`_initialPage` → "bu_ay" for every user, `index.html:7214-7220`).
- Landing has zero screenshots and zero real testimonials; Impressum e-mail is on a different
  domain (autotaxhub.de) and USt-ID says "wird nachgereicht". (`main.py:2386`)

### Immobilien — deliberately out of this sprint
- Ledger Phase 1+ (backfill/apply). `IMMO_LEDGER_READ` is OFF in prod; the read path is inert.
- Untermieter feature (TDD spec exists and is skipped: `tests/test_immo_untermieter.py`).
- Nebenkostenabrechnung (NK settlement) module.
- Dead endpoints with no UI: `/immo/events` CRUD, `/immo/dashboard`, `/immo/tenancies/{tid}/mahnungen`,
  legacy flat `/immo/tenants`.

### Other
- Premium "invisible strong engine" for the first 5 documents (flag-gated design ready).
- Landing redesign (control-center language, no "AI" hype).
- Root-level one-off scripts (~75 untracked files) → `scripts/scratch/`.
