# Kurulum ve Test Plani — 26 Modul

Bu doküman Odoo saas-19.2 üzerinde modülleri sırayla kurup test etmek için
adım adım talimatları içerir. Her modül için:
- **Durum**: ⬜ bekliyor / 🟡 devam ediyor / ✅ başarılı / ❌ başarısız
- **Senaryo**: örnek bir kullanım akışı
- **Adımlar**: test için tıklanacak butonlar/girilecek değerler
- **Beklenen**: başarılı kabul kriteri

---

## Hazırlık — Kurulum Öncesi

### A. Modülleri Addons Path'e Ekle
1. Odoo `odoo.conf` dosyasında `addons_path` içine `e:/Odoo-2026-modules/spreadsheet` yolunu ekle
2. Odoo sunucusunu yeniden başlat: `./odoo-bin -c odoo.conf --dev=all`

### B. Apps Listesini Güncelle
3. Odoo arayüzünde **Uygulamalar** menüsüne gir
4. Arama kutusuna tıkla, filtreleri temizle
5. **Uygulamalar listesini güncelle** butonuna tıkla (dev mode aktifse)

### C. Python Bağımlılıkları
6. Terminal: `pip install requests` (webhook için)
7. wkhtmltopdf kurulu olmalı (`wkhtmltopdf --version` ile kontrol)

---

## Faz 1 — Temel Araçlar (3 modül, bağımsız)

### 1. ⬜ `spreadsheet_template_oca` — Şablon Sistemi

**Install**:
- Uygulamalar > "Spreadsheet Template" ara > **Kur**

**Senaryo**: Satış için bir şablon oluştur, ondan yeni spreadsheet üret.

**Test Adımları**:
1. **Spreadsheets** > **New** ile yeni e-tablo oluştur, adını "Aylık Satış Şablonu" yap
2. Bir kaç hücreye veri gir (A1="Müşteri", B1="Tutar", vs.)
3. E-tabloyu aç, topbar'da **File** > **Save as Template** tıkla
4. Wizard açılır: İsim "Aylık Satış", Kategori "Sales" seç, **Save as Template**
5. **Spreadsheets** > **Templates** menüsüne git
6. "Sales" kategorisinde şablon görünmeli
7. Şablon kartında **Use Template** butonuna tıkla
8. Dialog açılır, **Create Spreadsheet** tıkla

**Beklenen**:
- ✅ Yeni e-tablo açılır, içinde aynı veriler var
- ✅ Şablon kartında `usage_count` arttı (1)
- ✅ Template Manager olmayan kullanıcı sadece görebilir, düzenleyemez

---

### 2. ⬜ `spreadsheet_forecast_oca` — Tahmin Fonksiyonları

**Install**:
- Uygulamalar > "Spreadsheet Forecast" ara > **Kur**

**Senaryo**: Geçmiş aylık satış verisinden gelecek ayı tahmin et.

**Test Adımları**:
1. Yeni bir e-tablo aç
2. A sütununa 1-5 (aylar), B sütununa satışlar: 100, 120, 150, 180, 210 gir
3. C1'e formül: `=ODOO.FORECAST(6, B1:B5, A1:A5)` — Ay 6'nın tahmini
4. C2'ye formül: `=ODOO.TREND(B1:B5, A1:A5, 10)` — Ay 10 tahmini
5. C3'e formül: `=ODOO.MOVING_AVG(B1:B5, 3)` — Son 3 ayın ortalaması

**Beklenen**:
- ✅ C1 ≈ 240 (linear trend devamı)
- ✅ C2 ≈ 360 (Ay 10 tahmini)
- ✅ C3 = 180 (150+180+210)/3

---

### 3. ⬜ `spreadsheet_period_comparison_oca` — Dönem Karşılaştırma

**Install**:
- Uygulamalar > "Period Comparison" ara > **Kur**

**Senaryo**: Bu ay vs geçen ay karşılaştır.

