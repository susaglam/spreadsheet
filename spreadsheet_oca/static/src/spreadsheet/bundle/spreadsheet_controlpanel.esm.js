import {Component, proxy} from "@odoo/owl";
import {Breadcrumbs} from "@web/search/breadcrumbs/breadcrumbs";
import {ControlPanel} from "@web/search/control_panel/control_panel";

export class SpreadsheetName extends Component {
    setup() {
        // The name comes from the record the spreadsheet action exposes on the
        // sub-env (see spreadsheet_action.esm.js): this component is rendered
        // by the breadcrumbs of SpreadsheetControlPanel, which cannot receive
        // the record as a prop. An explicit name prop still wins, for a reuse
        // outside of that action.
        const record = this.env.getSpreadsheetRecord?.();
        this.state = proxy({
            name: this.props.name || record?.name || "",
        });
    }
    _onNameChanged(ev) {
        if (this.props.isReadonly) {
            return;
        }
        if (ev.target.value) {
            this.env.saveRecord({name: ev.target.value});
        }
        this.state.name = ev.target.value;
        if (this.props.onChanged) {
            this.props.onChanged(ev);
        }
    }
}
SpreadsheetName.template = "spreadsheet_oca.SpreadsheetName";
SpreadsheetName.props = {
    name: {type: String, optional: true},
    isReadonly: Boolean,
    onChanged: {type: Function, optional: true},
};

export class SpreadsheetControlPanel extends ControlPanel {
    /**
     * Same wording (and therefore the same translations) as the core
     * breadcrumbs, whose markup spreadsheet_oca.Breadcrumbs is derived from.
     *
     * @param {Object} breadcrumb an entry of env.config.breadcrumbs
     * @returns {String}
     */
    getBreadcrumbTooltip(breadcrumb) {
        return Breadcrumbs.prototype.getBreadcrumbTooltip.call(this, breadcrumb);
    }
}
SpreadsheetControlPanel.template = "spreadsheet_oca.SpreadsheetControlPanel";
// No `record` prop: the core ControlPanel reads its props through the owl3
// field `props({display, slots})`, which exposes only those two keys, so the
// record reaches SpreadsheetName through env.getSpreadsheetRecord instead.

// The template renders the parent's Dropdown, DropdownItem and Pager: without
// them OWL throws "Cannot find the definition of component" as soon as the
// breadcrumbs collapse into a dropdown.
SpreadsheetControlPanel.components = {
    ...ControlPanel.components,
    SpreadsheetName,
};
