# Spreadsheet OCA — Demo Veri ve Test Rehberi

> 💡 **UYGULAMA ICI YARDIM:** Spreadsheets app'inde yeni **Help & Examples** menusu
> altinda 4 canli rehber e-tablo bulunur — acip kopyalayabilirsiniz:
> - ✨ Ozellikler ve Menuler
> - 📈 Tahminleme (FORECAST, TREND, MOVING_AVG)
> - 📊 Donem Karsilastirma (PERCENT_CHANGE, GROWTH_ARROW, YOY, VARIANCE)
> - 🧰 Core Formulleri (BALANCE, CREDIT, PIVOT, CURRENCY.RATE...)

**Olusturuldu:** 2026-04-17  
**Sunucu:** https://bv5.badvogel.nl  
**DB:** badvogel-o192-2026-4  
**Admin:** developer1@badkamertien.nl

Bu dokuman Odoo uzerinde olusturulmus **tum DEMO verilerin neler oldugunu, nerede bulundugunu ve ne ise yaradigini** aciklar.

---

## 🎯 Hizli Bakis — Kurulu Moduller

**26 yeni spreadsheet modulu kuruldu** (toplam 30 `spreadsheet_*_oca`).

Sunucuda mevcut dashboard sayisi: **22** (12 Odoo core + 10 bizim yeni).

---

## 📊 DEMO Kayitlari

Tum DEMO kayitlari `DEMO` prefix'i ile basliyor, boylece kolayca ayirt edilebilirler. **Silinmemeli** — referans olarak kalsin.

### Spreadsheet Dokumanlar
| id | İsim | Icerik |
|----|------|--------|
| 1 | DEMO - Satis Ozeti Q1 2026 | **Turkce** ana demo dokuman. "Satislar" sheet'i: Ocak-Subat-Mart ciro, siparis sayisi, ortalama siparis (formul). Toplam satirinda `=SUM(B2:B4)` formulleri. |
| 2, 3, 4 | DEMO - Sablondan Uretilmis Spreadsheet | Template'ten olusturulanlar (bu sayi `usage_count`'u gosterir). |

### Template (Sablonlar)
**Erisim:** Spreadsheets menusu > Templates  
**2 sablon olusturuldu:**
1. **DEMO Sablon - Aylik Satis Takibi** (Sales kategorisinde)
   - Aciklama: "Her ay ciro, siparis sayisi ve ortalama siparis degerini takip et"
   - `usage_count = 2` (2 kez kullanilmis)
2. **DEMO Kaydedilmis Sablon** (Finance kategorisinde)
   - 'Save as Template' wizard ile olusturuldu
   - Aciklama: "'Save as Template' wizard testiyle olusturuldu."

**Kategoriler (seed):** Sales, Finance, Human Resources, Operations, General

