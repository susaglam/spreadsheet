import {HandleField} from "@web/views/fields/handle/handle_field";
import {ListController} from "@web/views/list/list_controller";
import {evaluateBooleanExpr} from "@web/core/py_js/py";
import {omit} from "@web/core/utils/objects";
import {patch} from "@web/core/utils/patch";
import {status} from "@odoo/owl";
import {user} from "@web/core/user";

/** Field types a spreadsheet list cannot show. */
const UNSUPPORTED_FIELD_TYPES = ["binary", "json", "properties"];

patch(ListController.prototype, {
    /**
     * "Add to spreadsheet" button of the list view control panel.
     *
     * Handled by the controller of the clicked view itself. Since saas-19.4
     * a list view loads its records lazily: the control panel, and this
     * button, are shown before the records, while the ListRenderer is only
     * mounted once they are loaded. A click during that load used to be sent
     * on the global bus to a renderer that did not exist yet, and was lost.
     * Handling it here also keeps x2many lists (which have no controller) and
     * the other list views mounted at the same time out of it.
     */
    async onSpreadsheetButtonClicked() {
        await this.model.whenReady.promise;
        if (status(this) === "destroyed") {
            return;
        }
        const root = this.model.root;
        const name = this.env.config.getDisplayName();
        await this.actionService.doAction(
            "spreadsheet_oca.spreadsheet_spreadsheet_import_act_window",
            {
                additionalContext: {
                    default_name: name,
                    default_datasource_name: name,
                    default_can_be_dynamic: true,
                    default_dynamic: true,
                    default_is_tree: true,
                    default_number_of_rows: Math.min(root.count, root.limit),
                    default_import_data: {
                        mode: "list",
                        metaData: {
                            model: root.resModel,
                            domain: this.env.searchModel.domainString,
                            orderBy: root.orderBy,
                            // The session keys of the inserting user must not
                            // be stored for every reader of the spreadsheet.
                            context: omit(
                                root.context || {},
                                ...Object.keys(user.context)
                            ),
                            columns: this.getSpreadsheetColumns(),
                            fields: root.fields,
                            name,
                        },
                    },
                },
            }
        );
    },
    /**
     * Columns of the list as the user sees them: the columns of the arch
     * without the hidden optional ones, the invisible ones, the handle and the
     * field types a spreadsheet list cannot show.
     *
     * @returns {Object[]} {name, type} of each column
     */
    getSpreadsheetColumns() {
        const root = this.model.root;
        const fields = root.fields;
        return this.archInfo.columns
            .filter((column) => {
                const field = column.type === "field" && fields[column.name];
                if (!field || UNSUPPORTED_FIELD_TYPES.includes(field.type)) {
                    return false;
                }
                if (column.field?.component === HandleField) {
                    return false;
                }
                if (column.optional) {
                    // Filled by the renderer from the user's stored choice.
                    const shown =
                        column.name in this.optionalActiveFields
                            ? this.optionalActiveFields[column.name]
                            : column.optional === "show";
                    if (!shown) {
                        return false;
                    }
                }
                return !(
                    column.column_invisible &&
                    evaluateBooleanExpr(column.column_invisible, root.evalContext)
                );
            })
            .map((column) => ({name: column.name, type: fields[column.name].type}));
    },
});
