import {registry} from "@web/core/registry";

// Record name created by tests/test_ui_tours.py
const SHEET = "Breadcrumb Tour Sheet";
const EDITOR = ".o_spreadsheet_oca_container";
const CONTROL_PANEL = `${EDITOR} .o_spreadsheet_oca_compact_cp`;

function openEditorFromForm({mobile}) {
    const steps = [];
    if (mobile) {
        // Small screens move every stat button of the form into a dropdown.
        steps.push(
            {
                content: "Open the form's stat button dropdown",
                trigger: `body:not(:has(${EDITOR})) .o_form_view .o-form-buttonbox .o_button_more`,
                run: "click",
            },
            {
                content: "Open the spreadsheet editor from its form",
                trigger: ".o-dropdown-item button[name=open_spreadsheet]",
                run: "click",
            }
        );
    } else {
        steps.push({
            content: "Open the spreadsheet editor from its form",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            run: "click",
        });
    }
    steps.push(
        {
            content: "The control panel shows the editable spreadsheet name",
            trigger: `${CONTROL_PANEL} .o_last_breadcrumb_item .o_spreadsheet_oca_name:value(${SHEET})`,
        },
        {
            content: "The editor itself rendered below the control panel",
            trigger: `${EDITOR} .o-spreadsheet`,
        }
    );
    return steps;
}

function jumpToSpreadsheetsWithCollapsedBreadcrumbs() {
    return [
        {
            content: "Open the collapsed breadcrumbs",
            trigger: `${CONTROL_PANEL} .o_breadcrumb .dropdown-toggle`,
            run: "click",
        },
        {
            content: "Jump back to the first breadcrumb",
            trigger: ".o-dropdown-item:contains(Spreadsheets)",
            run: "click",
        },
        {
            content: "The Spreadsheets kanban is shown again",
            trigger: `body:not(:has(${EDITOR})) .o_kanban_view`,
        },
    ];
}

registry.category("web_tour.tours").add("spreadsheet_oca_breadcrumbs_desktop", {
    steps: () => [
        ...openEditorFromForm({mobile: false}),
        {
            content: "The previous breadcrumb (the form) is a link",
            trigger: `${CONTROL_PANEL} .o_breadcrumb li.o_back_button:contains(${SHEET})`,
        },
        ...jumpToSpreadsheetsWithCollapsedBreadcrumbs(),
    ],
});

registry.category("web_tour.tours").add("spreadsheet_oca_breadcrumbs_mobile", {
    steps: () => [
        ...openEditorFromForm({mobile: true}),
        {
            content: "Go back to the form with the back arrow",
            trigger: `${CONTROL_PANEL} .o_breadcrumb button.o_back_button`,
            run: "click",
        },
        ...openEditorFromForm({mobile: true}),
        ...jumpToSpreadsheetsWithCollapsedBreadcrumbs(),
    ],
});

registry.category("web_tour.tours").add("spreadsheet_oca_list_add_to_spreadsheet", {
    steps: () => [
        {
            content: "Add the list view to a spreadsheet",
            trigger: ".o_list_view .o_control_panel .o_list_export_spreadsheet",
            run: "click",
        },
        {
            content: "The import wizard opened",
            trigger: ".modal .o_form_view",
        },
    ],
});

registry.category("web_tour.tours").add("spreadsheet_oca_x2many_list_ignores_add", {
    steps: () => [
        {
            content: "The form view shows an x2many list",
            trigger:
                ".o_form_view .o_field_widget[name=field_id] .o_list_renderer .o_data_row",
        },
        {
            content:
                "The x2many list offers no 'Add to spreadsheet' action: only list view controllers do",
            trigger:
                ".o_form_view .o_field_widget[name=field_id]:not(:has(.o_list_export_spreadsheet))",
        },
        {
            content: "No import wizard was opened by the form",
            trigger: "body:not(:has(.modal)) .o_form_view",
        },
    ],
});

registry.category("web_tour.tours").add("spreadsheet_oca_graph_add_enabled", {
    steps: () => [
        {
            content: "With data, 'Add to spreadsheet' is enabled",
            trigger: ".o_graph_renderer button.fa-table:enabled",
            run: "click",
        },
        {
            content: "The import wizard opened",
            trigger: ".modal .o_form_view",
        },
    ],
});

registry.category("web_tour.tours").add("spreadsheet_oca_graph_add_disabled", {
    steps: () => [
        {
            content: "Without data, 'Add to spreadsheet' is disabled",
            trigger: ".o_graph_renderer button.fa-table:disabled",
        },
    ],
});
