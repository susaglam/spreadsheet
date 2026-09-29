import {registry} from "@web/core/registry";

// Records created by tests/test_global_filter_tour.py
const PARTNER = "Filter Tour Partner";
const EDITOR = ".o_spreadsheet_oca_container";
const PANEL = `${EDITOR} .o-sidePanel`;
const SAVE = `${PANEL} .o_spreadsheet_oca_filter_save`;
const LABEL = `${PANEL} input.o_global_filter_label`;
// Data sources of the tour spreadsheet: list "1" and pivot "1" on res.partner
const LIST_MATCHING = `${PANEL} .o_spreadsheet_oca_filter_field_matching[data-id=list_1]`;
const PIVOT_MATCHING = `${PANEL} .o_spreadsheet_oca_filter_field_matching[data-id=pivot_1]`;

function filterRow(type) {
    return `${PANEL} .o_spreadsheet_oca_filter[data-filter-type=${type}]`;
}

function matchField(dataSourceSelector, fieldName) {
    return [
        {
            content: `Open the field selector of ${dataSourceSelector}`,
            trigger: `${dataSourceSelector} .o_model_field_selector`,
            run: "click",
        },
        {
            content: `Match the filter with the field "${fieldName}"`,
            trigger: `.o_model_field_selector_popover li[data-name=${fieldName}] button.o_model_field_selector_popover_item_name`,
            run: "click",
        },
        {
            content: "The matched field is displayed",
            trigger: `body:not(:has(.o_model_field_selector_popover)) ${dataSourceSelector} .o_model_field_selector_chain_part`,
        },
    ];
}

/**
 * Press Enter in a text filter input to turn the typed text into a tag.
 *
 * The core AutoComplete of the input handles the typed text in a setTimeout
 * and, until that ran, prevents the Enter keydown (onInputKeydown), so the
 * browser sends no "change" event and nothing is committed. A person never
 * presses Enter within the millisecond after the last keystroke; the tour does,
 * since it types the whole value at once. Wait like the core unit tests of this
 * input do (hoot contains().edit() awaits the next frame) before pressing it.
 *
 * @param {String} content
 * @param {String} inputSelector
 * @returns {Object} tour step
 */
function confirmTypedText(content, inputSelector) {
    return {
        content,
        trigger: inputSelector,
        async run(helpers) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            await helpers.press("Enter");
        },
    };
}

function saveFilter(type) {
    return [
        {
            content: `Save the ${type} filter`,
            trigger: SAVE,
            run: "click",
        },
        {
            content: `Back on the Filters panel with the ${type} filter`,
            trigger: `${filterRow(type)} .spreadsheet_oca_filter_value_edit`,
        },
    ];
}

