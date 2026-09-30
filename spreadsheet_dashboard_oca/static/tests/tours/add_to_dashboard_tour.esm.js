import {registry} from "@web/core/registry";

// Record names created by tests/test_add_to_dashboard_tour.py
const SECTION = "Dashboard Tour Section";
const EDITOR = ".o_spreadsheet_oca_container";
const WIZARD = ".modal .o_form_view:has(div[name='dashboard_group_id'])";

registry.category("web_tour.tours").add("spreadsheet_dashboard_oca_add_to_dashboard", {
    steps: () => [
        {
            content: "Open the spreadsheet editor from its form",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            run: "click",
        },
        {
            content: "Open the File menu of the editor",
            trigger: `${EDITOR} .o-topbar-menu[data-id='file']`,
            run: "click",
        },
        {
            content: "The patched renderer adds 'Add to dashboard' to the File menu",
            trigger: `${EDITOR} .o-menu-item[data-name='add_to_dashboard']`,
            run: "click",
        },
        {
            content: "The wizard is prefilled with the spreadsheet name",
            trigger: `${WIZARD} div[name='name'] input:value(Dashboard Tour Sheet)`,
        },
        {
            content: "Pick the dashboard section",
            trigger: `${WIZARD} div[name='dashboard_group_id'] input`,
            run: `edit ${SECTION}`,
        },
        {
            content: "Select the section in the autocomplete",
            trigger: `.o-autocomplete--dropdown-item:contains(${SECTION})`,
            run: "click",
        },
        {
            content: "Create the dashboard",
            trigger: ".modal button[name='create_dashboard']",
            run: "click",
        },
        {
            content: "The new dashboard opens in the Dashboards app",
            trigger: ".o_spreadsheet_dashboard_action",
        },
    ],
});
