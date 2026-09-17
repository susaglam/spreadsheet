import {registry} from "@web/core/registry";
import {rpc} from "@web/core/network/rpc";

// Records created by tests/test_insert_flows.py
const EXISTING_SHEET = "Insert Tour Existing Sheet";
const PIVOT_TITLE = "Insert Tour Pivot";
const GRAPH_TITLE = "Insert Tour Graph";
const LIST_TITLE = "Insert Tour List";

const EDITOR = ".o_spreadsheet_oca_container";
const PANEL = `${EDITOR} .o-sidePanel`;
const COMPOSER = `${EDITOR} .o-topbar-composer .o-composer`;
const NO_ERROR =
    "body:not(:has(.o_error_dialog)):not(:has(.o_notification_bar.bg-danger))";

/**
 * Wait until the collaborative revisions holding the given commands reached
 * the server, so the Python side of the test can inspect their payload.
 *
 * @param {String} spreadsheetName
 * @param {String[]} commandTypes
 * @returns {Object} tour step
 */
function waitForSavedCommands(spreadsheetName, commandTypes) {
    return {
        content: `${commandTypes.join(", ")} saved on "${spreadsheetName}"`,
        trigger: `${NO_ERROR} ${EDITOR} .o-grid`,
        async run() {
            const call = (method, args, kwargs = {}) =>
                rpc(`/web/dataset/call_kw/spreadsheet.spreadsheet/${method}`, {
                    model: "spreadsheet.spreadsheet",
                    method,
                    args,
                    kwargs,
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

function fillImportWizard({existing = false, staticValues = false} = {}) {
    const steps = [
        {
            content: "The import wizard opened",
            trigger: ".modal .o_form_view .o_field_widget[name=mode_id]",
        },
    ];
    if (existing) {
        steps.push(
            {
                content: "Add to an existing spreadsheet",
                trigger:
                    ".modal .o_field_widget[name=mode_id] .o_selection_badge:contains(Add to spreadsheet)",
                run: "click",
            },
            {
                content: "Search the existing spreadsheet",
                trigger: ".modal .o_field_widget[name=spreadsheet_id] input",
                run: `edit ${EXISTING_SHEET}`,
            },
            {
                content: "Pick the existing spreadsheet",
                trigger: `.o-autocomplete--dropdown-item:contains(${EXISTING_SHEET})`,
                run: "click",
            },
            {
                content: "The existing spreadsheet is selected",
                trigger: `.modal .o_field_widget[name=spreadsheet_id] input:value(${EXISTING_SHEET})`,
            }
        );
    }
    if (staticValues) {
        steps.push(
            {
                content: "Insert static values instead of a dynamic formula",
                trigger: ".modal .o_field_widget[name=dynamic] input:checked",
                run: "click",
            },
            {
                content: "Dynamic is unchecked",
                trigger: ".modal .o_field_widget[name=dynamic] input:not(:checked)",
            }
        );
    }
    steps.push(
        {
            content: "Insert the data",
            trigger: ".modal button[name=insert_pivot]",
            run: "click",
        },
        {
            content: "The spreadsheet editor opened without error",
            trigger: `${NO_ERROR}:not(:has(.modal)) ${EDITOR} .o-grid`,
        }
    );
    return steps;
}

function insertedInNewSheet(sheetName) {
    return [
        {
            content: `The data went to a new sheet named "${sheetName}"`,
            trigger: `${EDITOR} .o-sheet.active .o-sheet-name:contains(${sheetName})`,
        },
        {
            content: "The first sheet of the existing spreadsheet is kept",
            trigger: `${EDITOR} .o-sheet:not(.active) .o-sheet-name:contains(Sheet1)`,
        },
    ];
}

const pivotButton = {
    content: "Add the pivot view to a spreadsheet",
    trigger: ".o_pivot_buttons button.fa-table:enabled",
    run: "click",
};
const listButton = {
    content: "Add the list view to a spreadsheet",
    trigger: ".o_list_view .o_control_panel .o_list_export_spreadsheet",
    run: "click",
};
const graphButton = {
    content: "Add the graph view to a spreadsheet",
    trigger: ".o_graph_renderer button.fa-table:enabled",
    run: "click",
};

const tours = registry.category("web_tour.tours");

tours.add("spreadsheet_oca_insert_pivot_new", {
    steps: () => [
        pivotButton,
        ...fillImportWizard(),
        {
            content: "A1 holds the dynamic pivot formula",
            trigger: `${COMPOSER}:contains(=PIVOT)`,
        },
        waitForSavedCommands(PIVOT_TITLE, ["ADD_PIVOT", "UPDATE_CELL"]),
    ],
});

tours.add("spreadsheet_oca_insert_pivot_static_existing", {
    steps: () => [
        pivotButton,
        ...fillImportWizard({existing: true, staticValues: true}),
        ...insertedInNewSheet(PIVOT_TITLE),
        waitForSavedCommands(EXISTING_SHEET, [
            "CREATE_SHEET",
            "ADD_PIVOT",
            "INSERT_PIVOT",
        ]),
    ],
});

tours.add("spreadsheet_oca_insert_list_new", {
    steps: () => [
        listButton,
        ...fillImportWizard(),
        {
            content: "A1 holds the dynamic list formula",
            trigger: `${COMPOSER}:contains(ODOO.LIST)`,
        },
        waitForSavedCommands(LIST_TITLE, ["INSERT_ODOO_LIST"]),
    ],
});

tours.add("spreadsheet_oca_insert_list_existing", {
    steps: () => [
        listButton,
        ...fillImportWizard({existing: true}),
        ...insertedInNewSheet(LIST_TITLE),
        {
            content: "A1 of the new sheet holds the dynamic list formula",
            trigger: `${COMPOSER}:contains(ODOO.LIST)`,
        },
        waitForSavedCommands(EXISTING_SHEET, ["CREATE_SHEET", "INSERT_ODOO_LIST"]),
    ],
});

tours.add("spreadsheet_oca_insert_graph_new", {
    steps: () => [
        graphButton,
        ...fillImportWizard(),
        {
            content: "The chart figure is drawn",
            trigger: `${EDITOR} .o-figure canvas`,
        },
        waitForSavedCommands(GRAPH_TITLE, ["CREATE_CHART"]),
    ],
});

tours.add("spreadsheet_oca_insert_graph_existing", {
    steps: () => [
        graphButton,
        ...fillImportWizard({existing: true}),
        ...insertedInNewSheet(GRAPH_TITLE),
        {
            content: "The chart figure is drawn",
            trigger: `${EDITOR} .o-figure canvas`,
        },
        waitForSavedCommands(EXISTING_SHEET, ["CREATE_SHEET", "CREATE_CHART"]),
    ],
});

function openDataMenuItem(itemName) {
    return [
        {
            content: "Open the Data menu",
            trigger: `${EDITOR} .o-topbar-menu[data-id=data]`,
            run: "click",
        },
        {
            content: `Open the "${itemName}" Data menu item`,
            trigger: `.o-menu-item[data-name=${itemName}]`,
            run: "click",
        },
    ];
}

function reinsertPivot(mode) {
    return [
        {
            content: "The pivot side panel is open",
            trigger: `${NO_ERROR} ${PANEL} .o_spreadsheet_oca_pivot_panel_info`,
        },
        {
            content: "Open the pivot actions",
            trigger: `${PANEL} .os-cog-wheel-menu-icon`,
            run: "click",
        },
        {
            content: `Re-insert the pivot as ${mode}`,
            trigger: `.o-menu-item[data-name=pivot_panel_reinsert_${mode}]`,
            run: "click",
        },
    ];
}

tours.add("spreadsheet_oca_reinsert_from_side_panels", {
    steps: () => [
        {
            content: "Open the spreadsheet editor from its form",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            run: "click",
        },
        // List side panel: "Insert list" at the selected cell (A1)
        ...openDataMenuItem("data_source_list_1"),
        {
            content: "Rows is prefilled for a list no cell shows yet",
            trigger: `${PANEL} input#list_rows`,
            run() {
                if (!(parseInt(this.anchor.value, 10) > 0)) {
                    throw new Error(`Rows is not prefilled: "${this.anchor.value}"`);
                }
            },
        },
        {
            content: "Insert the list at A1",
            trigger: `${PANEL} .o_spreadsheet_oca_datasource_panel button.btn-success`,
            run: "click",
        },
        {
            content: "A1 holds the dynamic list formula",
            trigger: `${NO_ERROR} ${COMPOSER}:contains(ODOO.LIST)`,
        },
        {
            content: "Empty the Rows input",
            trigger: `${PANEL} input#list_rows`,
            run: "clear",
        },
        {
            content: "Insert list without a number of rows",
            trigger: `${PANEL} .o_spreadsheet_oca_datasource_panel button.btn-success`,
            run: "click",
        },
        {
            content: "A warning asks for the number of rows, nothing is inserted",
            trigger: ".o_notification:has(.o_notification_bar.bg-warning)",
        },
        // Pivot side panel: re-insert dynamic, then static, at A1
        ...openDataMenuItem("pivot_data_sources"),
        {
            content: "Open the side panel of pivot #1",
            trigger: ".o-menu-item[data-name=item_pivot_1]",
            run: "click",
        },
        ...reinsertPivot("dynamic"),
        {
            content: "A1 holds the dynamic pivot formula",
            trigger: `${NO_ERROR} ${COMPOSER}:contains(=PIVOT)`,
        },
        ...reinsertPivot("static"),
        {
            content: "The static pivot replaced the dynamic formula",
            trigger: `${NO_ERROR} ${COMPOSER}:not(:contains(=PIVOT))`,
        },
        waitForSavedCommands("Reinsert Tour Sheet", [
            "RE_INSERT_ODOO_LIST",
            "INSERT_PIVOT",
        ]),
    ],
});

/**
 * Replace the domain of the open side panel through "Edit domain", with the
 * code editor that DomainSelectorDialog shows in debug mode.
 *
 * @param {String} panel selector of the side panel section holding the button
 * @param {String} domain
 * @returns {Object[]} tour steps
 */
function editDomain(panel, domain) {
    return [
        {
            content: "Open the domain dialog",
            trigger: `${NO_ERROR} ${panel} .btn-link:contains(Edit domain)`,
            run: "click",
        },
        {
            content: `Type the domain ${domain}`,
            trigger: ".modal .o_domain_selector_debug_container textarea",
            run: `edit ${domain}`,
        },
        {
            // The click moves the focus out of the code editor first, which
            // commits the typed domain before the dialog confirms it.
            content: "Confirm the domain",
            trigger: ".modal .modal-footer .btn-primary:enabled",
            run: "click",
        },
        {
            content: "The dialog closed without error",
            trigger: `${NO_ERROR}:not(:has(.modal)) ${EDITOR} .o-grid`,
        },
    ];
}

tours.add("spreadsheet_oca_edit_datasource_domains", {
    steps: () => [
        {
            content: "Open the spreadsheet editor from its form",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            run: "click",
        },
        // Pivot: a domain without context values is stored as a list
        ...openDataMenuItem("pivot_data_sources"),
        {
            content: "Open the side panel of pivot #1",
            trigger: ".o-menu-item[data-name=item_pivot_1]",
            run: "click",
        },
        ...editDomain(
            `${PANEL}:has(.o_spreadsheet_oca_pivot_panel_info)`,
            `[("name", "like", "Insert Tour Tag")]`
        ),
        // List: a domain using uid is stored as is, evaluated on each load
        ...openDataMenuItem("data_source_list_1"),
        ...editDomain(
            `${PANEL} .o_spreadsheet_oca_datasource_panel`,
            `[("create_uid", "=", uid)]`
        ),
        waitForSavedCommands("Domain Tour Sheet", [
            "UPDATE_PIVOT",
            "UPDATE_ODOO_LIST_DOMAIN",
        ]),
    ],
});
