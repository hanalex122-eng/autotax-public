# Contributing — AutoTax Cloud

## Ürün Prensibi (Bağlayıcı)

**AutoTax Cloud, tek bir kullanıcının ihtiyaçlarına göre değil, Almanya'daki küçük ve orta ölçekli ev sahiplerinin ORTAK ihtiyaçlarına göre geliştirilir.**

Her yeni özellik roadmap'e / geliştirmeye alınmadan önce **üç kriteri** sağlamalıdır:

1. Gerçek hayatta **yaygın kullanılan** bir kiralama senaryosunu çözüyor mu?
2. SaaS ürünü olarak **birçok müşteri** tarafından kullanılabilecek kadar **genel** mi?
3. **Mevcut müşterilerin verisini ve çalışma şeklini bozmadan** eklenebiliyor mu?

- Üç cevap da **"Evet"** ise → roadmap'e alınır.
- Aksi hâlde → **Product Backlog**'da bekletilir.

**Tek-kullanıcıya özel senaryolar** (ör. bir müşterinin kendi kiracısı/aile durumu) doğrudan koda gömülmez; **genel bir özellik** olarak soyutlanır ve bu kapıdan geçirilir.

## Belge kuralı

Tüm roadmap ve tasarım belgeleri (`docs/roadmap/*`) bu prensibe **atıf yapmalıdır**.

## İlgili

- **Engineering Constitution:** `CLAUDE.md` — Finish > New Features · ONE accounting model (Single-Ledger) · additive & geriye-dönük-uyumlu · her faz bağımsız/geri-alınabilir deploy.
- **Örnek roadmap:** `docs/roadmap/Flexible_Mietmodelle_Phase1.md`
