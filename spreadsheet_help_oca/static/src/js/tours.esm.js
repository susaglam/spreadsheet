/** @odoo-module **/

import {registry} from "@web/core/registry";

/**
 * Interactive tour: Quick Start — Creating first spreadsheet.
 *
 * Odoo web_tour framework: each step highlights a DOM element with
 * a floating tooltip. User clicks through real UI while seeing
 * contextual help. This is our "video tutorial" equivalent.
 */
registry.category("web_tour.tours").add("spreadsheet_quick_start", {
    url: "/odoo/spreadsheets",
    steps: () => [
        {
            trigger: ".o_breadcrumb",
            content:
                "👋 Hos geldin! Bu tur Odoo Spreadsheets'i size tanitacak. " +
                "Burasi tum spreadsheet'lerinizin anasayfasi.",
            position: "bottom",
            run: () => {},
        },
        {
            trigger: ".o-kanban-button-new, .o_list_button_add",
            content:
                "📊 ADIM 1: Yeni bir spreadsheet olusturmak icin 'New' " +
                "butonuna basin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o_field_widget[name='name'] input",
            content: "✏️ ADIM 2: Spreadsheet'e bir ad verin (orn: 'Satis Raporu').",
            position: "right",
            run: "edit Spreadsheet Tour Test",
        },
        {
            trigger: ".o_form_button_save, .o_form_status_indicator_buttons button",
            content: "💾 ADIM 3: Kaydetmek icin disket ikonuna basin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button[name='open_spreadsheet']",
            content:
                "🚀 ADIM 4: Spreadsheet'i acmak icin 'Edit' butonuna basin. " +
                "o-spreadsheet editoru acilacak.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o-spreadsheet",
            content:
                "🎉 Iste spreadsheet editoru! Hucrelere tiklayip veri girebilir, " +
                "formuller yazabilirsiniz. File menusunden 'Save as Template' ve " +
                "'Download PDF' secenekleri kullanabilirsiniz.",
            position: "bottom",
            run: () => {},
        },
    ],
});

/**
 * Interactive tour: Save as Template
 */
registry.category("web_tour.tours").add("spreadsheet_save_template", {
    url: "/odoo/spreadsheets",
    steps: () => [
        {
            trigger: ".o_kanban_record, .o_data_row",
            content:
                "📋 ADIM 1: Template olarak kaydedilecek bir spreadsheet'i secin. " +
                "DEMO - Satis Ozeti Q1 2026 acin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button[name='open_spreadsheet']",
            content: "🚀 Spreadsheet'i editor'de acin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o-topbar-menu[data-id='file'], .o-menu-item:contains(File)",
            content:
                "📂 ADIM 2: Ust cubuktaki 'File' menusune basin. " +
                "Templates ile ilgili secenekleri goreceksiniz.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o-menu-item:contains(Save as Template)",
            content:
                "💾 ADIM 3: 'Save as Template' secenegini tiklayin. " +
                "Dialog acilacak.",
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
            content: "✅ 'Save as Template' butonuyla onaylayin!",
            position: "top",
            run: "click",
        },
    ],
});

/**
 * Interactive tour: Create a KPI Alert
 */
registry.category("web_tour.tours").add("spreadsheet_kpi_alert", {
    url: "/odoo/spreadsheets",
    steps: () => [
        {
            trigger: ".o_kanban_record, .o_data_row",
            content: "📋 ADIM 1: KPI alert kuracaginiz bir spreadsheet'i acin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "button.oe_stat_button .o_stat_text:contains(KPI Alerts)",
            content:
                "🔔 ADIM 2: Form view'da 'KPI Alerts' smart button'a basin. " +
                "Mevcut alert'leri ve ekleme ekranini gorursunuz.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: ".o_list_button_add, .o-kanban-button-new",
            content: "➕ ADIM 3: Yeni alert olusturmak icin 'New' basin.",
            position: "bottom",
            run: "click",
        },
        {
            trigger: "input[name='name']",
            content:
                "✏️ ADIM 4: Alert'inize anlamli bir ad verin " +
                "(orn: 'Ciro 40K uzerine cikarsa bildir').",
            position: "right",
            run: "edit Ciro Esigi Asildi",
        },
        {
            trigger: "input[name='cell_ref']",
            content: "📍 ADIM 5: Izlenecek hucre referansini girin (orn: 'B5').",
            position: "right",
            run: "edit B5",
        },
        {
            trigger: "[name='operator']",
            content: "⚖️ ADIM 6: Karsilastirma operatorunu secin (>, <, =, ...).",
            position: "right",
        },
        {
            trigger: "input[name='threshold_value']",
            content: "🎯 ADIM 7: Esik degerini girin (orn: 40000).",
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
            trigger: "button[name='action_test_alert']",
            content:
                "🧪 BONUS: 'Test Alert' butonuyla hemen test bildirimi gonderin. " +
                "Discuss inbox'inizda mesaji goreceksiniz!",
            position: "bottom",
            run: () => {},
        },
    ],
});

/**
 * Client action handler: triggered when Tutorial > Start Tour clicked.
 * Starts the requested web_tour.
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
            // Fallback: call the tour registry directly
            const odooTour = odoo.__WOWL_DEBUG__?.root?.env?.services?.tour_service;
            if (odooTour) {
                odooTour.startTour(tourName, {mode: "manual"});
            }
        }
        env.services.notification.add(
            `Tour baslatildi: ${tourName}. Ekranda beliren yonergeleri takip edin.`,
            {type: "info"}
        );
    } catch (e) {
        env.services.notification.add(`Tour baslatilamadi: ${e.message}`, {
            type: "danger",
        });
    }
});