**Test Adımları**:
1. Yeni e-tablo aç
2. A1=1500 (bu ay), A2=1200 (geçen ay)
3. B1'e: `=ODOO.PERCENT_CHANGE(A1, A2)` — % değişim
4. B2'ye: `=ODOO.VARIANCE(A1, A2)` — mutlak fark
5. B3'e: `=ODOO.GROWTH_ARROW(A1, A2)` — ok + %
6. B4'e: `=ODOO.YOY(A1, A2)` — yıllık büyüme

**Beklenen**:
- ✅ B1 = 25 (yüzde 25 artış)
- ✅ B2 = 300
- ✅ B3 = "▲ 25.0%"
- ✅ B4 = 25

---

## Faz 2 — PDF Export (1 modül)

### 4. ⬜ `spreadsheet_pdf_report_oca` — PDF Raporu

**Install**:
- Uygulamalar > "Spreadsheet PDF" ara > **Kur**

**Ön-koşul**: wkhtmltopdf kurulu olmalı.

**Senaryo**: Türkçe karakterli bir e-tabloyu PDF olarak indir.

**Test Adımları**:
1. Yeni e-tablo aç, adını "Satış Raporu Mart" yap
2. Hücrelere Türkçe içerik gir:
   - A1="Müşteri" (kalın yap)
   - A2="Öğrenci Ayşe"
   - A3="Şirket Çağrı A.Ş."
   - B1="Tutar"
   - B2=1500, B3=2300
3. B2 ve B3'ü italik yap, renk ekle (kırmızı/yeşil)
4. A1:B1 aralığını merge et
5. C1 hücresine `=SUM(B2:B3)` formülü koy
6. **File** > **Download PDF** tıkla

**Beklenen**:
- ✅ PDF indirir
- ✅ PDF'te Türkçe karakterler doğru görünür (ç,ğ,ı,ö,ş,ü,Ç,Ğ,İ,Ö,Ş,Ü)
- ✅ Formül sonucu (3800) PDF'te görünür, formül metni değil
- ✅ Bold/italic/renkler korunur
- ✅ Merge edilmiş hücre birleşik görünür
- ✅ Üst kısımda şirket logosu + rapor adı

---

## Faz 3 — Uyarı ve İzleme (2 modül)

### 5. ⬜ `spreadsheet_kpi_alert_oca` — KPI Uyarı

**Install**:
- Uygulamalar > "Spreadsheet KPI Alert" ara > **Kur**

**Senaryo**: Satış hedefi aşıldığında uyarı al.

**Test Adımları**:
1. Yeni e-tablo aç, B2 hücresine `1500` gir (literal değer)
2. E-tabloyu kaydet
3. Spreadsheet form görünümünde **KPI Alerts** smart button'a tıkla (0 göstermeli)
4. **New** ile alert oluştur:
   - Name: "Satış Hedefi Aşıldı"
   - Sheet Name: "Sheet1"
   - Cell Ref: "B2"
   - Operator: "> (Greater than)"
   - Threshold: 1000
   - Notify Users: kendini seç
