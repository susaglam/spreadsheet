/** @odoo-module **/

import {registry} from "@web/core/registry";

/**
 * Interactive tours for the Spreadsheets app ("video tutorial" equivalent).
 *
 * Odoo web_tour framework: each step highlights a DOM element with a floating
 * pointer/tooltip. In `mode: "manual"` the tour waits for the USER to perform
 * each step's `run` action (click / edit) before advancing.
 *
 * TWO design rules learned the hard way (they fix the two reported bugs):
 *
 * 1. NO contentless intro steps. In manual mode a step whose trigger is
 *    ALREADY on screen and has no user-action `run` auto-satisfies and
 *    advances instantly — the user never sees it ("first step skipped").
 *    => The very first step must be ACTIONABLE (run: "click"/"edit") and
 *       carry the welcome text itself.
 *
 * 2. SCOPE every waiting trigger to the Spreadsheets app. A generic selector
 *    like `.o-kanban-button-new` exists in every Odoo app, so while the tour
 *    is waiting the pointer will pop up in whatever module the user opens
 *    ("tour leaks into unrelated modules"). Guarding the trigger with
 *    `:has(.o_breadcrumb:contains('Spreadsheets'))` binds it to this app.
 *    (Core Odoo tours use the same `body:has(...) .o-kanban-button-new`
 *    pattern — hoot-dom `queryAll` supports `:has()` and `:contains()`.)
 */

// DB-stable app URL: `/odoo/spreadsheets` is NOT a registered route (the app
// menu defines no custom path), so it silently fell through to the home
// launcher where the first trigger could never match -> the tour appeared to
// do nothing / skip. `/odoo/action-<xmlid>` always resolves to the action.
const SPREADSHEETS_URL =
    "/odoo/action-spreadsheet_oca.spreadsheet_spreadsheet_act_window";

// Scope helper: only matches inside the Spreadsheets app (breadcrumb guard).
const IN_APP = ".o_control_panel:has(.o_breadcrumb:contains('Spreadsheets'))";

/**
 * Tour 1 — Quick Start: create your first spreadsheet.
 */
registry.category("web_tour.tours").add("spreadsheet_quick_start", {
    url: SPREADSHEETS_URL,
    steps: () => [
        {
            // Actionable + scoped first step carries the welcome (rule 1 & 2).
            trigger: `${IN_APP} .o-kanban-button-new, ${IN_APP} .o_list_button_add`,
            content:
                "👋 Hoş geldin! Bu tur ilk spreadsheet'inizi oluşturmayı gösterir. " +
                "Başlamak için 'Nieuw' (New) butonuna basın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='name'] input",
            content: "✏️ ADIM 2: Spreadsheet'e bir ad verin (örn: 'Satış Raporu').",
            position: "right",
            run: "edit Spreadsheet Tour Test",
        },
        {
            trigger: ".o_form_button_save, .o_form_status_indicator_buttons button",
            content: "💾 ADIM 3: Kaydetmek için disket ikonuna basın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button[name='open_spreadsheet']",
            content:
                "🚀 ADIM 4: Spreadsheet'i açmak için 'Edit' butonuna basın. " +
                "o-spreadsheet editörü açılacak.",
            position: "bottom",
            run: "click",
        },
        {
            // Terminal step: matches once the editor is open, then the tour
            // ends. Kept short because it cannot wait for user input.
            trigger: ".o-spreadsheet",
            content:
                "🎉 İşte spreadsheet editörü! Hücrelere tıklayıp veri girebilir, " +
                "formüller yazabilirsiniz. 'File' menüsünden 'Save as Template' ve " +
                "'Download PDF' seçeneklerini kullanabilirsiniz.",
            position: "bottom",
        },
    ],
});

/**
 * Tour 2 — Save as Template.
 */
