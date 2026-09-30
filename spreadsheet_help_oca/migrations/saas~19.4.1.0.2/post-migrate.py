# Copyright 2026 Codesnap
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Bring databases installed before saas~19.4.1.0.2 in line with the data files.

All touched records live in ``noupdate="1"`` files, so ``-u`` alone never
reaches them:

* guide spreadsheets: share them read-only with ``spreadsheet_oca.group_user``
  (they were readable by managers only), rename the ASCII-Turkish titles and
  reload their workbook (``spreadsheet_binary_data``) from the English
  ``data/files/guide_*.json``;
* web tours: ``custom=True`` so the onboarding queue never auto-plays them, and
  English rainbow-man messages;
* tutorials: English source texts, and module / tour names stripped of
  surrounding blanks (the availability search compares exact names).

Translatable JSONB values are only rewritten while their English key still
holds the text this module shipped; any language key still holding that old
text is dropped so the ``.po`` import that runs right after post-migrate fills
it with the proper nl/tr/de translation. Values edited by users are kept.
A guide workbook is only reloaded while its parsed JSON still equals a Turkish
file this module shipped and no collaborative revision sits on top of it; a
guide somebody edited is kept.
Every step is isolated in a savepoint and only logs on failure: this script
must never abort an upgrade.
"""

import hashlib
import json
import logging

from odoo.api import SUPERUSER_ID, Environment
from odoo.fields import Command
from odoo.tools import SQL, file_open
from odoo.tools.binary import BinaryBytes

_logger = logging.getLogger(__name__)

MODULE = "spreadsheet_help_oca"

# xmlid -> {field: (shipped text, new English text)}. The shipped text is the
# ASCII-Turkish original, or a tuple of every text this module ever shipped.
TUTORIAL_TEXTS = {
    "tutorial_quick_start": {
        "name": (
            "🚀 Quick Start — Ilk Spreadsheet'inizi olusturun",
            "🚀 Quick Start — Create your first spreadsheet",
        ),
        "description": (
            "Odoo Spreadsheets uygulamasinin tum "
            "temelleri. Yeni bir spreadsheet "
            "olusturma, veri girme, kaydetme, "
            "template olarak kaydetme ve PDF olarak "
            "indirme. Interactive tour ile hemen "
            "baslayin!",
            "All the basics of the Spreadsheets app: "
            "create a new spreadsheet, enter data, "
            "save it, save it as a template and "
            "download it as PDF. Start right away "
            "with the interactive tour!",
        ),
    },
    "tutorial_template_save": {
        "name": (
            "📋 Spreadsheet'i Template olarak kaydedin",
            "📋 Save a spreadsheet as a template",
        ),
        "description": (
            (
                "Sik kullandiginiz bir rapor sablonunu "
                "kaydedip tek tikla yeniden olusturun. "
                "'File > Save as Template' akisini "
                "gosteren interactive tour.",
                "Save a report layout you use often "
                "and recreate it in one click. "
                "Interactive tour showing the 'File > "
                "Save as Template' flow.",
            ),
            "Save a report layout you use often "
            "and recreate it in one click. "
            "Interactive tour of the 'File > Save "
            "as Template' flow; it needs the "
            "Template Manager access right and a "
            "desktop-size screen.",
        ),
    },
    "tutorial_kpi_alert": {
        "name": ("🔔 KPI Alert kurun", "🔔 Set up a KPI alert"),
        "description": (
            (
                "Bir hucre belirli bir esigi astiginda "
                "bildirim alin. Smart button uzerinden "
                "alert olusturma, operator secimi, "
                "bildirim alicilari ayarlama. Discuss "
                "inbox ve chatter entegrasyonunu gosteren "
                "tour.",
                "Get notified when a cell crosses a "
                "threshold. Create an alert from the "
                "spreadsheet's 'Data > KPI Alerts' menu, "
                "choose the operator and the notification "
                "recipients. Tour showing the Discuss "
                "inbox and chatter integration.",
            ),
            "Get notified when a cell crosses a "
            "threshold. Create an alert from the "
            "spreadsheet's 'Data > KPI Alerts' menu, "
            "choose the operator and the notification "
            "recipients. The tour needs a desktop-size "
            "screen and ends by sending a test "
            "notification to your Discuss inbox.",
        ),
    },
    "tutorial_public_share": {
        "name": (
            "🔗 Spreadsheet'i public link ile paylasin",
            "🔗 Share a spreadsheet with a public link",
        ),
        "description": (
            "Musterilere veya dis ekibe "
            "spreadsheet'i read-only olarak "
            "paylasin. Parola korumasi, suresi "
            "dolma, indirme izni ayarlari.",
            "Share a spreadsheet read-only with "
            "customers or external teams. Password "
            "protection, expiry date and download "
            "permission settings.",
        ),
    },
    "tutorial_forecast": {
        "name": ("📈 Tahminleme fonksiyonlari", "📈 Forecasting functions"),
        "description": (
            "ODOO.FORECAST, ODOO.TREND ve "
            "ODOO.MOVING_AVG ile gecmis verilerden "
            "gelecek tahminleri. Lineer regresyon ve "
            "hareketli ortalama ornekleri.",
            "Forecast future values from historical "
            "data with ODOO.FORECAST, ODOO.TREND and "
            "ODOO.MOVING_AVG. Linear regression and "
            "moving average examples.",
        ),
    },
    "tutorial_period_comparison": {
        "name": ("📊 Donem karsilastirma", "📊 Period comparison"),
        "description": (
            "Bu ay vs gecen ay, YoY "
            "(year-over-year), GROWTH_ARROW "
            "ile gorsel yuzde degisim. "
            "Dashboard'larda vazgecilmez "
            "fonksiyonlar.",
            "This month vs last month, YoY "
            "(year-over-year) and a visual "
            "percentage change with "
            "GROWTH_ARROW. Essential functions "
            "for dashboards.",
        ),
    },
    "tutorial_contract": {
        "name": ("📝 Sozlesme ve SLA takibi", "📝 Contract and SLA tracking"),
        "description": (
            "Yillik sozlesmeleri takip edin, SLA "
            "metrikleri (uptime, response time) "
            "kaydedin, yaklasan bitis tarihleri icin "
            "otomatik email ve activity olusturun.",
            "Track yearly contracts, record SLA metrics "
            "(uptime, response time) and create "
            "automatic emails and activities for "
            "upcoming end dates.",
        ),
    },
    "tutorial_version_history": {
        "name": (
            "📸 Versiyon yedekleme ve geri alma",
            "📸 Version backups and rollback",
        ),
        "description": (
            "Spreadsheet'in periyodik "
            "snapshot'lari. 'New Snapshot' "
            "butonu, versiyonlar arasi gorsel "
            "cell-level diff, rollback.",
            "Periodic snapshots of a "
            "spreadsheet: the 'New Snapshot' "
            "button, a visual cell-level diff "
            "between versions and rollback.",
        ),
    },
    "tutorial_api": {
        "name": ("🔑 REST API ile entegrasyon", "🔑 Integrate with the REST API"),
        "description": (
            "Spreadsheet verisine dis sistemlerden (Power "
            "BI, Google Sheets, webhook'lar) erisim. Bearer "
            "token, rate limit, webhook delivery log.",
            "Access spreadsheet data from external systems "
            "(Power BI, Google Sheets, webhooks). Bearer "
            "token, rate limit, webhook delivery log.",
        ),
    },
    "tutorial_portal": {
        "name": (
            "👥 Portal uzerinden bayilere dashboard",
            "👥 Dealer dashboards through the portal",
        ),
        "description": (
            "Portal kullanicilarinin (bayi/distributor) "
            "kendi verilerine ait read-only dashboard "
            "gorebilmesi. Record rule filter ile her "
            "bayiye kendi siparislerini gosterme.",
            "Let portal users (dealers/distributors) see "
            "a read-only dashboard of their own data. A "
            "record rule filter shows each dealer only "
            "their own orders.",
        ),
    },
    "tutorial_consolidation": {
        "name": ("🏢 Multi-company konsolidasyon", "🏢 Multi-company consolidation"),
        "description": (
            "Birden cok sirketin bilancolarini tek "
            "bir konsolide rapora birlestirin. "
            "Currency conversion, inter-company "
            "elimination.",
            "Combine the balance sheets of several "
            "companies into one consolidated "
            "report. Currency conversion, "
            "inter-company elimination.",
        ),
    },
    "tutorial_email_report": {
        "name": ("📧 Zamanli email raporlari", "📧 Scheduled email reports"),
        "description": (
            "Haftalik/aylik otomatik XLSX "
            "raporlarini ekibinize email ile "
            "gonderin. Mail template, cron tabanli "
            "delivery, send-now butonu.",
            "Email weekly or monthly reports to "
            "your team automatically, attached as "
            "spreadsheet data (JSON) that opens in "
            "the Spreadsheets app. Mail template, "
            "scheduled (cron) delivery and a Send "
            "Now button.",
        ),
    },
    "tutorial_dashboard_sale": {
        "name": ("📈 Satis analiz dashboard'u", "📈 Sales analysis dashboard"),
        "description": (
            "Satis ekibi performansini tek "
            "bakista gorun: Ciro, Siparis, "
            "Satilan Adet, Ortalama Siparis "
            "Degeri (onceki donemle "
            "karsilastirmali), aylik ciro trendi "
            "ve son siparisler. Satis temsilcisi "
            "ve urun kategorisi filtreleri. "
            "Dashboards > Sales altinda otomatik "
            "cikar.",
            "See sales team performance at a "
            "glance: Revenue, Orders, Units Sold, "
            "Average Order Value (compared with "
            "the previous period), the monthly "
            "revenue trend and the latest orders. "
            "Salesperson and product category "
            "filters. Appears automatically under "
            "Dashboards > Sales.",
        ),
    },
    "tutorial_dashboard_crm": {
        "name": ("📊 CRM pipeline dashboard'u", "📊 CRM pipeline dashboard"),
        "description": (
            "Acik firsatlar, beklenen ve prorate "
            "ciro, kazanilan anlasmalar; satis "
            "temsilcisi ve satis ekibi "
            "filtreleriyle. Satis yoneticisinin "
            "ceyreklik pipeline'i izlemesi icin. "
            "Dashboards > Sales.",
            "Open opportunities, expected and "
            "prorated revenue and won deals, with "
            "salesperson and sales team filters. "
            "Lets the sales manager follow the "
            "quarterly pipeline. Dashboards > "
            "Sales.",
        ),
    },
    "tutorial_dashboard_stock": {
        "name": ("📦 Stok / envanter dashboard'u", "📦 Stock / inventory dashboard"),
        "description": (
            "Stok hareketleri: tamamlanan "
            "transferler, hareket eden adet, "
            "ortalama tedarik suresi, aylik "
            "hareket trendi ve son transferler; "
            "depo ve urun kategorisi "
            "filtreleriyle. Dashboards > "
            "Logistics.",
            "Stock moves: completed transfers, "
            "quantity moved, average lead time, "
            "the monthly movement trend and the "
            "latest transfers, with warehouse "
            "and product category filters. "
            "Dashboards > Logistics.",
        ),
    },
    "tutorial_dashboard_ecommerce": {
        "name": ("🛒 E-ticaret dashboard'u", "🛒 eCommerce dashboard"),
        "description": (
            "Web magazasi (website) satis "
            "KPI'lari: ciro, siparis sayisi, "
            "ortalama sepet, musteri; onceki "
            "donemle karsilastirma ve gunluk "
            "ciro trendi. NOT: yalnizca "
            "website siparislerini gosterir, "
            "bayi/toptan siparisleri haric.",
            "Web shop (website) sales KPIs: "
            "revenue, number of orders, "
            "average basket and customers, "
            "compared with the previous "
            "period, plus the daily revenue "
            "trend. NOTE: only website "
            "orders are shown; dealer and "
            "wholesale orders are "
            "excluded.",
        ),
    },
    "tutorial_dashboard_hr": {
        "name": ("👤 Insan Kaynaklari dashboard'u", "👤 Human Resources dashboard"),
        "description": (
            "Toplam calisan, yeni ise alim, "
            "departman ve pozisyon dagilimi, "
            "calisan rehberi; "
            "donem/departman/sirket filtreleriyle. "
            "Yalnizca Odoo IK modulu kullaniliyorsa "
            "anlamli. Dashboards > HR.",
            "Total employees, new hires, "
            "distribution by department and job "
            "position and an employee directory, "
            "with period, department and company "
            "filters. Only meaningful when the Odoo "
            "Employees app is used. Dashboards > "
            "HR.",
        ),
    },
    "tutorial_quote_conversion": {
        "name": (
            "🎯 Teklif → siparis donusum dashboard'u",
            "🎯 Quotation → order conversion dashboard",
        ),
        "description": (
            "Kac teklifin siparise dondugunu ve "
            "donusum yuzdesini gorun. Satis "
            "hunisini ve teklif basari oranini "
            "izlemek icin bayi-satis odakli bir "
            "gosterge.",
            "See how many quotations turned "
            "into orders and the conversion "
            "percentage. A dealer-sales "
            "indicator to follow the sales "
            "funnel and the quotation success "
            "rate.",
        ),
    },
    "tutorial_vendor_scorecard": {
        "name": ("🏭 Tedarikci performans karnesi", "🏭 Vendor performance scorecard"),
        "description": (
            "Tedarikcileri teslimat, kalite ve "
            "fiyat metrikleriyle puanlayin ve "
            "karsilastirin. Toptanci/bayi "
            "tedarik zincirinde hangi "
            "tedarikcinin iyi performans "
            "gosterdigini gormek icin.",
            "Score and compare vendors on "
            "delivery, quality and price "
            "metrics, to see which vendors "
            "perform well in a wholesale or "
            "dealer supply chain.",
        ),
    },
    "tutorial_stock_sales_correlation": {
        "name": ("🔗 Stok - satis korelasyonu", "🔗 Stock - sales correlation"),
        "description": (
            "Stok seviyesi ile satis "
            "hizini yan yana koyarak "
            "hangi urunlerde stok "
            "fazlasi veya eksigi "
            "oldugunu gorun — yeniden "
            "siparis (reorder) kararlari "
            "icin.",
            "Put stock levels next to "
            "sales velocity to see which "
            "products are overstocked or "
            "understocked — for reorder "
            "decisions.",
        ),
    },
    "tutorial_customer_segmentation": {
        "name": ("🧩 Musteri segmentasyonu", "🧩 Customer segmentation"),
        "description": (
            "Son donemde kazanilan musteri "
            "sayilari ve onceki donemle "
            "karsilastirma, en iyi "
            "musteriler listesi. NOT: "
            "VIP/Yeni/Risk altinda "
            "tile'lari su an ayni sayiyi "
            "gosteriyor — gercek RFM/CLV "
            "segmentasyonu henuz "
            "gelistirme bekliyor.",
            "Customer overview: total "
            "customers, companies and "
            "individual buyers, new "
            "customers compared with the "
            "previous period, a monthly "
            "new-customer trend and a top "
            "customers list, with a period "
            "filter. NOTE: a real RFM/CLV "
            "segmentation is not available "
            "yet.",
        ),
    },
    "tutorial_campaign_roi": {
        "name": ("📣 E-posta kampanya performansi", "📣 Email campaign performance"),
        "description": (
            "Tamamlanan e-posta kampanyalarinin "
            "gonderilen/iletilen/acilan/tiklanan "
            "sayilari ve aylik iletim trendi. NOT: "
            "isim 'ROI' olsa da su an gercek "
            "ciro/kupon atifi yok — sadece e-posta "
            "etkilesimini olcer.",
            "Sent, delivered, opened and clicked "
            "counts of completed email campaigns "
            "and the monthly delivery trend. NOTE: "
            "despite the 'ROI' name there is no "
            "real revenue or coupon attribution yet "
            "— it only measures email engagement.",
        ),
    },
    "tutorial_loyalty_dashboard": {
        "name": ("🎁 Sadakat programi dashboard'u", "🎁 Loyalty program dashboard"),
        "description": (
            "Sadakat programi analizi: puan, "
            "kupon ve uye metrikleri. Yalnizca "
            "Odoo Loyalty modulu aktif "
            "kullaniliyorsa anlamli.",
            "Loyalty program analysis: points, "
            "coupon and member metrics. Only "
            "meaningful when the Odoo Loyalty "
            "app is actively used.",
        ),
    },
    "tutorial_pdf_report": {
        "name": ("📄 Profesyonel PDF export", "📄 Professional PDF export"),
        "description": (
            "Bir spreadsheet'i sirket logolu, "
            "profesyonel bir PDF olarak disa aktarin "
            "— musteri veya yonetim sunumlari icin.",
            "Export a spreadsheet as a professional "
            "PDF with your company logo — for "
            "customer or management presentations.",
        ),
    },
    "tutorial_record_rule": {
        "name": (
            "🔒 Dashboard'a kullanici bazli kayit kurallari",
            "🔒 Per-user record rules for dashboards",
        ),
        "description": (
            "Dashboard verisine kullanici bazli "
            "kayit kurallari (record rule) uygulayin "
            "— her kullanici yalnizca kendi verisini "
            "gorsun. Ozellikle bayi izolasyonu (her "
            "bayi kendi siparislerini) icin.",
            "Apply per-user record rules to "
            "dashboard data so that every user only "
            "sees their own data. Especially useful "
            "for dealer isolation (each dealer sees "
            "only their own orders).",
        ),
    },
    "tutorial_scheduled_refresh": {
        "name": ("🔄 Zamanli veri yenileme", "🔄 Scheduled data refresh"),
        "description": (
            "Spreadsheet revizyonunu periyodik "
            "olarak artirarak dashboard "
            "verilerini otomatik tazeleyin "
            "(cron ile) — acilista her zaman "
            "guncel veri.",
            "Refresh dashboard data "
            "automatically by periodically "
            "bumping the spreadsheet revision "
            "(with a scheduled action), so the "
            "data is always up to date when "
            "opened.",
        ),
    },
}

# xmlid -> (old tags, new tags) — plain Char, not translatable
TUTORIAL_TAGS = {"tutorial_template_save": ("template,sablon", "template,reuse")}

# xmlid -> (old name, new name) — spreadsheet name is not translatable
GUIDE_NAMES = {
    "guide_forecast": (
        "📈 Rehber: Tahminleme Fonksiyonlari",
        "📈 Guide: Forecasting Functions",
    ),
    "guide_period": ("📊 Rehber: Donem Karsilastirma", "📊 Guide: Period Comparison"),
    "guide_core": ("🧰 Rehber: Odoo Core Formulleri", "🧰 Guide: Odoo Core Formulas"),
    "guide_features": (
        "✨ Rehber: Ozellikler ve Menuler",
        "✨ Guide: Features and Menus",
    ),
}

# xmlid -> fingerprints (see _guide_fingerprint) of every ASCII-Turkish workbook
# this module shipped in data/files/<xmlid>.json before saas~19.4.1.0.2: the
# git revisions 94141f1 and c05e28f (guide_core changed between the two).
SHIPPED_GUIDE_FINGERPRINTS = {
    "guide_forecast": {
        "812a20f69238d05eb8e9ddf45ca22bb07a8cf9aadf83a0eff66afa5abba63c94",
    },
    "guide_period": {
        "c40cbbf91507bc2aa3ae28e1454a9939a4364d977108f4636245c3df2881a293",
    },
    "guide_core": {
        "9a93547abac895319a37ff9f44e7e35573f3611ccf28b228c969441d8bbb1951",
        "8d04754bdf679ed1cd192b5632e1bfa3cd1f49fc2626857f575af1c2250bd99c",
    },
    "guide_features": {
        "25d5313e191025f59ac6b6acc63671f2b030131e349b0c9ee4b15cdbe30ae10a",
    },
}

# xmlid -> (marker only present in the shipped Turkish message, new English HTML)
TOUR_MESSAGES = {
    "tour_quick_start": (
        "Tebrikler!",
        "<p><strong>🎉 Congratulations!</strong> You created your "
        "first spreadsheet.</p><p>You can now enter data in the "
        "cells, write formulas and turn it into a template with File "
        "&gt; Save as Template.</p>",
    ),
    "tour_save_template": (
        "Harika!",
        "<p><strong>📋 Great!</strong> You can now reuse this "
        "spreadsheet as a template whenever you want.</p>",
    ),
    "tour_kpi_alert": (
        "izlenecek!",
        "<p><strong>🔔 Your KPI is now being watched!</strong></p><p>A "
        "scheduled action checks the thresholds every 15 minutes. When "
        "a threshold is crossed, a notification arrives in your "
        "Discuss inbox.</p>",
    ),
}


def _res_id(cr, xmlid, model):
    cr.execute(
        "SELECT res_id FROM ir_model_data"
        " WHERE module = %s AND name = %s AND model = %s",
        (MODULE, xmlid, model),
    )
    row = cr.fetchone()
    return row and row[0]


def _rewrite_translated(cr, table, column, res_id, is_shipped, new_en):
    """Replace the English source when it is still the shipped text."""
    cr.execute(
        SQL(
            "SELECT %s FROM %s WHERE id = %s",
            SQL.identifier(column),
            SQL.identifier(table),
            res_id,
        )
    )
    row = cr.fetchone()
    value = row and row[0]
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or not is_shipped(value.get("en_US")):
        return False
    new_value = {
        lang: text
        for lang, text in value.items()
        if lang != "en_US" and not is_shipped(text)
    }
    new_value["en_US"] = new_en
    cr.execute(
        SQL(
            "UPDATE %s SET %s = %s::jsonb WHERE id = %s",
            SQL.identifier(table),
            SQL.identifier(column),
            json.dumps(new_value),
            res_id,
        )
    )
    return True


def _run_step(cr, label, func):
    try:
        with cr.savepoint():
            func()
    except Exception:
        _logger.warning(
            "%s migration step %r failed; skipped", MODULE, label, exc_info=True
        )


def _share_and_rename_guides(env):
    group = env.ref("spreadsheet_oca.group_user", raise_if_not_found=False)
    for xmlid, (old_name, new_name) in GUIDE_NAMES.items():
        guide = env.ref(f"{MODULE}.{xmlid}", raise_if_not_found=False)
        if not guide:
            continue
        if group and group not in guide.reader_group_ids:
            guide.reader_group_ids = [Command.link(group.id)]
        if (guide.name or "").strip() == old_name:
            guide.name = new_name


def _guide_fingerprint(content):
    """SHA-256 of a workbook's parsed JSON, or None when it is not JSON.

    Parsing first makes the comparison independent of line endings and
    indentation (a checkout with CRLF line endings stores other bytes).
    """
    try:
        data = json.loads(bytes(content or b"").decode("utf-8"))
    except (TypeError, ValueError):  # UnicodeDecodeError is a ValueError
        return None
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reload_guide_contents(env):
    Revision = env["spreadsheet.oca.revision"]
    for xmlid, shipped in SHIPPED_GUIDE_FINGERPRINTS.items():
        guide = env.ref(f"{MODULE}.{xmlid}", raise_if_not_found=False)
        if not guide or guide._name != "spreadsheet.spreadsheet":
            continue
        if _guide_fingerprint(guide.spreadsheet_binary_data) not in shipped:
            continue  # already English, or replaced by somebody
        if Revision.search_count(
            [("model", "=", guide._name), ("res_id", "=", guide.id)], limit=1
        ):
            # Edited in the spreadsheet editor: the revisions are replayed on
            # top of the stored workbook and would not fit a new one.
            _logger.info(
                "%s: guide %s has collaborative edits; its workbook is kept",
                MODULE,
                xmlid,
            )
            continue
        with file_open(f"{MODULE}/data/files/{xmlid}.json", "rb") as file:
            guide.spreadsheet_binary_data = BinaryBytes(file.read())


def _fix_tours(env):
    cr = env.cr
    for xmlid, (marker, new_html) in TOUR_MESSAGES.items():
        tour = env.ref(f"{MODULE}.{xmlid}", raise_if_not_found=False)
        if not tour:
            continue
        if not tour.custom:
            tour.custom = True
        tour.flush_recordset()
        _rewrite_translated(
            cr,
            "web_tour_tour",
            "rainbow_man_message",
            tour.id,
            lambda text, marker=marker: bool(text) and marker in text,
            new_html,
        )
    env["web_tour.tour"].invalidate_model(["rainbow_man_message"])


def _fix_tutorials(env):
    cr = env.cr
    for xmlid, fields_map in TUTORIAL_TEXTS.items():
        res_id = _res_id(cr, xmlid, "spreadsheet.tutorial")
        if not res_id:
            continue
        for column, (old, new) in fields_map.items():
            shipped = {old} if isinstance(old, str) else set(old)
            _rewrite_translated(
                cr,
                "spreadsheet_tutorial",
                column,
                res_id,
                lambda text, shipped=shipped: (text or "").strip() in shipped,
                new,
            )
    for xmlid, (old, new) in TUTORIAL_TAGS.items():
        res_id = _res_id(cr, xmlid, "spreadsheet.tutorial")
        if res_id:
            cr.execute(
                "UPDATE spreadsheet_tutorial SET tags = %s WHERE id = %s AND tags = %s",
                (new, res_id, old),
            )
    # Blank / padded technical names: the create/write overrides only clean
    # new values, so rows typed before them are cleaned here.
    for column in ("module_name", "tour_name"):
        cr.execute(
            SQL(
                "UPDATE spreadsheet_tutorial SET %s = NULLIF(btrim(%s), '')"
                " WHERE %s IS NOT NULL AND %s <> btrim(%s)",
                SQL.identifier(column),
                SQL.identifier(column),
                SQL.identifier(column),
                SQL.identifier(column),
                SQL.identifier(column),
            )
        )
    env["spreadsheet.tutorial"].invalidate_model(
        ["name", "description", "tags", "module_name", "tour_name"]
    )


def migrate(cr, version):
    if not version:
        return
    env = Environment(cr, SUPERUSER_ID, {})
    _run_step(cr, "guide spreadsheets", lambda: _share_and_rename_guides(env))
    _run_step(cr, "guide contents", lambda: _reload_guide_contents(env))
    _run_step(cr, "web tours", lambda: _fix_tours(env))
    _run_step(cr, "tutorial texts", lambda: _fix_tutorials(env))
