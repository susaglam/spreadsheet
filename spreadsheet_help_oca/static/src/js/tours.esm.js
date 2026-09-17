/** @odoo-module **/

import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";

/**
 * Interactive tours for the Spreadsheets app ("video tutorial" equivalent).
 *
 * saas-19.4 rules these tours follow (see the team field manual):
 *
 * 1. MANUAL tours are read from the database (`web_tour.tour`, see
 *    data/web_tours.xml). The rows ship without step records, so the core
 *    falls back to the steps registered here: this file is the single source
 *    of truth for the steps, the DB row holds name / url / rainbow message.
 * 2. The tour object only accepts `steps` (a top-level `url` is rejected by
 *    the registry schema in debug mode and would kill this whole file). The
 *    starting URL is passed to `startTour(name, {url})` by the launcher below.
 * 3. Every step has a string `run`: in manual mode a step without `run` is
 *    silently skipped. Steps use `tooltipPosition` (not `position`).
 * 4. The first step is ACTIONABLE (a contentless intro auto-skips) and every
 *    waiting trigger is SCOPED to the Spreadsheets app, so a paused tour never
 *    points at a lookalike button in another app. After step 1 the scopes use
 *    translation-independent markers (field names, editor container,
 *    o-spreadsheet menu ids). Step 1 uses the app menu xmlid on desktop; on
 *    small screens web.NavBar renders neither the brand nor the app sections,
 *    so the only app marker left is the breadcrumb, which shows the action
 *    name in the user's language: the label is translated when the tour
 *    starts (see appScopes).
 * 5. Selectors are split on top-level commas by the tour runner, so no comma
 *    may appear inside a `:has(...)` that itself contains parentheses, and the
 *    alternatives of one trigger must never match the same element (each
 *    match gets its own listener: one click would consume two steps).
 * 6. Tours through the editor's File / Data top bar only work on large
 *    screens: o-spreadsheet renders that bar only when !env.isSmall. The
 *    launcher explains this instead of starting them on a phone.
 */

const APP_MENU_XMLID = "spreadsheet_oca.spreadsheet_spreadsheet_menu";

/** Tours that go through the o-spreadsheet top bar (desktop only). */
const DESKTOP_ONLY_TOURS = new Set([
    "spreadsheet_save_template",
    "spreadsheet_kpi_alert",
]);

/**
 * Selector prefixes limiting a trigger to the Spreadsheets app. Called from
 * steps(), i.e. when the tour starts, so translations are loaded.
 */
