import {loadBundle} from "@web/core/assets";
import {patch} from "@web/core/utils/patch";
import {registry} from "@web/core/registry";
import {rpc} from "@web/core/network/rpc";

// Records created by tests/test_chart_panel_tour.py
const GRAPH_TITLE = "Chart Panel Tour Graph";
const MENU_NAME = "Spreadsheets Tags";
const TAG_MODEL = "spreadsheet.spreadsheet.tag";

const EDITOR = ".o_spreadsheet_oca_container";
const PANEL = `${EDITOR} .o-sidePanel`;
const MENU_LINK = `${PANEL} .o_spreadsheet_oca_chart_odoo_link`;
const DATA_SOURCE = `${PANEL} .o_spreadsheet_oca_chart_odoo_datasource`;
const TYPE_SELECTOR = `${PANEL} .o-chart .o-type-selector`;
const TYPE_POPOVER = ".o-chart-select-popover";
const NO_ERROR =
    "body:not(:has(.o_error_dialog)):not(:has(.o_notification_bar.bg-danger))";

/** Chart types the "odoo" chart data source does not support (saas-19.4). */
const NOT_FOR_ODOO_DATA = ["scorecard", "gauge", "calendar", "bubble"];

/**
 * @param {String} spreadsheetName
 * @param {String[]} commandTypes
 * @returns {Object} tour step waiting until the collaborative revisions holding
 *   the given commands reached the server
 */
function waitForSavedCommands(spreadsheetName, commandTypes) {
    return {
        content: `${commandTypes.join(", ")} saved on "${spreadsheetName}"`,
        trigger: `${NO_ERROR} ${EDITOR} .o-grid`,
        async run() {
            const call = (method, args) =>
                rpc(`/web/dataset/call_kw/spreadsheet.spreadsheet/${method}`, {
                    model: "spreadsheet.spreadsheet",
                    method,
                    args,
                    kwargs: {},
                });
            let missing = commandTypes;
            for (let attempt = 0; attempt < 40 && missing.length; attempt++) {
                const [sheet] = await call("search_read", [
                    [["name", "=", spreadsheetName]],
                    ["id"],
                ]);
                if (sheet) {
                    const data = await call("get_spreadsheet_data", [[sheet.id]]);
                    const saved = new Set(
                        data.revisions.flatMap((revision) =>
                            (revision.commands || []).map((command) => command.type)
                        )
                    );
                    missing = commandTypes.filter((type) => !saved.has(type));
                }
                if (missing.length) {
                    await new Promise((resolve) => setTimeout(resolve, 200));
                }
            }
            if (missing.length) {
                throw new Error(
                    `Commands never saved on "${spreadsheetName}": ${missing.join(", ")}`
                );
            }
        },
    };
}

/** @returns {String[]} chart subtypes offered by the open type picker */
function offeredChartTypes() {
    return [...document.querySelectorAll(`${TYPE_POPOVER} .o-chart-type-item`)].map(
        (item) => item.dataset.id
    );
}

const openEditorFromForm = {
    content: "Open the spreadsheet editor from its form",
    trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
    run: "click",
};

function openChartPanel() {
    return [
        {
            content: "The chart figure is drawn",
            trigger: `${NO_ERROR} ${EDITOR} .o-figure canvas`,
        },
        {
            content: "Double-click the chart to edit it",
            trigger: `${EDITOR} .o-figure .o-chart-container`,
            run: "dblclick",
        },
    ];
}

const toggleTypePicker = {
    content: "Toggle the chart type picker",
    trigger: TYPE_SELECTOR,
    run: "click",
};

const tours = registry.category("web_tour.tours");

tours.add("spreadsheet_oca_chart_panel_odoo_chart", {
    steps: () => [
        {
            content: "Add the graph view to a spreadsheet",
            trigger: ".o_graph_renderer button.fa-table:enabled",
            run: "click",
        },
        {
            content: "Insert it in a new spreadsheet",
            trigger: ".modal button[name=insert_pivot]",
            run: "click",
        },
        ...openChartPanel(),
        {
            content: "The chart panel shows the Odoo menu link section",
            trigger: `${NO_ERROR} ${MENU_LINK} input`,
        },
        {
            content: "The Odoo data source section shows the model with its label",
            trigger: `${DATA_SOURCE} .o_spreadsheet_oca_chart_model:contains(${TAG_MODEL}):contains(Spreadsheet Tag)`,
        },
        {
            content: "The Odoo data source section shows the measure",
            trigger: `${DATA_SOURCE} .o_spreadsheet_oca_chart_measure:contains(Count)`,
        },
        {
            content: "The Odoo data source section shows the group by field label",
            trigger: `${DATA_SOURCE} .o_spreadsheet_oca_chart_group_by:contains(Name)`,
        },
        {
            content: "The Odoo data source section shows the domain",
            trigger: `${NO_ERROR} ${DATA_SOURCE} .o_spreadsheet_oca_chart_domain .o_domain_selector`,
        },
        toggleTypePicker,
        {
            content: "Only the chart types of the Odoo data source are offered",
            trigger: `${TYPE_POPOVER} .o-chart-type-item[data-id=column]`,
            run() {
                const offered = offeredChartTypes();
                const unsupported = NOT_FOR_ODOO_DATA.filter((type) =>
                    offered.includes(type)
                );
                if (unsupported.length) {
                    throw new Error(
                        `Chart types the Odoo data source cannot draw are offered: ${unsupported.join(", ")}`
                    );
                }
                const missing = ["column", "line", "pie"].filter(
                    (type) => !offered.includes(type)
                );
                if (missing.length) {
                    throw new Error(`Chart types missing: ${missing.join(", ")}`);
                }
            },
        },
        toggleTypePicker,
        {
            content: "The type picker is closed",
            trigger: `body:not(:has(${TYPE_POPOVER})) ${TYPE_SELECTOR}`,
        },
        {
            content: "Search a menu to link the chart to",
            trigger: `${MENU_LINK} input`,
            run: `edit ${MENU_NAME}`,
        },
        {
            content: "Pick the menu",
            trigger: `.o-autocomplete--dropdown-item:contains(${MENU_NAME})`,
            run: "click",
        },
        {
            content: "The chart link shows the menu",
            trigger: `${NO_ERROR} ${MENU_LINK} input:value(${MENU_NAME})`,
        },
        waitForSavedCommands(GRAPH_TITLE, ["UPDATE_ODOO_LINK_TO_CHART"]),
    ],
});

