/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {useState, useSubEnv} from "@odoo/owl";
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
        this.templateState = useState({canSaveAsTemplate: false});
        this._checkTemplatePermission();
        useSubEnv({
            saveAsTemplate: this._saveAsTemplate.bind(this),
            canSaveAsTemplate: () => this.templateState.canSaveAsTemplate,
        });
    },
    async _checkTemplatePermission() {
        const result =
            (await user.hasGroup("base.group_system")) ||
            (await user.hasGroup("spreadsheet_template_oca.group_template_manager"));
        this.templateState.canSaveAsTemplate = result;
    },
    async _saveAsTemplate() {
        const record = this.props.record;
        const resId = this.props.res_id;
        const name = record.name;
        this.onSpreadsheetSaved();
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