registry.category("web_tour.tours").add("spreadsheet_save_template", {
    url: SPREADSHEETS_URL,
    steps: () => [
        {
            trigger: `${IN_APP} ~ * .o_kanban_record, .o_content:has(${IN_APP}) .o_kanban_record, .o_kanban_renderer .o_kanban_record`,
            content:
                "📋 Bu tur bir spreadsheet'i template olarak kaydetmeyi gösterir. " +
                "ADIM 1: Kaydedeceğiniz bir spreadsheet'i açın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button[name='open_spreadsheet']",
            content: "🚀 Spreadsheet'i editörde açın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o-topbar-menu[data-id='file'], .o-menu-item:contains(File)",
            content:
                "📂 ADIM 2: Üst çubuktaki 'File' menüsüne basın. " +
                "Template ile ilgili seçenekleri göreceksiniz.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o-menu-item:contains(Save as Template)",
            content: "💾 ADIM 3: 'Save as Template' seçeneğini tıklayın. Dialog açılacak.",
            position: "right",
            run: "click",
        },
        {
            trigger: "input[name='name']",
            content: "✏️ Template'e bir ad verin.",
            position: "bottom",
            run: "edit Aylik Satis Raporu Sablonum",
        },
        {
            trigger: ".modal-footer button.btn-primary",
            content: "✅ 'Save as Template' butonuyla onaylayın!",
            position: "top",
            run: "click",
        },
    ],
});

/**
 * Tour 3 — Create a KPI Alert.
 */
registry.category("web_tour.tours").add("spreadsheet_kpi_alert", {
    url: SPREADSHEETS_URL,
    steps: () => [
        {
            trigger: `.o_content:has(${IN_APP}) .o_kanban_record, .o_kanban_renderer .o_kanban_record`,
            content:
                "🔔 Bu tur bir spreadsheet'e KPI eşik uyarısı eklemeyi gösterir. " +
                "ADIM 1: KPI alert kuracağınız bir spreadsheet'i açın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button.oe_stat_button .o_stat_text:contains(KPI Alerts)",
            content:
                "🔔 ADIM 2: Form view'da 'KPI Alerts' smart button'a basın. " +
                "Mevcut alert'leri ve ekleme ekranını görürsünüz.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o_list_button_add, .o-kanban-button-new",
            content: "➕ ADIM 3: Yeni alert oluşturmak için 'New' basın.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "input[name='name']",
            content:
                "✏️ ADIM 4: Alert'inize anlamlı bir ad verin " +
                "(örn: 'Ciro 40K üzerine çıkarsa bildir').",
            position: "right",
            run: "edit Ciro Esigi Asildi",
        },
        {
            trigger: "input[name='cell_ref']",
            content: "📍 ADIM 5: İzlenecek hücre referansını girin (örn: 'B5').",
            position: "right",
            run: "edit B5",
        },
        {
            trigger: "[name='operator']",
            content: "⚖️ ADIM 6: Karşılaştırma operatörünü seçin (>, <, =, ...).",
            position: "right",
            run: "click",
        },
        {
            trigger: "input[name='threshold_value']",
            content: "🎯 ADIM 7: Eşik değerini girin (örn: 40000).",
            position: "right",
            run: "edit 40000",
        },
        {
            trigger: ".o_form_button_save, .o_form_status_indicator_buttons button",
            content: "💾 ADIM 8: Kaydedin! Cron her 15 dakikada bir kontrol edecek.",
            position: "bottom",
            run: "click",
        },
        {
            // Terminal step — flashes then the tour ends (cannot wait).
            trigger: "button[name='action_test_alert']",
            content:
                "🧪 BONUS: 'Test Alert' butonuyla hemen test bildirimi gönderin. " +
                "Discuss inbox'inizda mesajı göreceksiniz!",
            position: "bottom",
        },
    ],
});

/**
 * Client action handler: triggered when Tutorial > Start Tour is clicked.
 * Starts the requested web_tour in manual mode. The core auto-enables tours
 * for the current user on the first manual start, so no extra setup needed.
 */
registry.category("actions").add("spreadsheet_help_start_tour", async (env, action) => {
    const tourName = action.params?.tour_name;
    if (!tourName) {
        env.services.notification.add("Tour name not provided", {type: "danger"});
        return;
    }
    try {
        const tourService = env.services.tour_service;
        if (tourService && tourService.startTour) {
            tourService.startTour(tourName, {mode: "manual"});
        } else {
            // Fallback: reach the service via the debug root.
            const odooTour = odoo.__WOWL_DEBUG__?.root?.env?.services?.tour_service;
            if (odooTour) {
                odooTour.startTour(tourName, {mode: "manual"});
            }
        }
        env.services.notification.add(
            `Tour başlatıldı: ${tourName}. Ekranda beliren yönergeleri takip edin.`,
            {type: "info"}
        );
    } catch (e) {
        env.services.notification.add(`Tour başlatılamadı: ${e.message}`, {
            type: "danger",
        });
    }
});
