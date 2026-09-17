import {GraphRenderer} from "@web/views/graph/graph_renderer";

import {patch} from "@web/core/utils/patch";

patch(GraphRenderer.prototype, {
    /**
     * Saas-19.4 has no `noDataDisplayed` on the graph renderer: the model tells
     * whether real data points are shown. Sample data (shown when the domain
     * matches nothing) must not be inserted in a spreadsheet either.
     *
     * @returns {Boolean}
     */
    disableSpreadsheetInsertion() {
        return !this.model.hasData() || Boolean(this.model.useSampleModel);
    },
    onSpreadsheetButtonClicked() {
        this.actionService.doAction(
            "spreadsheet_oca.spreadsheet_spreadsheet_import_act_window",
            {
                additionalContext: {
                    default_name: this.model.metaData.title,
                    default_datasource_name: this.model.metaData.title,
                    default_import_data: {
                        mode: "graph",
                        metaData: this.model.metaData,
                        searchParams: {
                            ...this.model.searchParams,
                            domain: this.env.searchModel.domainString,
                        },
                    },
                },
            }
        );
    },
});