function appScopes() {
    // Desktop: the navbar brand carries the app menu xmlid (any language).
    const desktop = `body:has(.o_menu_brand[data-menu-xmlid='${APP_MENU_XMLID}'])`;
    // Mobile: the breadcrumb shows spreadsheet_oca's action name, translated.
    // This msgid carries the same nl/tr/de translation as that action name.
    // Quotes, commas, parentheses or backslashes would break the :contains()
    // argument or the runner's comma split: keep the text before them (a
    // prefix still matches).
    const label =
        String(_t("Spreadsheets"))
            .split(/[,'"()\\]/)[0]
            .trim() || "Spreadsheets";
    // `:not(:has(.o_menu_brand))` keeps desktop and mobile mutually exclusive.
    const mobile = `body:not(:has(.o_menu_brand)):has(.o_breadcrumb:contains('${label}'))`;
    return [desktop, mobile];
}

/** Same selector scoped to the Spreadsheets app on desktop and mobile. */
function inApp(selector) {
    return appScopes()
        .map((scope) => `${scope} ${selector}`)
        .join(", ");
}

// Form view of spreadsheet.spreadsheet: only that form has a reader groups field.
const SHEET_FORM = ".o_form_view:has(div[name='reader_group_ids'])";
// The o-spreadsheet editor opened by spreadsheet_oca.
const EDITOR = ".o_spreadsheet_oca_container";
// "Save as Template" wizard (spreadsheet_template_oca).
const TEMPLATE_WIZARD = ".modal:has(div[name='category_id'])";
// KPI alert form (spreadsheet_kpi_alert_oca).
const KPI_FORM = ".o_form_view:has(div[name='threshold_value'])";
// KPI alert list opened from the editor's Data menu.
const KPI_LIST = ".o_list_view:has(th[data-name='alert_condition'])";

/** Kanban card link or list button that opens a spreadsheet in the editor. */
function openSheetTrigger() {
    return [
        inApp(".o_kanban_record a[name='open_spreadsheet']"),
        inApp(".o_list_renderer button[name='open_spreadsheet']"),
    ].join(", ");
}

const TOURS = {
    /**
     * Tour 1 — Quick Start: create your first spreadsheet.
     */
    spreadsheet_quick_start: {
        steps: () => [
            {
                trigger: [
                    inApp(".o_control_panel .o-kanban-button-new"),
                    inApp(".o_control_panel .o_list_button_add"),
                ].join(", "),
                content: _t(
                    "👋 Welcome! This tour shows how to create your first spreadsheet. Click New to start."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${SHEET_FORM} div[name='name'] input`,
                content: _t(
                    "✏️ Give your spreadsheet a name, for example 'Sales Report'."
                ),
                tooltipPosition: "right",
                run: "edit Sales Report",
            },
            {
                trigger: `${SHEET_FORM} .o_form_button_save`,
                content: _t("💾 Save the record with the save (cloud) icon."),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${SHEET_FORM} button[name='open_spreadsheet']`,
                content: _t(
                    "🚀 Click Edit to open the spreadsheet in the o-spreadsheet editor."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${EDITOR} .o-grid-overlay`,
                content: _t(
                    "🎉 This is the spreadsheet editor! Click a cell to type data or a formula. The File menu offers Save as Template and PDF download."
                ),
                tooltipPosition: "top",
                run: "click",
            },
        ],
    },

    /**
     * Tour 2 — Save as Template (needs spreadsheet_template_oca and the
     * template manager group; the File menu is desktop-only in o-spreadsheet).
     */
    spreadsheet_save_template: {
        steps: () => [
            {
                trigger: openSheetTrigger(),
                content: _t(
                    "📋 This tour saves a spreadsheet as a template. Open one of your spreadsheets (create one first with the Quick Start tour if the list is empty)."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${EDITOR} .o-topbar-menu[data-id='file']`,
                content: _t("📂 Open the File menu in the top bar."),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${EDITOR} .o-menu-item[data-name='save_as_template']`,
                content: _t(
                    "💾 Choose Save as Template. A dialog opens to name the template."
                ),
                tooltipPosition: "right",
                run: "click",
            },
            {
                trigger: `${TEMPLATE_WIZARD} div[name='name'] input`,
                content: _t("✏️ Give the template a clear name."),
                tooltipPosition: "bottom",
                run: "edit Monthly Sales Report Template",
            },
            {
                trigger: `${TEMPLATE_WIZARD} .modal-footer button[name='create_template']`,
                content: _t("✅ Confirm with Save as Template!"),
                tooltipPosition: "top",
                run: "click",
            },
        ],
    },

    /**
     * Tour 3 — Create a KPI Alert (needs spreadsheet_kpi_alert_oca; the Data
     * menu is desktop-only in o-spreadsheet).
     */
    spreadsheet_kpi_alert: {
        steps: () => [
            {
                trigger: openSheetTrigger(),
                content: _t(
                    "🔔 This tour adds a KPI threshold alert to a spreadsheet. Open the spreadsheet you want to watch."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${EDITOR} .o-topbar-menu[data-id='data']`,
                content: _t("📊 Open the Data menu in the top bar."),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${EDITOR} .o-menu-item[data-name='kpi_alerts']`,
                content: _t(
                    "🔔 Choose KPI Alerts to see the alerts of this spreadsheet."
                ),
                tooltipPosition: "right",
                run: "click",
            },
            {
                trigger: `${KPI_LIST} .o_list_button_add`,
                content: _t("➕ Click New to create an alert."),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${KPI_FORM} div[name='name'] input`,
                content: _t(
                    "✏️ Give the alert a meaningful name, for example 'Revenue threshold crossed'."
                ),
                tooltipPosition: "right",
                run: "edit Revenue threshold crossed",
            },
            {
                trigger: `${KPI_FORM} div[name='cell_ref'] input`,
                content: _t("📍 Enter the cell to watch, for example B5."),
                tooltipPosition: "right",
                run: "edit B5",
            },
            {
                trigger: `${KPI_FORM} div[name='threshold_value'] input`,
                content: _t(
                    "🎯 Enter the threshold value, for example 40000. The operator (>, <, =...) is set just above."
                ),
                tooltipPosition: "right",
                run: "edit 40000",
            },
            {
                trigger: `${KPI_FORM} .o_form_button_save`,
                content: _t(
                    "💾 Save! A scheduled action checks the threshold every 15 minutes."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
            {
                trigger: `${KPI_FORM} button[name='action_test_alert']`,
                content: _t(
                    "🧪 Click Test Alert to send a test notification right away and see it in your Discuss inbox."
                ),
                tooltipPosition: "bottom",
                run: "click",
            },
        ],
    },
};

for (const [name, tour] of Object.entries(TOURS)) {
    try {
        registry.category("web_tour.tours").add(name, tour);
    } catch (error) {
        // A future registry schema change must not break the rest of the file
        // (the client action below) nor the backend bundle.
        console.warn(`spreadsheet_help_oca: tour ${name} not registered`, error);
    }
}

/**
 * Client action handler: triggered when Tutorial > Start Tour is clicked.
 * Starts the requested web_tour in manual mode. `url` comes from the tour's
 * database row: saas-19.4 startTour() only redirects through options.url, so
 * without it the tour would start on the Help page and wait forever.
 */
registry.category("actions").add("spreadsheet_help_start_tour", async (env, action) => {
    const notification = env.services.notification;
    const tourName = action.params?.tour_name;
    const url = action.params?.url || undefined;
    if (!tourName) {
        notification.add(
            _t(
                "The tour could not start because no tour name was provided. Set the Interactive Tour Name on the tutorial and try again."
            ),
            {type: "danger"}
        );
        return;
    }
    if (DESKTOP_ONLY_TOURS.has(tourName) && env.isSmall) {
        notification.add(
            _t(
                "This tour guides you through the spreadsheet editor's top menu, which is only shown on larger screens, so it cannot run on this device. Open Odoo on a computer or a tablet in landscape mode and start the tour again."
            ),
            {type: "warning"}
        );
        return;
    }
    const tourService = env.services.tour_service;
    if (!tourService?.startTour) {
        notification.add(
            _t(
                "Interactive tours are not available in this session, so the tour cannot start. Reload the page and try again; if it persists, ask an administrator to check that the Tours (web_tour) module is installed."
            ),
            {type: "warning"}
        );
        return;
    }
    try {
        await tourService.startTour(tourName, {mode: "manual", url});
        if (!url) {
            notification.add(
                _t("Tour started: %(name)s. Follow the highlighted steps.", {
                    name: tourName,
                }),
                {type: "info"}
            );
        }
    } catch (error) {
        notification.add(
            _t(
                "The tour %(name)s could not start: %(error)s. Reload the page and try again.",
                {name: tourName, error: error?.message || String(error)}
            ),
            {type: "danger"}
        );
    }
});
