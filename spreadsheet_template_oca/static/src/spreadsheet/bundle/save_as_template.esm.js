/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {proxy, useSubEnv} from "@odoo/owl";
import {SpreadsheetRenderer} from "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {user} from "@web/core/user";

const {topbarMenuRegistry} = spreadsheet.registries;

topbarMenuRegistry.addChild("save_as_template", ["file"], {
    name: _t("Save as Template"),
    sequence: 130,
    execute: (env) => env.saveAsTemplate(),
    isVisible: (env) => env.canSaveAsTemplate?.(),
    icon: "o-spreadsheet-Icon.INSERT_CHART",
});

patch(SpreadsheetRenderer.prototype, {
    setup() {
        super.setup();
        this.templateState = proxy({canSaveAsTemplate: false});
        this._checkTemplatePermission();
        useSubEnv({
            saveAsTemplate: this._saveAsTemplate.bind(this),
            canSaveAsTemplate: () => this.templateState.canSaveAsTemplate,
        });
    },
    async _checkTemplatePermission() {
        // The renderer is shared by every spreadsheet-like model (templates,
        // dashboards...). The wizard's spreadsheet_id points to
        // spreadsheet.spreadsheet, so offering the entry elsewhere would hand
        // it the id of an unrelated record.
        if (this.props.model !== "spreadsheet.spreadsheet") {
            return;
        }
        // Only Template Managers may create templates (ir.access.csv).
        // base.group_system is deliberately NOT accepted: it grants no ACL on
        // spreadsheet.template, so a system admin without the Template Manager
        // right would only reach an error. The wizard re-checks server-side.
        let result = false;
        try {
            result = await user.hasGroup(
                "spreadsheet_template_oca.group_template_manager"
            );
        } catch {
            // Soft-fail: keep the menu hidden rather than break the editor.
            result = false;
        }
        this.templateState.canSaveAsTemplate = Boolean(result);
    },
    async _saveAsTemplate() {
        const record = this.props.record;
        const resId = this.props.res_id;
        const name = record.name;
        // Persist current state so the wizard's create_template reads fresh
        // spreadsheet_raw, but do NOT call onSpreadsheetSaved() — that tears
        // down the collaborative session (leaveSession + off('update')) and
        // would silently kill live sync for the rest of the editing session.
        const data = this.spreadsheet_model.exportData();
        await this.env.saveRecord({spreadsheet_raw: data});
        this.env.services.action.doAction(
            {
                name: _t("Save as Template"),
                type: "ir.actions.act_window",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                res_model: "spreadsheet.to.template",
            },
            {
                additionalContext: {
                    default_spreadsheet_id: resId,
                    default_name: name,
                },
            }
        );
    },
});