tours.add("spreadsheet_oca_chart_panel_link_persists", {
    steps: () => [
        openEditorFromForm,
        ...openChartPanel(),
        {
            content: "The saved menu link is shown again",
            trigger: `${NO_ERROR} ${MENU_LINK} input:value(${MENU_NAME})`,
        },
        // With the panel still open, a new chart gets selected: the panel must
        // follow it, type picker included.
        {
            content: "Open the Insert menu",
            trigger: `${EDITOR} .o-topbar-menu[data-id=insert]`,
            run: "click",
        },
        {
            content: "Insert a chart of the (empty) selected cells",
            trigger: ".o-menu-item[data-name=insert_chart]",
            run: "click",
        },
        {
            content: "The panel shows the new chart, which has no menu link",
            trigger: `${NO_ERROR} ${MENU_LINK} input:not(:value(${MENU_NAME}))`,
        },
        {
            content:
                "The chart of cell ranges shows its ranges, not the Odoo data source",
            trigger: `${PANEL}:not(:has(.o_spreadsheet_oca_chart_odoo_datasource)) .o-data-series`,
        },
        toggleTypePicker,
        {
            content: "A chart of cell ranges offers every chart type",
            trigger: `${TYPE_POPOVER} .o-chart-type-item[data-id=scorecard]`,
            run() {
                const missing = NOT_FOR_ODOO_DATA.filter(
                    (type) => !offeredChartTypes().includes(type)
                );
                if (missing.length) {
                    throw new Error(
                        `The type picker kept the types of the previous chart: ${missing.join(", ")} missing`
                    );
                }
            },
        },
    ],
});

/**
 * Patch the SpreadsheetRenderer of the lazy loaded spreadsheet bundle, as an
 * add-on module would.
 *
 * @param {Object} extension patch of SpreadsheetRenderer.prototype
 */
async function patchSpreadsheetRenderer(extension) {
    await loadBundle("spreadsheet.o_spreadsheet");
    const {SpreadsheetRenderer} = odoo.loader.modules.get(
        "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm"
    );
    patch(SpreadsheetRenderer.prototype, extension);
}

const PROBE = "spreadsheet_oca_tour_probe";

tours.add("spreadsheet_oca_model_custom_hook", {
    steps: () => [
        {
            content: "An add-on hands an extra entry to the spreadsheet plugins",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            async run() {
                await patchSpreadsheetRenderer({
                    getExtraModelCustom() {
                        return {...super.getExtraModelCustom(), probe: PROBE};
                    },
                    setup() {
                        super.setup();
                        window.spreadsheetOcaTourModelCustom =
                            this.spreadsheet_model.config.custom;
                    },
                });
            },
        },
        openEditorFromForm,
        {
            content: "The Model config has the extra entry and the core ones",
            trigger: `${NO_ERROR} ${EDITOR} .o-grid`,
            run() {
                const custom = window.spreadsheetOcaTourModelCustom || {};
                const missing = ["env", "orm", "odooDataProvider"].filter(
                    (key) => !custom[key]
                );
                if (custom.probe !== PROBE || missing.length) {
                    throw new Error(
                        `Unexpected Model custom config: probe=${custom.probe}, missing: ${missing.join(", ")}`
                    );
                }
            },
        },
    ],
});

tours.add("spreadsheet_oca_model_custom_hook_failure", {
    steps: () => [
        {
            content: "An add-on's getExtraModelCustom() is broken",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            async run() {
                await patchSpreadsheetRenderer({
                    getExtraModelCustom() {
                        throw new Error("Broken tour add-on");
                    },
                });
            },
        },
        openEditorFromForm,
        {
            content: "A warning names the failure",
            trigger:
                ".o_notification:has(.o_notification_bar.bg-warning):contains(Broken tour add-on)",
        },
        {
            content: "The spreadsheet still opened",
            trigger: `${NO_ERROR} ${EDITOR} .o-grid`,
        },
    ],
});