### KPI Alert
**Erisim:** Spreadsheets > Configuration > KPI Alerts (veya e-tablo form'unda smart button)

| id | Adi | Kosul | Durum |
|----|-----|-------|-------|
| 1 | DEMO - Aylik Satis Uyarisi | `Satislar!B5 > 40000` | ✅ Tetiklendi (45600 > 40000) |

- `last_value = 45600` (JS sync simulasyonu)
- Cooldown: 24 saat
- Admin'i bildirir (mesajlasma panelinde)
- **Test Alert** butonu ile manuel tetiklendi → chatter'da mesaj olusmali

### Version History
**Erisim:** Spreadsheet form > "Versions" smart button

| id | Version | Spreadsheet |
|----|---------|-------------|
| 1 | v1.0 - ilk hali | DEMO - Satis Ozeti |
| 2 | v1.1 - ornek degisiklik | DEMO - Satis Ozeti |

- **Visual Diff vs Current** sekmesinde cell-level karsilastirma gorunur
- **Restore This Version** ile geri donulebilir

### Scheduled Refresh
**Erisim:** Spreadsheets > Configuration > Refresh Schedules

| id | Adi | Interval |
|----|-----|----------|
| 1 | DEMO - Saatlik Otomatik Yenileme | 1 saat |

### Email Report
**Erisim:** Spreadsheets > Configuration > Email Reports

| id | Adi | Format | Gonderici | Alicilar |
|----|-----|--------|-----------|----------|
| 1 | DEMO - Haftalik Satis Raporu | XLSX | Haftalik | Admin + info@example.com |

- **Send Now** butonu ile manuel gonderilebilir (outgoing mail server gerekir)

### Public Share
**Erisim:** Spreadsheets > Configuration > Public Share Links

| id | Adi | Ayarlar |
|----|-----|---------|
| 1 | DEMO - Musteri Paylasim Linki | Parola: `demo2026`, 30 gun, indirme acik |

**Test edildi (view_count = 1):**
- URL: https://bv5.badvogel.nl/spreadsheet/public/{TOKEN}
- Parolasiz → "Password Required" ekrani
- Parola ile → Read-only HTML render, Turkce tablo, merge cell destegi

### API Token
**Erisim:** Spreadsheets > Configuration > API Tokens

| id | Adi | Rate Limit | Webhook |
|----|-----|------------|---------|
| 1 | DEMO - Test Entegrasyon Token | 60/dakika | https://webhook.site/demo |

**Test edilen endpoint'ler:**
```bash
# 1. List all accessible spreadsheets
curl -H "Authorization: Bearer {TOKEN}" https://bv5.badvogel.nl/api/spreadsheet/list

# 2. Get full spreadsheet data (includes raw JSON)
curl -H "Authorization: Bearer {TOKEN}" https://bv5.badvogel.nl/api/spreadsheet/1

# 3. Get flat cells of a sheet
curl -H "Authorization: Bearer {TOKEN}" \
  "https://bv5.badvogel.nl/api/spreadsheet/1/cells?sheet=Satislar"
```

Token degerini UI'dan al (view/edit API Token > `token` field).

### Contract & SLA
**Erisim:** Spreadsheets > Contracts & SLA (ust menude)

| id | Adi | Durum | Kalan |
|----|-----|-------|-------|
| 1 | DEMO - Yillik Servis Sozlesmesi 2026 | Expiring Soon | 24 gun |

- Partner: **DEMO Kurumsal Musteri A.S.** (Istanbul, Turkiye)
- Responsible: Admin
- Amount: 12,000
- **2 SLA metrigi:**
  - Uptime Garantisi: Target %99.9, Actual %98.5 → **Breached**
  - Response Time: Target 4h, Actual 6h → **Breached**
- **Renew Contract** butonu ile yenileme denenebilir
- Chatter'da otomatik tracking mesajlari gorunmelidir
- Calendar view'da sozlesme periyodu gorunur

### Vendor Scorecard
**Erisim:** Purchase > Reporting > Vendor Scorecards

| id | Tedarikci | Skor | Detay |
|----|-----------|------|-------|
| 1 | DEMO Tedarikci Ltd. | **92.7/100** | Yuksek performans (green) |

- On-time delivery: %92.5
- Quality rate: %97.8
- Avg lead time: 5.2 gun
- 28 siparis, 45,000 EUR
- Pre-built dashboard: **Vendor Performance** (Dashboards app'inde)

### Dashboard Record Rule
**Erisim:** Spreadsheets > Configuration > Dashboard Data Filters

| id | Adi | Kural |
|----|-----|-------|
| 1 | DEMO - Sadece Kendi Siparislerim | `sale.order` uzerinde `[('user_id', '=', user.id)]` |

- Dashboard: Sales
- Group: Sales User
- **Test icin:** Sadece sales_user yetkisi olan bir kullanici ile Sales dashboard'u acinca sadece kendi siparisleri gosterilmeli (admin icin kural uygulanmaz).

### Portal Dashboard Assignment
**Erisim:** Spreadsheets > Configuration > Portal Dashboards

| id | Dashboard | Partner |
|----|-----------|---------|
| 1 | Invoicing | DEMO Bayi AB |

- Partner `DEMO Bayi AB` portal user olarak set edilirse `/my/dashboards`'ta bu dashboard'u gorecek.
- Read-only HTML rendering (o-spreadsheet lite)

### Consolidation
**Erisim:** Spreadsheets > Consolidation

- Demo atlandi cunku sistemde **tek sirket** var. Birden fazla sirket eklenirse test edilebilir.

---

## 🧪 Test Edilmesi Gereken Ozellikler (Browser'da)

Odoo arayuzunde manuel olarak test edilmeli:

### 1. Tahmin Fonksiyonlari (spreadsheet_forecast_oca)
Yeni e-tablo > bir hucreye:
```
=ODOO.FORECAST(6, B2:B5, A2:A5)
=ODOO.TREND(B2:B5, A2:A5, 10)
=ODOO.MOVING_AVG(B2:B5, 3)
```

### 2. Donem Karsilastirma (spreadsheet_period_comparison_oca)
```
=ODOO.PERCENT_CHANGE(1500, 1200)  // 25
=ODOO.GROWTH_ARROW(1500, 1200)    // "▲ 25.0%"
=ODOO.YOY(1500, 1200)              // 25
=ODOO.VARIANCE(1500, 1200)        // 300
```

### 3. Muhasebe Formulleri (✅ CORE ODOO ile gelir — spreadsheet_account)
```
=ODOO.BALANCE("600000")
=ODOO.CREDIT("1200", "2026-01-01", "2026-12-31")
=ODOO.DEBIT("4000")
=ODOO.RESIDUAL("4000")
=ODOO.PARTNER.BALANCE("4000", partner_id)
=ODOO.FISCALYEAR.START(date)
```
**Not:** `spreadsheet_accounting_formulas_oca` modulumuz core `spreadsheet_account` ile cakistigi icin kaldirildi. Bu fonksiyonlar zaten Odoo core'da gelir (daha fazla: RESIDUAL, PARTNER.BALANCE, FISCALYEAR.START/END, ACCOUNT.GROUP, BALANCE.TAG).

### 4. PDF Export (spreadsheet_pdf_report_oca)
"DEMO - Satis Ozeti Q1 2026" spreadsheet'i ac → **File > Download PDF**. Turkce karakterler, formul sonuclari, stil korunmali.

### 5. Save as Template (spreadsheet_template_oca)
Herhangi bir spreadsheet ac → **File > Save as Template**. Yeni template kategori ile kaydedilir.

### 6. Settings Ekrani
Settings > Spreadsheet sekmesi (tek sekme). 6 block gorunmeli:
- KPI Alerts
- REST API
- Contracts & SLA
- Email Reports
- Scheduled Refresh
- Public Share Links

---

## 🔗 Hizli Linkler

| Sayfa | URL |
|-------|-----|
| Ana Odoo | https://bv5.badvogel.nl |
| Apps List | https://bv5.badvogel.nl/odoo/apps |
| Spreadsheets | https://bv5.badvogel.nl/odoo/spreadsheets |
| Settings | https://bv5.badvogel.nl/odoo/settings |
| Purchase Reporting | https://bv5.badvogel.nl/odoo/purchase > Reporting |
| Portal (as customer) | https://bv5.badvogel.nl/my |
| DEMO Share Link (parola: demo2026) | https://bv5.badvogel.nl/spreadsheet/public/oHTbZp7ZdGt-kQtGdw3O9YUMk3eajPN7R0yQRh-IL0Y |

---

## 🧹 Temizlik (Gerekirse)

DEMO verilerini silmek icin Odoo shell'de:
```python
env["spreadsheet.spreadsheet"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.template"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.kpi.alert"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.version"].search([("name", "like", "DEMO%") ]).unlink()
env["spreadsheet.refresh.schedule"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.email.report"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.public.share"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.api.token"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.contract"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.vendor.scorecard"].search([
    ("partner_id.name", "=", "DEMO Tedarikci Ltd.")
]).unlink()
env["spreadsheet.dashboard.rule"].search([("name", "like", "DEMO%")]).unlink()
env["spreadsheet.portal.dashboard"].search([
    ("partner_ids.name", "=", "DEMO Bayi AB")
]).unlink()
env["res.partner"].search([("name", "like", "DEMO%")]).unlink()
```

Veya test script'ini tekrar calistirmak icin: `python3 _demo_data_test.py` (idempotent — zaten olanlari atlar).

---

## 🐛 Giderilen Hatalar (Installation sirasinda)

Kurulum sirasinda 9 saas-19.2 breaking change bulundu ve `odoo-version-compatibility-matrix.jsx` dosyasina eklendi:

| # | Hata | Cozum |
|---|------|-------|
| 1 | `res.groups.category_id` yok | `privilege_id` kullan |
| 2 | `res.groups.users` yok | `user_ids` kullan |
| 3 | `<group string="Group By">` search view'da yasak | `<group>` bos birak |
| 4 | `ir.cron.numbercall` yok | Bu alani XML'den sil |
| 5 | Form view'da `active_id` tanimsiz | `id` kullan (smart button context) |
| 6 | `spreadsheet_dashboard_group_human_resources` yanlis | `spreadsheet_dashboard_group_hr` |
| 7 | `purchase.menu_purchase_report` yok | `purchase.purchase_report_main` |
| 8 | 6 modul Settings'te 6 ayri sekme olusturdu | 5 modul tek app'e xpath ile eklenir (kpi_alert master) |
| 9 | `ir.config_parameter.get_param` yok | `get_str` / `get_bool` / `get_int` / `get_float` |
