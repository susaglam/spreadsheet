import {Component, t, useProps} from "@odoo/owl";
import {FileUploader} from "@web/views/fields/file_handler";
import {ListController} from "@web/views/list/list_controller";
import {_t} from "@web/core/l10n/translation";
import {listView} from "@web/views/list/list_view";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";

class SpreadsheetFileUploader extends Component {
    static template = "spreadsheet_oca.SpreadsheetFileUploader";
    static components = {FileUploader};
    // Odoo 20.0: a static `props`/`defaultProps` throws; the schema goes
    // through useProps(). `record` stays optional (the list buttons render
    // the uploader without a record).
    props = useProps({
        readonly: t.boolean().optional(),
        record: t.object().optional(),
        acceptedFileExtensions: t
            .string()
            .optional(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        togglerTemplate: t.string().optional(),
        slots: t.object().optional(),
        linkText: t.string().optional(_t("Upload a Spreadsheet")),
    });

    setup() {
        this.orm = useService("orm");
        this.attachmentIdsToProcess = [];
        this.action = useService("action");
        this.notification = useService("notification");
    }
    async onFileUploaded(file) {
        const att_data = {
            name: file.name,
            mimetype: file.type,
            // On saas-19.4, ir.attachment has no `datas` field; a base64 string
            // written to `raw` over RPC is decoded server side.
            raw: file.data,
        };
        const att_id = await this.orm.create("ir.attachment", [att_data], {
            context: this.env.searchModel.context,
        });
        this.attachmentIdsToProcess.push(att_id[0]);
    }
    async onUploadComplete() {
        let action = {};
        try {
            action = await this.orm.call(
                "spreadsheet.spreadsheet",
                "create_document_from_attachment",
                ["", this.attachmentIdsToProcess],
                {context: this.env.searchModel.context}
            );
        } finally {
            // Ensures attachments are cleared on success as well as on error
            this.attachmentIdsToProcess = [];
        }
        if (action.context && action.context.notifications) {
            for (const [file, msg] of Object.entries(action.context.notifications)) {
                this.notification.add(msg, {
                    title: file,
                    type: "info",
                    sticky: true,
                });
            }
            delete action.context.notifications;
        }
        this.action.doAction(action);
    }
}
export class SpreadsheetListController extends ListController {}
SpreadsheetListController.components = {
    ...ListController.components,
    SpreadsheetFileUploader,
};
export const SpreadsheetListView = {
    ...listView,
    Controller: SpreadsheetListController,
    buttonTemplate: "spreadsheet_oca.ListView.Buttons",
};

registry.category("views").add("spreadsheet_tree", SpreadsheetListView);
