import * as spreadsheet from "@odoo/o-spreadsheet";

import {Component, onWillStart} from "@odoo/owl";
import {deepCopy, omit} from "@web/core/utils/objects";
import {Domain} from "@web/core/domain";
import {MAX_STATIC_PIVOT_CELLS} from "./filter_panel_datasources.esm";
import {SpreadsheetControlPanel} from "./spreadsheet_controlpanel.esm";
import {SpreadsheetRenderer} from "./spreadsheet_renderer.esm";
import {_t} from "@web/core/l10n/translation";
import {registry} from "@web/core/registry";
import {standardActionServiceProps} from "@web/webclient/actions/action_service";
import {useService} from "@web/core/utils/hooks";
import {useSubEnv} from "@web/owl2/utils";
import {user} from "@web/core/user";
import {waitForDataLoaded} from "@spreadsheet/helpers/model";

const {helpers, constants} = spreadsheet;
const {
    UuidGenerator: uuidGenerator,
    isDateOrDatetimeField,
    parseDimension,
    sanitizeSheetName,
} = helpers;
const actionRegistry = registry.category("actions");

/** Graph view modes, which are also the native o-spreadsheet chart types. */
const GRAPH_CHART_TYPES = ["bar", "line", "pie"];

function normalizeGroupBys(dimensions, fields) {
    return dimensions.map((dimension) => {
        const field = fields[dimension.fieldName];
        if (field && isDateOrDatetimeField(field) && !dimension.granularity) {
            return {granularity: "month", ...dimension};
        }
        return dimension;
    });
}

/**
 * Convert the sorted column of a pivot view to the o-spreadsheet format.
 *
 * The pivot view stores {groupId: [rowValues, colValues], measure: fieldName,
 * order}; a spreadsheet pivot stores {measure: measureId, order, domain}. Like
 * the core 12->13 migration, only a sort on the total column can be kept: the
 * column values of any other column cannot be typed back into a domain.
 *
 * @param {Object|null} sortedColumn pivot view sorted column
 * @param {Object[]} measures spreadsheet pivot measures
 * @returns {Object|undefined}
 */
function toSpreadsheetSortedColumn(sortedColumn, measures) {
    if (!sortedColumn || sortedColumn.groupId?.[1]?.length) {
        return undefined;
    }
    const measure = measures.find((m) => m.fieldName === sortedColumn.measure);
    if (!measure) {
        return undefined;
    }
    return {measure: measure.id, order: sortedColumn.order, domain: []};
}

/**
 * @param {Object} result o-spreadsheet DispatchResult
 * @param {String} command name of the dispatched command
 */
function assertDispatched(result, command) {
    if (!result.isSuccessful) {
        throw new Error(`${command} was refused (${result.reasons.join(", ")})`);
    }
}

