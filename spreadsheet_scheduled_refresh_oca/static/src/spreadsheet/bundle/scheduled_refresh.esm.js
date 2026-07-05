/** @odoo-module **/

import {onWillUnmount} from "@odoo/owl";
import {SpreadsheetRenderer} from "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm";
import {patch} from "@web/core/utils/patch";

// The scheduled-refresh cron emits a "refresh_data" bus message, but the base
// spreadsheet_oca renderer only subscribes to "notification" — so open sheets
// never reloaded (the whole feature was a no-op). Add the missing subscriber
// here (in the scheduled-refresh module, not the OCA base) so an open
// spreadsheet actually reloads its Odoo data sources when the cron fires.
patch(SpreadsheetRenderer.prototype, {
    setup() {
        super.setup();
        // The scheduled-refresh cron FK targets spreadsheet.spreadsheet only;
        // dashboards never receive a "refresh_data" bus message.
        if (this.props.model !== "spreadsheet.spreadsheet") {
            return;
        }
        // Stable reference so unsubscribe() removes exactly this handler.
        this._onScheduledRefresh = (payload) => {
            // subscribe() keys by TYPE, so every open sheet gets this event;
            // only react when the record id matches (payload.id is an int from
            // Python; this.props.res_id is a Number → === matches).
            if (payload && payload.id === this.props.res_id) {
                try {
                    this.spreadsheet_model.dispatch("REFRESH_ALL_DATA_SOURCES");
                } catch (e) {
                    // Model may be tearing down on navigate-away; never let a
                    // bus callback bubble an uncaught error (graceful degrade).
                    console.warn("Scheduled spreadsheet refresh skipped:", e);
                }
            }
        };
        this.bus_service.subscribe("refresh_data", this._onScheduledRefresh);
        onWillUnmount(() => {
            this.bus_service.unsubscribe("refresh_data", this._onScheduledRefresh);
        });
    },
});
