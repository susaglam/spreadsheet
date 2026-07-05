import {Component} from "@odoo/owl";
import {ControlPanel} from "@web/search/control_panel/control_panel";
import {useService} from "@web/core/utils/hooks";

const {proxy} = owl;

export class SpreadsheetName extends Component {
    setup() {
        // Prefer the explicit prop; when it is empty (the record prop no longer
        // reaches the subclassed ControlPanel in saas-19.4, see
        // spreadsheet_action.esm.js) fall back to the record exposed on the
        // sub-env. This is what makes the file name show in the breadcrumb when
        // the editor is opened directly from the kanban list.
        const envName = this.env.getSpreadsheetRecord?.()?.name;
        this.state = proxy({
            name: this.props.name || envName || "",
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
    name: String,
    isReadonly: Boolean,
    onChanged: {type: Function, optional: true},
};

export class SpreadsheetControlPanel extends ControlPanel {
    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    onBreadcrumbClicked(jsId) {
        this.actionService.restore(jsId);
    }
}
SpreadsheetControlPanel.template = "spreadsheet_oca.SpreadsheetControlPanel";
SpreadsheetControlPanel.props = {
    ...ControlPanel.props,
    record: Object,
};
SpreadsheetControlPanel.components = {
    SpreadsheetName,
};