export class ActionSpreadsheetOca extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const params = this.props.action.params || this.props.action.context.params;
        this.spreadsheetId = params.spreadsheet_id || params.active_id;
        this.model = params.model || "spreadsheet.spreadsheet";
        this.import_data = params.import_data || {};
        // The insertion is one-shot: the action service keeps this action (and
        // its params) to restore the editor from the breadcrumbs, and the
        // inserted data is saved in the spreadsheet by then. Re-running it on
        // return would insert the same pivot/list/chart a second time.
        delete params.import_data;
        onWillStart(async () => {
            // The get_spreadsheet_data RPC returns {name, spreadsheet_raw, revisions,
            // mode, default_currency, ...}; keep it AS-IS so the control panel
            // can read record.name. The renderer applies o-spreadsheet load()
            // to record.spreadsheet_raw itself, so wrapping the whole dict in
            // load() here was redundant and stripped .name (empty title).
            this.record =
                (await this.orm.call(
                    this.model,
                    "get_spreadsheet_data",
                    [[this.spreadsheetId]],
                    {context: {bin_size: false}}
                )) || {};
        });
        useSubEnv({
            saveRecord: this.saveRecord.bind(this),
            importData: this.importData.bind(this),
            notifyUser: this.notifyUser.bind(this),
            // Expose the loaded record to descendants (the breadcrumb name) via
            // the sub-env instead of prop-drilling it through the subclassed
            // core ControlPanel: in saas-19.4 that one reads its props through
            // the owl3 field `props = props({display, slots})`, which exposes
            // only those two keys, so a `record` prop never reaches it. A
            // getter keeps it correct after onWillStart.
            getSpreadsheetRecord: () => this.record,
        });
    }

    notifyUser(notification) {
        this.notification.add(notification.text, {
            type: notification.type,
            sticky: notification.sticky,
        });
    }
    async saveRecord(data) {
        if (this.record.mode === "readonly") {
            return;
        }
        if (this.spreadsheetId) {
            this.orm.call(this.model, "write", [this.spreadsheetId, data]);
        } else {
            this.spreadsheetId = await this.orm.call(this.model, "create", [data]);
        }
    }
    /**
     * Search params of the inserted view, with a context that only keeps what
     * describes the data: the view state (pivot_* / graph_* keys) is already
     * in the definition, and the session keys of the inserting user (lang, tz,
     * uid, allowed_company_ids) must not be stored for every other reader.
     * The list view patch strips the session keys the same way.
     *
     * @returns {Object} searchParams with a cleaned context
     */
    cleanSearchParams() {
        const searchParams = this.import_data.searchParams;
        const context = omit(searchParams.context || {}, ...Object.keys(user.context));
        for (const key of Object.keys(context)) {
            if (key.startsWith("pivot_") || key.startsWith("graph_")) {
                delete context[key];
            }
        }
        return {...searchParams, context};
    }
    /**
     * Sheet receiving the inserted data: the (empty) first sheet of a spreadsheet
     * created by the import wizard, a new sheet named after the data source
     * when adding to an existing spreadsheet, so its content is never
     * overwritten.
     *
     * @param {Object} spreadsheet_model
     * @returns {String} sheet id
     */
    importCreateOrReuseSheet(spreadsheet_model) {
        const {getters} = spreadsheet_model;
        const activeSheetId = getters.getActiveSheetId();
        if (this.import_data.new !== undefined) {
            return activeSheetId;
        }
        const sheetId = uuidGenerator.smallUuid();
        const baseName =
            sanitizeSheetName(this.import_data.name || "").trim() ||
            getters.getNextSheetName();
        let name = baseName;
        // CREATE_SHEET refuses a name that differs only by case ("Sales" next
        // to "sales"): getSheetIdByName compares names the same way.
        for (let i = 1; getters.getSheetIdByName(name); i++) {
            name = `${baseName} (${i})`;
        }
        assertDispatched(
            spreadsheet_model.dispatch("CREATE_SHEET", {
                sheetId,
                name,
                position: getters.getSheetIds().length,
            }),
            "CREATE_SHEET"
        );
        spreadsheet_model.dispatch("ACTIVATE_SHEET", {
            sheetIdFrom: activeSheetId,
            sheetIdTo: sheetId,
        });
        return sheetId;
    }
    /**
     * Insert the graph view as a native chart (bar/line/pie) fed by an "odoo"
     * data source, the saas-19.3+ replacement of the odoo_bar/odoo_line/
     * odoo_pie chart types.
     *
     * @param {Object} spreadsheet_model
     */
    async importDataGraph(spreadsheet_model) {
        const {metaData, actionXmlId, name} = this.import_data;
        const type = GRAPH_CHART_TYPES.includes(metaData.mode) ? metaData.mode : "bar";
        const searchParams = this.cleanSearchParams();
        const dataSource = {
            type: "odoo",
            cumulatedStart: Boolean(metaData.cumulatedStart),
            metaData: {
                // Graph view group bys serialize to their spec ("date:month").
                groupBy: (metaData.groupBy || []).map((groupBy) =>
                    typeof groupBy === "string" ? groupBy : groupBy.spec
                ),
                measure: metaData.measure,
                order: metaData.order || null,
                resModel: metaData.resModel,
            },
            searchParams: {
                comparison: null,
                context: searchParams.context,
                domain: new Domain(searchParams.domain).toJson(),
                groupBy: searchParams.groupBy || [],
                orderBy: searchParams.orderBy || [],
            },
        };
        if (actionXmlId) {
            dataSource.actionXmlId = actionXmlId;
        }
        const definition = {
            type,
            title: {text: name || ""},
            background: "#FFFFFF",
            legendPosition: "top",
            dataSource,
        };
        if (type !== "pie") {
            definition.stacked = Boolean(metaData.stacked);
        }
        if (type === "line") {
            definition.cumulative = Boolean(metaData.cumulated);
            definition.fillArea = true;
        }
        const sheetId = this.importCreateOrReuseSheet(spreadsheet_model);
        assertDispatched(
            spreadsheet_model.dispatch("CREATE_CHART", {
                sheetId,
                figureId: uuidGenerator.smallUuid(),
                chartId: uuidGenerator.smallUuid(),
                col: 0,
                row: 0,
                offset: {x: 0, y: 0},
                definition,
            }),
            "CREATE_CHART"
        );
    }
    /**
     * Insert the list view as one dynamic =ODOO.LIST() formula.
     *
     * @param {Object} spreadsheet_model
     */
    async importDataList(spreadsheet_model) {
        const {metaData, actionXmlId, name} = this.import_data;
        const definition = {
            model: metaData.model,
            domain: new Domain(metaData.domain).toJson(),
            context: metaData.context || {},
            orderBy: metaData.orderBy || [],
            columns: metaData.columns.map((column) => ({name: column.name})),
            name,
        };
        if (actionXmlId) {
            definition.actionXmlId = actionXmlId;
        }
        const command = {
            col: 0,
            row: 0,
            listId: spreadsheet_model.getters.getNextListId(),
            definition,
            linesNumber: this.import_data.dyn_number_of_rows,
            mode: "dynamic",
        };
        // INSERT_ODOO_LIST_WITH_TABLE is a UI command that cannot be refused:
        // check the core command it runs first, a refusal inside it would
        // throw half-way through the dispatch and break the model.
        assertDispatched(
            spreadsheet_model.canDispatch("INSERT_ODOO_LIST", {
                ...command,
                sheetId: spreadsheet_model.getters.getActiveSheetId(),
            }),
            "INSERT_ODOO_LIST"
        );
        const sheetId = this.importCreateOrReuseSheet(spreadsheet_model);
        assertDispatched(
            spreadsheet_model.dispatch("INSERT_ODOO_LIST_WITH_TABLE", {
                ...command,
                sheetId,
            }),
            "INSERT_ODOO_LIST_WITH_TABLE"
        );
        await waitForDataLoaded(spreadsheet_model);
        spreadsheet_model.dispatch("AUTORESIZE_COLUMNS", {
            sheetId,
            cols: Array.from({length: definition.columns.length}, (_, i) => i),
        });
    }
    /**
     * Insert the pivot view, dynamic (one =PIVOT() formula) unless the import
     * wizard asked for static values (one formula per cell).
     *
     * @param {Object} spreadsheet_model
     */
    async importDataPivot(spreadsheet_model) {
        const {metaData, actionXmlId, name} = this.import_data;
        const fields = metaData.fields || {};
        const measures = metaData.activeMeasures.map((fieldName) => {
            const aggregator = fields[fieldName]?.aggregator;
            return {
                id: aggregator ? `${fieldName}:${aggregator}` : fieldName,
                fieldName,
                aggregator,
            };
        });
        const colGroupBys = (metaData.colGroupBys || []).concat(
            metaData.expandedColGroupBys || []
        );
        const rowGroupBys = (metaData.rowGroupBys || []).concat(
            metaData.expandedRowGroupBys || []
        );
        const searchParams = this.cleanSearchParams();
        const definition = deepCopy({
            type: "ODOO",
            domain: new Domain(searchParams.domain).toJson(),
            context: searchParams.context,
            sortedColumn: toSpreadsheetSortedColumn(metaData.sortedColumn, measures),
            measures,
            model: metaData.resModel,
            columns: normalizeGroupBys(colGroupBys.map(parseDimension), fields),
            rows: normalizeGroupBys(rowGroupBys.map(parseDimension), fields),
            name,
            style: {tableStyleId: constants.PIVOT_INSERT_TABLE_STYLE_ID},
        });
        if (actionXmlId) {
            definition.actionXmlId = actionXmlId;
        }
        const pivotId = uuidGenerator.smallUuid();
        assertDispatched(
            spreadsheet_model.dispatch("ADD_PIVOT", {pivotId, pivot: definition}),
            "ADD_PIVOT"
        );
        const pivot = spreadsheet_model.getters.getPivot(pivotId);
        await pivot.load();
        pivot.assertIsValid();
        let pivotMode = this.import_data.dynamic === false ? "static" : "dynamic";
        let table =
            pivotMode === "dynamic"
                ? pivot.getCollapsedTableStructure()
                : pivot.getExpandedTableStructure();
        if (pivotMode === "static" && table.numberOfCells > MAX_STATIC_PIVOT_CELLS) {
            this.notification.add(
                _t(
                    "This pivot has %(cells)s cells, too many to insert as static values, so it was inserted as a dynamic pivot. Remove row or column groups before re-inserting it as static.",
                    {cells: table.numberOfCells}
                ),
                {type: "warning", sticky: true}
            );
            pivotMode = "dynamic";
            table = pivot.getCollapsedTableStructure();
        }
        const sheetId = this.importCreateOrReuseSheet(spreadsheet_model);
        assertDispatched(
            spreadsheet_model.dispatch("INSERT_PIVOT_WITH_TABLE", {
                sheetId,
                col: 0,
                row: 0,
                pivotId,
                table: table.export(),
                pivotMode,
            }),
            "INSERT_PIVOT_WITH_TABLE"
        );
        await waitForDataLoaded(spreadsheet_model);
        spreadsheet_model.dispatch("AUTORESIZE_COLUMNS", {
            sheetId,
            cols: Array.from({length: table.getNumberOfDataColumns() + 1}, (_, i) => i),
        });
    }
    /**
     * Remove what a failed insertion left behind: the pivot it added (a pivot
     * without data or table is unusable) and the sheet it created (empty or
     * half-filled), so the spreadsheet stays as it was before.
     *
     * @param {Object} spreadsheet_model
     * @param {Set<String>} sheetIds sheet ids before the insertion
     * @param {Set<String>} pivotIds pivot ids before the insertion
     */
    revertFailedImport(spreadsheet_model, sheetIds, pivotIds) {
        const {getters} = spreadsheet_model;
        try {
            for (const pivotId of getters.getPivotIds()) {
                if (!pivotIds.has(pivotId)) {
                    spreadsheet_model.dispatch("REMOVE_PIVOT", {pivotId});
                }
            }
            for (const sheetId of getters.getSheetIds()) {
                if (!sheetIds.has(sheetId)) {
                    spreadsheet_model.dispatch("DELETE_SHEET", {
                        sheetId,
                        sheetName: getters.getSheetName(sheetId),
                    });
                }
            }
        } catch (error) {
            console.warn(
                "spreadsheet_oca: could not clean up the failed insertion",
                error
            );
        }
    }
    /**
     * Insert the data prepared by the import wizard, if any.
     *
     * Never throws: the spreadsheet itself loaded fine, so a failed insertion
     * (access error on the model, refused command, ...) is reported and the
     * editor still opens instead of crashing blank.
     *
     * @param {Object} spreadsheet_model
     */
    async importData(spreadsheet_model) {
        const importers = {
            pivot: this.importDataPivot,
            graph: this.importDataGraph,
            list: this.importDataList,
        };
        const importer = importers[this.import_data.mode];
        if (!importer) {
            return;
        }
        const {getters} = spreadsheet_model;
        const sheetIds = new Set(getters.getSheetIds());
        const pivotIds = new Set(getters.getPivotIds());
        try {
            await importer.call(this, spreadsheet_model);
        } catch (error) {
            console.warn("spreadsheet_oca: data insertion failed", error);
            this.revertFailedImport(spreadsheet_model, sheetIds, pivotIds);
            this.notification.add(
                _t(
                    "The data could not be inserted in the spreadsheet: %(error)s. The spreadsheet is still open; check the view you inserted from (model, filters, measures) and try again.",
                    {error: error?.data?.message || error?.message || String(error)}
                ),
                {type: "danger", sticky: true}
            );
        }
    }
}
ActionSpreadsheetOca.template = "spreadsheet_oca.ActionSpreadsheetOca";
ActionSpreadsheetOca.components = {
    SpreadsheetRenderer,
    SpreadsheetControlPanel,
};
ActionSpreadsheetOca.props = {...standardActionServiceProps};
actionRegistry.add("action_spreadsheet_oca", ActionSpreadsheetOca, {
    force: true,
});