registry.category("web_tour.tours").add("spreadsheet_oca_global_filters", {
    steps: () => [
        {
            content: "Open the spreadsheet editor from its form",
            trigger: `body:not(:has(${EDITOR})) .o_form_view button[name=open_spreadsheet]`,
            run: "click",
        },
        {
            content: "Open the File menu of the editor",
            trigger: `${EDITOR} .o-spreadsheet .o-topbar-menu[data-id=file]`,
            run: "click",
        },
        {
            content: "Open the global filters panel",
            trigger: ".o-menu-item[data-name=filters]",
            run: "click",
        },

        // Text filter with a default value, matched with the list
        {
            content: "Add a text filter",
            trigger: `${PANEL} .o_spreadsheet_oca_add_text_filter`,
            run: "click",
        },
        {
            content: "The edit panel lists the list data source",
            trigger: LIST_MATCHING,
        },
        {
            content: "Label the text filter",
            trigger: LABEL,
            run: "edit Tour Text",
        },
        {
            content: "Type a default value",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_text input`,
            run: "edit Azure",
        },
        confirmTypedText(
            "Confirm the default value",
            `${PANEL} .o_spreadsheet_oca_filter_default_text input`
        ),
        {
            content: "The default value is a tag",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_text .o_tag:contains(Azure)`,
        },
        ...matchField(LIST_MATCHING, "name"),
        ...saveFilter("text"),
        {
            content: "The default value is applied to the text filter",
            trigger: `${filterRow("text")} .o-global-filter-text-value .o_tag:contains(Azure)`,
        },

        // Relation filter with a default record, matched with the pivot
        {
            content: "Add a relation filter",
            trigger: `${PANEL} .o_spreadsheet_oca_add_relation_filter`,
            run: "click",
        },
        {
            content: "Label the relation filter",
            trigger: LABEL,
            run: "edit Tour Partner",
        },
        {
            content: "Search the related model",
            trigger: `${PANEL} .o_model_selector input`,
            run: "edit res.partner",
        },
        {
            content: "Select the partner model",
            trigger: ".o-autocomplete--dropdown-item.o_model_selector_res_partner",
            run: "click",
        },
        {
            content: "Search the default record",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_relation .o_multi_record_selector input`,
            run: `edit ${PARTNER}`,
        },
        {
            content: "Select the default record",
            trigger: `.o-autocomplete--dropdown-item:contains(${PARTNER})`,
            run: "click",
        },
        {
            content: "The default record is a tag",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_relation .o_tag:contains(${PARTNER})`,
        },
        ...matchField(PIVOT_MATCHING, "id"),
        ...saveFilter("relation"),
        {
            content: "The default record is applied to the relation filter",
            trigger: `${filterRow("relation")} .o_tag:contains(${PARTNER})`,
        },

        // Date filter with a relative default period
        {
            content: "Add a date filter",
            trigger: `${PANEL} .o_spreadsheet_oca_add_date_filter`,
            run: "click",
        },
        {
            content: "Label the date filter",
            trigger: LABEL,
            run: "edit Tour Date",
        },
        {
            content: "Open the default period dropdown",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_date input.o-date-filter-input`,
            run: "click",
        },
        {
            content: "Default to the last 30 days",
            trigger: ".o-dropdown-item[data-id=last_30_days]",
            run: "click",
        },
        {
            content: "The default period is selected",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_date input.o-date-filter-input:value(Last 30 Days)`,
        },
        ...saveFilter("date"),
        {
            content: "The default period is applied to the date filter",
            trigger: `${filterRow("date")} input.o-date-filter-input:value(Last 30 Days)`,
        },

        // Reopen the saved filters
        {
            content: "Edit the text filter again",
            trigger: `${filterRow("text")} .spreadsheet_oca_filter_value_edit`,
            run: "click",
        },
        {
            content: "The saved default value is shown",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_text .o_tag:contains(Azure)`,
        },
        {
            content: "The saved list matching is shown",
            trigger: `${LIST_MATCHING} .o_model_field_selector_chain_part`,
        },
        {
            content: "Rename the text filter",
            trigger: `${LABEL}:value(Tour Text)`,
            run: "edit Tour Text Renamed",
        },
        ...saveFilter("text"),
        {
            content: "The text filter is renamed",
            trigger: `${filterRow("text")} .spreadsheet_oca_filter_label:contains(Tour Text Renamed)`,
        },
        {
            content: "Edit the relation filter again",
            trigger: `${filterRow("relation")} .spreadsheet_oca_filter_value_edit`,
            run: "click",
        },
        {
            content: "The saved default record is shown",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_relation .o_tag:contains(${PARTNER})`,
        },
        {
            content: "The saved pivot matching is shown",
            trigger: `${PIVOT_MATCHING} .o_model_field_selector_chain_part`,
        },
        {
            content: "Leave the relation filter unchanged",
            trigger: `${PANEL} .o-sidePanelButtons .btn-warning`,
            run: "click",
        },
        {
            content: "Edit the date filter again",
            trigger: `${filterRow("date")} .spreadsheet_oca_filter_value_edit`,
            run: "click",
        },
        {
            content: "The saved default period is shown",
            trigger: `${PANEL} .o_spreadsheet_oca_filter_default_date input.o-date-filter-input:value(Last 30 Days)`,
        },
        {
            content: "Leave the date filter unchanged",
            trigger: `${PANEL} .o-sidePanelButtons .btn-warning`,
            run: "click",
        },

        // Change the filter values from the Filters panel
        {
            content: "Add a value to the text filter",
            trigger: `${filterRow("text")} .o-global-filter-text-value input`,
            run: "edit Deco",
        },
        confirmTypedText(
            "Confirm the text value",
            `${filterRow("text")} .o-global-filter-text-value input`
        ),
        {
            content: "The text filter has both values",
            trigger: `${filterRow("text")} .o_tag:contains(Deco)`,
        },
        {
            content: "Hover the default record tag to reveal its delete button",
            trigger: `${filterRow("relation")} .o_tag:contains(${PARTNER})`,
            run: "hover",
        },
        {
            // Partners have an avatar, so saas-19.4 renders an AvatarTag whose
            // delete link is "opacity-0 opacity-100-hover": only a real CSS
            // :hover shows it, which synthetic pointer events cannot trigger.
            content: "Clear the relation filter value",
            trigger: `${filterRow("relation")} .o_tag.o_avatar:contains(${PARTNER}) .o_delete:not(:visible)`,
            run: "click",
        },
        {
            content: "The relation filter is empty",
            trigger: `${filterRow("relation")} .o_multi_record_selector:not(:has(.o_tag))`,
        },
        {
            content: "Open the date filter periods",
            trigger: `${filterRow("date")} input.o-date-filter-input`,
            run: "click",
        },
        {
            content: "Filter on today",
            trigger: ".o-dropdown-item.o-date-filter-dropdown[data-id=today]",
            run: "click",
        },
        {
            content: "The date filter shows the new period and no error dialog opened",
            trigger: `body:not(:has(.o_error_dialog)) ${filterRow("date")} input.o-date-filter-input:value(Today)`,
        },
    ],
});
