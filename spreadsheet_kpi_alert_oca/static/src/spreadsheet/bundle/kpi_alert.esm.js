/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {onWillUnmount, useSubEnv} from "@odoo/owl";
import {SpreadsheetRenderer} from "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {waitForDataLoaded} from "@spreadsheet/helpers/model";

const {topbarMenuRegistry} = spreadsheet.registries;

// Add "KPI Alerts" to the Data menu
topbarMenuRegistry.addChild("kpi_alerts", ["data"], {
    name: _t("KPI Alerts"),
    sequence: 100,
    execute: (env) => env.openKpiAlerts(),
    icon: "o-spreadsheet-Icon.FILTER_ICON_ACTIVE",
});

// How often to sync cell values to the server (ms)
const KPI_SYNC_INTERVAL = 5 * 60 * 1000; // 5 minutes

patch(SpreadsheetRenderer.prototype, {
    setup() {
        super.setup();
        this._kpiAlerts = [];
        this._kpiSyncTimer = null;
        this._kpiStartTimer = null;
        this._destroyed = false;
        useSubEnv({
            openKpiAlerts: this._openKpiAlerts.bind(this),
        });

        // Start KPI value sync after data is loaded
        const originalOnMounted = this._startKpiSync.bind(this);
        // Use a small delay to let the spreadsheet fully initialize. Track the
        // timer so an early unmount cancels it instead of firing on a destroyed
        // component (which would leave an orphaned 5-min RPC interval).
        this._kpiStartTimer = setTimeout(() => originalOnMounted(), 3000);

        onWillUnmount(() => {
            this._destroyed = true;
            clearTimeout(this._kpiStartTimer);
            if (this._kpiSyncTimer) {
                clearInterval(this._kpiSyncTimer);
                this._kpiSyncTimer = null;
            }
        });
    },

    async _startKpiSync() {
        if (this._destroyed) {
            return;
        }
        if (this.props.model !== "spreadsheet.spreadsheet") {
            return;
        }
        await this._syncKpiValues();
        // The component may have unmounted during the await; don't arm a timer
        // that would call into a destroyed component.
        if (this._destroyed) {
            return;
        }
        this._kpiSyncTimer = setInterval(
            () => this._syncKpiValues(),
            KPI_SYNC_INTERVAL
        );
    },

    /**
     * Fetch alerts for this spreadsheet and send current cell values to server.
     */
    async _syncKpiValues() {
        try {
            const alerts = await this.orm.searchRead(
                "spreadsheet.kpi.alert",
                [
                    ["spreadsheet_id", "=", this.props.res_id],
                    ["active", "=", true],
                ],
                ["id", "sheet_name", "cell_ref"]
            );

            if (!alerts.length) return;

            this._kpiAlerts = alerts;
            await waitForDataLoaded(this.spreadsheet_model);

            const getters = this.spreadsheet_model.getters;
            const sheetIds = getters.getSheetIds();
            const values = {};

            for (const alert of alerts) {
                const sheetId = sheetIds.find(
                    (id) => getters.getSheetName(id) === alert.sheet_name
                );
                if (!sheetId) continue;

                const {col, row} = this._parseCellRef(alert.cell_ref);
                if (col < 0 || row < 0) continue;

                const cell = getters.getEvaluatedCell({sheetId, col, row});
                if (cell.type !== "empty" && cell.value !== undefined) {
                    const numVal = Number(cell.value);
                    if (!isNaN(numVal)) {
                        values[alert.id] = numVal;
                    }
                }
            }

            if (Object.keys(values).length) {
                await this.orm.call(
                    "spreadsheet.kpi.alert",
                    "update_cell_values",
                    [Object.keys(values).map(Number)],
                    {values}
                );
            }
        } catch (e) {
            // Don't break the spreadsheet if KPI sync fails
            console.warn("KPI Alert sync failed:", e);
        }
    },

    /**
     * Parse a cell reference like "B2" into {col, row} (0-indexed).
     */
    _parseCellRef(ref) {
        const match = ref.match(/^([A-Z]+)(\d+)$/i);
        if (!match) return {col: -1, row: -1};

        let col = 0;
        const letters = match[1].toUpperCase();
        for (let i = 0; i < letters.length; i++) {
            col = col * 26 + (letters.charCodeAt(i) - 64);
        }
        col -= 1; // 0-indexed

        const row = parseInt(match[2], 10) - 1; // 0-indexed
        return {col, row};
    },

    /**
     * Open the KPI Alerts management view for this spreadsheet.
     */
    _openKpiAlerts() {
        this.env.services.action.doAction({
            name: _t("KPI Alerts"),
            type: "ir.actions.act_window",
            res_model: "spreadsheet.kpi.alert",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: [["spreadsheet_id", "=", this.props.res_id]],
            context: {
                default_spreadsheet_id: this.props.res_id,
            },
        });
    },
});
