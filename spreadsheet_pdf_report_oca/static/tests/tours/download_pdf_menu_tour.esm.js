import {registry} from "@web/core/registry";

const EDITOR = ".o_spreadsheet_oca_container";

registry.category("web_tour.tours").add("spreadsheet_pdf_report_oca_menu", {
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
            content: "The patched renderer adds 'Download PDF' to the File menu",
            trigger: `${EDITOR} .o-menu-item[data-name='download_pdf']:not(.disabled)`,
        },
    ],
});