5. Kaydet
6. **Test Alert** butonuna tıkla (header'da)
7. Discuss inbox'u aç
8. E-tablo chatter'ını kontrol et
9. B2'yi 500'e değiştir ve tekrar kaydet
10. **Settings > Technical > Scheduled Actions** > "KPI Alert Threshold Check" > **Run Manually**

**Beklenen**:
- ✅ Test Alert sonrası bildirim geldi (Discuss ve chatter)
- ✅ Cron çalıştıktan sonra, B2=500 için uyarı çıkmadı (cooldown)
- ✅ `last_value` alanı 500'e güncellendi (JS sync)

---

### 6. ⬜ `spreadsheet_version_history_oca` — Versiyon Geçmişi

**Install**:
- Uygulamalar > "Version History" ara > **Kur**

**Senaryo**: E-tabloyu kaydet, değiştir, geri al.

**Test Adımları**:
1. Yeni e-tablo aç, A1="Version 1", B1=100 gir, kaydet
2. Form view'da **New Snapshot** smart button'a tıkla
3. Spreadsheet'i aç, A1'i "Version 2" yap, B1'i 200 yap, kaydet
4. Tekrar **New Snapshot** butonuna tıkla
5. **Versions** smart button'a tıkla (2 görmeli)
6. İlk snapshot'u aç
7. **Visual Diff vs Current** sekmesine geç
8. Özet bölümünde "0 added, 2 changed, 0 removed" görmeli
9. A1 ve B1 için "Changed" rozetleri görünmeli
10. **Restore This Version** butonuna tıkla, onayla
11. Spreadsheet'i aç

**Beklenen**:
- ✅ 2 snapshot oluştu
- ✅ Visual Diff doğru görünüyor (A1: Version 2 → Version 1, B1: 200 → 100)
- ✅ Restore sonrası A1="Version 1", B1=100

---

## Faz 4 — Otomasyon (2 modül)

### 7. ⬜ `spreadsheet_scheduled_refresh_oca` — Zamanlı Yenileme

**Install**:
- Uygulamalar > "Scheduled Refresh" ara > **Kur**

**Senaryo**: E-tabloyu saatlik otomatik yenile.

**Test Adımları**:
1. **Spreadsheets** > **Configuration** > **Refresh Schedules** > **New**
2. Name: "Saatlik Yenileme"
3. Spreadsheet: bir dashboard seç (örn. CRM dashboard varsa)
4. Interval: 1 Hours
5. Kaydet — `next_refresh` otomatik hesaplandı
6. Başka bir tarayıcı sekmesinde o spreadsheet'i aç (devtools açık, Network > WS)
7. Odoo'da **Settings > Technical > Scheduled Actions** > "Scheduled Data Refresh" > **Run Manually**
8. Devtools'ta WS frame'i kontrol et

**Beklenen**:
- ✅ `last_refresh` güncellendi
- ✅ `next_refresh` +1 saat ileriye kaydı
- ✅ Açık browser'da WebSocket üzerinden `refresh_data` notification geldi

---

### 8. ⬜ `spreadsheet_email_report_oca` — E-posta Raporu

**Install**:
- Uygulamalar > "Email Report" ara > **Kur**

**Ön-koşul**: Odoo'da outgoing mail server ayarlanmış olmalı.

**Senaryo**: Haftalık e-tablo raporu e-posta ile gönder.

**Test Adımları**:
1. **Spreadsheets** > **Configuration** > **Email Reports** > **New**
2. Name: "Haftalık Satış Raporu"
3. Spreadsheet: herhangi bir e-tablo
4. Recipients: Admin partner'i seç
5. Extra Emails: kendi e-postan
6. Format: XLSX
7. Interval: 1 Weeks
8. Kaydet
9. Header'daki **Send Now** butonuna tıkla
10. E-posta gelen kutusunu kontrol et
11. **Settings > Technical > Email > Emails** > son mesajı kontrol et

**Beklenen**:
- ✅ `last_sent` doldu, `send_count = 1`
- ✅ E-posta ekinde `<spreadsheet-adı>.xlsx` dosyası var
- ✅ `next_send` 1 hafta ileriye kaydırıldı

---

## Faz 5 — Paylaşım (2 modül)

### 9. ⬜ `spreadsheet_public_share_oca` — Genel Paylaşım

**Install**:
- Uygulamalar > "Public Share" ara > **Kur**

**Senaryo**: Parola korumalı bir paylaşım linki oluştur.

**Test Adımları**:
1. **Spreadsheets** > **Configuration** > **Public Share Links** > **New**
2. Name: "Müşteri Raporu"
3. Spreadsheet: Veri içeren bir e-tablo seç
4. Password: "test123"
5. Allow Download: ✓
6. Expires At: 7 gün sonra
7. Kaydet — `share_url` otomatik doldu
8. Header'daki **Show Link** butonuna tıkla, URL'yi kopyala
9. Incognito/private pencerede URL'yi aç
10. Parola prompt'u görür → "test123" gir
11. Read-only spreadsheet render olmalı
12. Download butonuna tıkla

**Beklenen**:
- ✅ Parola yanlış girilirse erişim verilmedi
- ✅ Doğru parola ile HTML render göründü (stiller, merge'ler, renkler)
- ✅ XLSX indirdi
- ✅ Admin'de `view_count=1`, `last_viewed` doldu
- ✅ Expires at geçtiyse "Invalid or Expired Link" mesajı

---

### 10. ⬜ `spreadsheet_api_oca` — REST API

**Install**:
- Uygulamalar > "Spreadsheet REST API" ara > **Kur**

**Ön-koşul**: `pip install requests`

**Senaryo**: API token oluştur, curl ile dış erişim test et, webhook tetikle.

**Test Adımları**:
1. **Spreadsheets** > **Configuration** > **API Tokens** > **New**
2. Name: "Test Integration"
3. User: Admin
4. Rate Limit: 5 (dakikada)
5. Webhook URL: https://webhook.site (bir temp URL al)
6. Kaydet — `token` otomatik doluyor
7. Form'dan token'ı kopyala (password görünür, show ile göster)
8. Terminal'de:
   ```
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:8069/api/spreadsheet/list
   ```
9. Detaylı endpoint:
   ```
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:8069/api/spreadsheet/1
   ```
10. Rate limit test: 6 kere ardarda aynı isteği gönder
11. Webhook test: Odoo'da herhangi bir spreadsheet'i aç, bir hücre değiştir, kaydet
12. 2 dakika bekle
13. webhook.site'de POST isteği görünmeli

**Beklenen**:
- ✅ İlk 5 istek 200 dönüyor, JSON ile spreadsheet listesi
- ✅ 6. istek 429 (Rate Limited) dönüyor
- ✅ webhook.site'de POST geldi (event=update)
- ✅ Token form'unda "Webhook Delivery Log" dolu

---

## Faz 6 — Muhasebe (2 modül)

### 11. ⬜ `spreadsheet_accounting_formulas_oca` — Muhasebe Formülleri

**Install**:
- Uygulamalar > "Accounting Formulas" ara > **Kur** (account modülü kurulu olmalı)

**Senaryo**: Hesap bakiyesini e-tabloda göster.

**Test Adımları**:
1. Accounting'de en azından 1 hesap olduğundan emin ol (örn. kod 600000)
2. Yeni e-tablo aç
3. A1'e: `=ODOO.BALANCE("600000")` — 0 gösterir başta
4. 1-2 saniye bekle — cell otomatik güncellenmeli
5. A2'ye: `=ODOO.CREDIT("600000", "2026-01-01", "2026-12-31")`
6. A3'e: `=ODOO.DEBIT("600000")`
7. DevTools'ta Network sekmesinde RPC isteklerini kontrol et

**Beklenen**:
- ✅ Başta 0, sonra gerçek bakiye
- ✅ `account_account/spreadsheet_get_account_balance` RPC çağrısı görünür
- ✅ Network'te her farklı hesap kodu için yeni istek (cache çalışıyor)

---

### 12. ⬜ `spreadsheet_multicompany_oca` — Çok-Şirket Konsolidasyon

**Install**:
- Uygulamalar > "Multi-Company Consolidation" ara > **Kur**

**Ön-koşul**: Birden fazla şirket kurulu olmalı, her birinde hesaplar olmalı.

**Senaryo**: 2 şirketin bilançosunu konsolide et.

**Test Adımları**:
1. **Spreadsheets** > **Consolidation** menüsüne git > **New**
2. Name: "Grup Konsolidasyon Q1"
3. Companies: 2+ şirket seç
4. Consolidation Currency: EUR (veya tercihli)
5. Elimination Accounts: varsa inter-company hesapları seç
6. Kaydet
7. Header'da **Generate Consolidated Report** butonuna tıkla

**Beklenen**:
- ✅ Yeni e-tablo açılır, adı "Consolidated Report - Grup Konsolidasyon Q1"
- ✅ Sütunlar: Account | Code | Şirket1 | Şirket2 | Eliminations | Consolidated
- ✅ Para birimi dönüşümü uygulandı
- ✅ Elimination hesaplarının konsolide sütunda değeri 0

---

## Faz 7 — Sözleşme (1 modül)

### 13. ⬜ `spreadsheet_contract_sla_oca` — Sözleşme ve SLA

**Install**:
- Uygulamalar > "Contract & SLA Tracker" ara > **Kur**

**Senaryo**: Yakında bitecek bir sözleşme oluştur, hatırlatma tetikle.

**Test Adımları**:
1. **Spreadsheets** > **Contracts & SLA** > **New**
2. Name: "Test Sözleşmesi 2026"
3. Partner: Bir müşteri
4. Contract Type: Service Agreement
5. Date Start: bugün -30 gün
6. Date End: bugün +25 gün
7. Reminder Before: 30 (yani bitişe 30 gün kaldığında hatırlat)
8. Amount: 10000
9. Responsible: kendini seç
10. SLA Metrics sekmesine geç:
    - Name: "Uptime", Target: 99.9, Actual: 98.5, Unit: %
    - Name: "Response", Target: 4, Actual: 6, Unit: hours
11. Kaydet
12. Status "Expiring Soon" olmalı (25 gün kaldı, reminder 30 gün)
13. **Settings > Technical > Scheduled Actions** > "Contract Expiry Check" > **Run Manually**
14. Inbox'u ve mail.mail kayıtlarını kontrol et
15. **Calendar** view'a geç

**Beklenen**:
- ✅ Status "Expiring Soon" olarak hesaplandı
- ✅ SLA satırlarından Uptime "Breached", Response "Breached" (target < actual)
- ✅ Cron sonrası e-posta gönderildi + activity oluştu
- ✅ Calendar'da sözleşme görünür

---

## Faz 8 — Hazır Dashboardlar (9 modül)

Bu modüllerin tümü **auto-install** özelliğine sahip — bağımlı app (crm, sale, hr, vs.) kuruluysa otomatik yüklenir.

### 14-22. ⬜ Tüm Dashboard Modülleri

**Modul Listesi**:
1. `spreadsheet_dashboard_crm_oca` — CRM Pipeline
2. `spreadsheet_dashboard_sale_oca` — Sales
3. `spreadsheet_dashboard_hr_oca` — HR Overview
4. `spreadsheet_dashboard_stock_oca` — Inventory
5. `spreadsheet_dashboard_ecommerce_oca` — E-commerce Analytics
6. `spreadsheet_customer_segmentation_oca` — Customer Segmentation
7. `spreadsheet_campaign_roi_oca` — Campaign ROI
8. `spreadsheet_stock_sales_correlation_oca` — Stock vs Sales
9. `spreadsheet_loyalty_dashboard_oca` — Loyalty Program
10. `spreadsheet_quote_conversion_oca` — Quote Conversion

**Ortak Test Adımları** (her dashboard için tekrarla):
1. İlgili bağımlı modül kurulu mu kontrol et (crm, sale, hr, stock, website_sale, mass_mailing, loyalty vs.)
2. Bağımlı app kuruluysa, ilgili dashboard modülü **otomatik kurulmuş** olmalı
3. **Dashboards** app'ini aç (spreadsheet_dashboard)
4. Solda yeni dashboard'un listede görünmesi gerek
5. Dashboard'a tıkla
6. KPI scorecard'lar ve trend chart yüklenmeli
7. Sağ üstte Period filtresini "Last 3 months" olarak kullan
8. Bir scorecard'a tıkla — drill-down pivotu açmalı

**Beklenen** (her biri için):
- ✅ 4 scorecard + 1 chart + 1 liste görünür
- ✅ Period filter değişince veriler güncellenir
- ✅ Drill-down ile kaynak model açılır

**Notlar**:
- ❗ Eğer bir dashboard boş görünürse → ilgili modelde gerçek veri yok demek (demo data yükleyebilirsiniz)
- ❗ Loyalty dashboard'unun görünmesi için `loyalty` modülü kurulu olmalı
- ❗ Campaign ROI için `mass_mailing` kurulu olmalı

---

### 23. ⬜ `spreadsheet_vendor_scorecard_oca` — Tedarikçi Karnesi

**Install**:
- Uygulamalar > "Vendor Scorecard" ara > **Kur** (purchase_stock bağımlılığı)

**Senaryo**: Otomatik scorecard hesapla ve incele.

**Test Adımları**:
1. En az 1 tedarikçiden onaylanmış purchase order olmalı
2. **Settings > Technical > Scheduled Actions** > "Compute Vendor Scorecards" > **Run Manually**
3. **Purchase** > **Reporting** > **Vendor Scorecards** menüsüne git
4. Scorecard kayıtları görünmeli
5. Bir kayda tıkla, detayları incele
6. Score'a göre renklendirme: yeşil (≥80), sarı (50-80), kırmızı (<50)
7. Dashboards > "Vendor Performance" aç

**Beklenen**:
- ✅ Her vendor için aylık scorecard satırı oluştu
- ✅ score, on_time_delivery_rate, quality_rate, avg_lead_time dolu
- ✅ Renk kodlaması doğru
- ✅ Pre-built dashboard data gösteriyor

---

## Faz 9 — İleri Düzey (Dashboard Bağımlı) (2 modül)

### 24. ⬜ `spreadsheet_record_rule_oca` — Yetki Bazlı Filtreleme

**Install**:
- Uygulamalar > "Dashboard Record Rule Filter" ara > **Kur**

**Ön-koşul**: En az bir dashboard kurulu olmalı (örn. Sales).

**Senaryo**: Satış Temsilcisi sadece kendi siparişlerini görsün.

**Test Adımları**:
1. **Spreadsheets** > **Configuration** > **Dashboard Data Filters** > **New**
2. Name: "Sadece Kendi Siparişleri"
3. Dashboard: "Sales"
4. Model: `sale.order`
5. Apply to Groups: "Sales / User"
6. Additional Domain: `[('user_id', '=', user.id)]`
7. Kaydet
8. Yeni bir Sales User oluştur (sales_team.group_sale_salesman only)
9. O kullanıcı olarak giriş yap
10. Sales dashboard'u aç
11. Veriler sadece o kullanıcının siparişlerini göstermeli
12. Admin olarak giriş yap, dashboard'u tekrar aç → tüm siparişler görünmeli

**Beklenen**:
- ✅ Sales User dashboard'da kendi verilerini görüyor
- ✅ Admin tüm verileri görüyor (kural sadece sales user'a uygulandı)
- ✅ Geçersiz domain yazılırsa save'de hata verir

---

### 25. ⬜ `spreadsheet_portal_dashboard_oca` — Portal Dashboard

**Install**:
- Uygulamalar > "Portal Dashboard" ara > **Kur**

**Ön-koşul**: En az bir dashboard kurulu, en az bir portal user olmalı.

**Senaryo**: Bayi portal'inde Satış dashboard'unu paylaş.

**Test Adımları**:
1. Contacts'ta bir partner oluştur, "Portal User" yap (Contacts > Partner > Action > Grant Portal Access)
2. **Spreadsheets** > **Configuration** > **Portal Dashboards** > **New**
3. Dashboard: "Sales" dashboard'unu seç
4. Name: otomatik doldu
5. Description: "Satış performansınız"
6. Partner Ids: yukarıda oluşturduğun portal partner'ı seç
7. Kaydet
8. Portal partner'ın email'i ile giriş yap (veya admin olarak `/web/session/logout` + portal login)
9. `/my` sayfasına git
10. "Dashboards" kartı görünmeli
11. "Dashboards" kartına tıkla → `/my/dashboards` listesi
12. Dashboard kartına tıkla
13. Read-only HTML render görünmeli

**Beklenen**:
- ✅ Portal home'da "Dashboards" kartı var
- ✅ `/my/dashboards`'ta sadece bu partner'a atanmış dashboard görünür
- ✅ Dashboard detay sayfası HTML tablosu ile render
- ✅ Atanmamış partner'lar için liste boş

---

## Son Faz — Entegre Testler

### 26. ⬜ Unified Settings Test

**Adımlar**:
1. **Settings** menüsüne git
2. Sol panelde "Spreadsheet" sekmesini ara (tüm ayarlar modülleri kuruluysa)
3. Şu blokları görmen gerek:
   - KPI Alerts (Default Cooldown, Send Email Default)
   - REST API (Rate Limit, Retry Max, Expiry Days)
   - Contracts & SLA (Default Reminder Days)
   - Email Reports (Default Format)
   - Scheduled Refresh (Default Interval Hours)
   - Public Share Links (Default Expiry, Allow Download Default)
4. Bir değer değiştir → **Save**
5. Sayfayı yenile → değer korundu

---

### 27. ⬜ Translation Test

**Adımlar**:
1. **Preferences** > kullanıcı dilini **Türkçe** yap
2. Sayfayı yenile
3. Menüleri kontrol et:
   - "Templates" → "Sablonlar"
   - "KPI Alerts" → "KPI Uyarilari"
   - "Save as Template" → "Sablon Olarak Kaydet"
4. Nederlands ve Deutsch için tekrar et

---

### 28. ⬜ Permission / User Card Test

**Adımlar**:
1. **Settings** > **Users & Companies** > **Users** > Admin'i aç
2. "Other" sekmesinde "Spreadsheet" category'sini ara
3. Dropdown: **No Access / User / Manager** seçenekleri olmalı
4. "Manager" seçildiğinde "Template Manager" checkbox'u otomatik seçili olmalı (implied_ids)
5. Yeni bir test user oluştur, sadece "User" seviyesinde
6. Giriş yap → Template düzenleyememeli
7. Manager olarak tekrar oluştur → tüm erişim

---

## İlerleme Takibi

| # | Modul | Durum | Notlar |
|:-:|:------|:-----:|:-------|
| 1 | spreadsheet_template_oca | ⬜ | |
| 2 | spreadsheet_forecast_oca | ⬜ | |
| 3 | spreadsheet_period_comparison_oca | ⬜ | |
| 4 | spreadsheet_pdf_report_oca | ⬜ | |
| 5 | spreadsheet_kpi_alert_oca | ⬜ | |
| 6 | spreadsheet_version_history_oca | ⬜ | |
| 7 | spreadsheet_scheduled_refresh_oca | ⬜ | |
| 8 | spreadsheet_email_report_oca | ⬜ | |
| 9 | spreadsheet_public_share_oca | ⬜ | |
| 10 | spreadsheet_api_oca | ⬜ | |
| 11 | spreadsheet_accounting_formulas_oca | ⬜ | |
| 12 | spreadsheet_multicompany_oca | ⬜ | |
| 13 | spreadsheet_contract_sla_oca | ⬜ | |
| 14-22 | 9x dashboard modülü | ⬜ | |
| 23 | spreadsheet_vendor_scorecard_oca | ⬜ | |
| 24 | spreadsheet_record_rule_oca | ⬜ | |
| 25 | spreadsheet_portal_dashboard_oca | ⬜ | |
| 26 | Unified Settings Test | ⬜ | |
| 27 | Translation Test | ⬜ | |
| 28 | Permission Test | ⬜ | |

---

## Ortak Hata Senaryoları

| Hata | Muhtemel Neden | Çözüm |
|------|----------------|-------|
| "Module not installable" | requests paketi eksik | `pip install requests` |
| Asset yüklenmiyor | Cache eski | Browser cache temizle, `--dev=all` ile restart |
| PDF boş çıkıyor | wkhtmltopdf yok | `apt install wkhtmltopdf` |
| Portal user AccessDenied | Portal Dashboard modülü kurulu değil | Kur |
| Webhook gelmiyor | Cron aktif değil | Scheduled Actions'tan kontrol |
| Cell value 0 dönüyor (accounting formula) | İlk yükleme, cache boş | 1-2 saniye bekle |
| "KeyError: users" | groups alanı "users" olarak isimlendirilmiş, artik "group_ids" | XML görünümünü düzelt |
