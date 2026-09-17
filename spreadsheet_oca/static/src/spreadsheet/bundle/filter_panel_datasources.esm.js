import * as spreadsheet from "@odoo/o-spreadsheet";
import {Component, onWillStart, onWillUpdateProps, proxy} from "@odoo/owl";
import {Domain} from "@web/core/domain";
import {DomainSelector} from "@web/core/domain_selector/domain_selector";
import {DomainSelectorDialog} from "@web/core/domain_selector_dialog/domain_selector_dialog";
import {ODOO_AGGREGATORS} from "@spreadsheet/pivot/pivot_helpers";
import {_t} from "@web/core/l10n/translation";
import {formatDate} from "@web/core/l10n/dates";
import {useRef} from "@web/owl2/utils";
import {useService} from "@web/core/utils/hooks";

const {DateTime} = luxon;
const {PivotTitleSection, PivotLayoutConfigurator} = spreadsheet.components;
const {useLocalStore, PivotSidePanelStore} = spreadsheet.stores;
const {sidePanelRegistry, topbarMenuRegistry, pivotSidePanelRegistry} =
    spreadsheet.registries;

/**
 * Largest pivot (rows x data columns) inserted as static values, the limit
 * o-spreadsheet itself applies to "Data > Re-insert static pivot": beyond it,
 * writing one formula per cell freezes the browser.
 */
export const MAX_STATIC_PIVOT_CELLS = 500000;

/** Rows proposed by the list panel for a list no cell shows yet: a list view page. */
const DEFAULT_LIST_ROWS = 80;

topbarMenuRegistry.addChild("data_sources", ["data"], (env) => {
    let sequence = 53;
    const lists = env.model.getters.getListIds().map((listId, index) => ({
        id: `data_source_list_${listId}`,
        name: env.model.getters.getListDisplayName(listId),
        sequence: sequence++,
        execute: (child_env) => child_env.openSidePanel("ListPanel", {listId}),
        icon: "spreadsheet_oca.ListIcon",
        separator: index === env.model.getters.getListIds().length - 1,
    }));
    return lists.concat([
        {
            id: "refresh_all_data",
            name: _t("Refresh all data"),
            sequence: 110,
            execute: (child_env) => {
                child_env.model.dispatch("REFRESH_ALL_DATA_SOURCES");
            },
            separator: true,
        },
    ]);
});

export class PivotLayoutConfiguratorWithAggregators extends PivotLayoutConfigurator {
    setup() {
        super.setup();
        this.AGGREGATORS = ODOO_AGGREGATORS;
    }
}

export class PivotTitleSectionInsertion extends PivotTitleSection {
    get cogWheelMenuItems() {
        // Like core "Data > Re-insert pivot": a pivot in error has no table.
        const isValid = (env) =>
            env.model.getters.getPivot(this.props.pivotId).isValid();
        return [
            ...super.cogWheelMenuItems,
            {
                id: "pivot_panel_reinsert_dynamic",
                name: _t("Re-insert Dynamic"),
                icon: "o-spreadsheet-Icon.INSERT_PIVOT",
                execute: (env) => this.reinsertTable(env, "dynamic"),
                isVisible: isValid,
            },
            {
                id: "pivot_panel_reinsert_static",
                name: _t("Re-insert Static"),
                icon: "o-spreadsheet-Icon.INSERT_PIVOT",
                execute: (env) => this.reinsertTable(env, "static"),
                isVisible: isValid,
            },
        ];
    }
    /**
     * Insert the pivot at the selected cell.
     *
     * Dynamic: a single =PIVOT() formula spilling the collapsed layout, which
     * follows the data and the global filters. Static: one PIVOT.HEADER /
     * PIVOT.VALUE formula per cell of the fully expanded layout.
     *
     * @param {Object} env spreadsheet env
     * @param {"dynamic"|"static"} mode
     */
    reinsertTable(env, mode) {
        const {getters} = env.model;
        const pivotId = this.props.pivotId;
        const pivot = getters.getPivot(pivotId);
        const table =
            mode === "dynamic"
                ? pivot.getCollapsedTableStructure()
                : pivot.getExpandedTableStructure();
        if (mode === "static" && table.numberOfCells > MAX_STATIC_PIVOT_CELLS) {
            env.notifyUser({
                type: "warning",
                sticky: true,
                text: _t(
                    "This pivot has %(cells)s cells, too many to insert as static values. Re-insert it as dynamic, or remove row or column groups first.",
                    {cells: table.numberOfCells}
                ),
            });
            return;
        }
        const zone = getters.getSelectedZone();
        env.model.dispatch("INSERT_PIVOT_WITH_TABLE", {
            pivotId,
            table: table.export(),
            col: zone.left,
            row: zone.top,
            sheetId: getters.getActiveSheetId(),
            pivotMode: mode,
        });
        env.model.dispatch("REFRESH_PIVOT", {id: pivotId});
    }
}

export class PivotPanelDisplay extends Component {
    setup() {
        this.dialog = useService("dialog");
        this.store = useLocalStore(PivotSidePanelStore, this.props.pivotId);
        this.pivotPanelRef = useRef("pivotPanel");
        // Owl 3 calls onWillStart callbacks with the component scope as first
        // argument (and onWillUpdateProps ones with the next props): never
        // hand them a method whose first parameter means something else.
        onWillStart(() => this.modelData(this.props));
        onWillUpdateProps((nextProps) => this.modelData(nextProps));
    }
    /**
     * @param {Object} props the next props when the panel switches to another
     *   pivot, the current ones on start
     */
    async modelData(props) {
        this.PivotDataSource = this.env.model.getters.getPivot(props.pivotId);
        this.modelLabel = await this.PivotDataSource.getModelLabel();
    }
    get domain() {
        return new Domain(this.store.definition.domain).toString();
    }
    get lastUpdate() {
        const lastUpdate = this.PivotDataSource.lastUpdate;
        if (lastUpdate) {
            return formatDate(DateTime.fromMillis(lastUpdate));
        }
        return _t("not updated");
    }
    editDomain() {
        this.dialog.add(DomainSelectorDialog, {
            resModel: this.store.definition.model,
            domain: this.domain,
            readonly: false,
            isDebugMode: Boolean(this.env.debug),
            onConfirm: this.onSelectDomain.bind(this),
        });
    }
    updateDimensions(dimensions) {
        this.store.update(dimensions);
    }
    /**
     * @param {String} domain the domain confirmed in DomainSelectorDialog,
     *   which is always a string
     */
    onSelectDomain(domain) {
        // Stored like the pivots inserted from a pivot view (and like core
        // export): a list when the domain can be evaluated without a context,
        // the string otherwise so uid / context_today() stay dynamic.
        this.store.update({domain: new Domain(domain).toJson()});
    }
    getScrollableContainerEl() {
        return this.pivotPanelRef.el;
    }
    flipAxis() {
        const dimensions = {
            rows: this.store.definition.columns,
            columns: this.store.definition.rows,
        };
        this.updateDimensions(dimensions);
    }
}

PivotPanelDisplay.template = "spreadsheet_oca.PivotPanelDisplay";
PivotPanelDisplay.components = {
    DomainSelector,
    PivotTitleSectionInsertion,
    PivotLayoutConfiguratorWithAggregators,
};
PivotPanelDisplay.props = {
    pivotId: String,
};

export class PivotPanel extends Component {
    get pivotId() {
        return this.props.pivotId;
    }
    get pivotType() {
        return this.env.model.getters.getPivotCoreDefinition(this.pivotId).type;
    }
}

PivotPanel.template = "spreadsheet_oca.PivotPanel";
PivotPanel.components = {
    PivotPanelDisplay,
};

try {
    pivotSidePanelRegistry.add("ODOO", {editor: PivotPanel});
} catch {
    pivotSidePanelRegistry.replace("ODOO", {editor: PivotPanel});
}

export class ListPanelDisplay extends Component {
    setup() {
        this.state = proxy({listRows: undefined});
        this.dialog = useService("dialog");
        // Owl 3 calls onWillStart callbacks with the component scope as first
        // argument: a bound modelData received that scope as its props and
        // asked the list plugin for the data source of list "undefined".
        onWillStart(() => this.modelData(this.props));
        onWillUpdateProps((nextProps) => this.modelData(nextProps));
    }
    /**
     * @param {Object} props the next props when the panel switches to another
     *   list, the current ones on start
     */
    async modelData(props) {
        this.ListDataSource = await this.env.model.getters.getAsyncListDataSource(
            props.listId
        );
        this.modelLabel = await this.ListDataSource.getModelLabel();
        if (this.rowsListId !== props.listId) {
            this.rowsListId = props.listId;
            this.state.listRows = String(await this.getDefaultListRows());
        }
    }
    /**
     * Rows proposed for "Insert list": as many as the spreadsheet already
     * shows for this list, otherwise one list view page of its records.
     *
     * @returns {Promise<Number>}
     */
    async getDefaultListRows() {
        if (this.ListDataSource.maxPosition > 0) {
            return this.ListDataSource.maxPosition;
        }
        try {
            const count = await this.ListDataSource.getRecordsCount();
            return Math.min(count, DEFAULT_LIST_ROWS) || DEFAULT_LIST_ROWS;
        } catch (error) {
            // An invalid model or domain: the panel still opens, the user
            // picks the number of rows.
            console.warn("spreadsheet_oca: could not count the list records", error);
            return DEFAULT_LIST_ROWS;
        }
    }
    get domain() {
        return new Domain(this.props.listDefinition.domain).toString();
    }
    get lastUpdate() {
        const lastUpdate = this.ListDataSource.lastUpdate;
        if (lastUpdate) {
            return formatDate(DateTime.fromMillis(lastUpdate));
        }
        return _t("not updated");
    }
    editDomain() {
        this.dialog.add(DomainSelectorDialog, {
            resModel: this.props.listDefinition.model,
            domain: this.domain,
            readonly: false,
            isDebugMode: Boolean(this.env.debug),
            onConfirm: this.onSelectDomain.bind(this),
        });
    }
    /**
     * @param {String} domain the domain confirmed in DomainSelectorDialog
     */
    onSelectDomain(domain) {
        this.env.model.dispatch("UPDATE_ODOO_LIST_DOMAIN", {
            listId: this.props.listId,
            // Not toList(): evaluated without a context it throws on uid and
            // freezes context_today() to today's date. The list data source
            // evaluates the stored domain with the user context on each load.
            domain: new Domain(domain).toJson(),
        });
    }
    /**
     * Insert the list at the selected cell as one dynamic =ODOO.LIST() formula,
     * the same form "Add to spreadsheet" uses from a list view.
     */
    insertList() {
        const listId = this.props.listId;
        const {getters} = this.env.model;
        const linesNumber = parseInt(this.state.listRows, 10);
        if (!(linesNumber > 0)) {
            // Without a size, =ODOO.LIST() would spill every record under a
            // header-only table: ask for the number instead.
            this.env.notifyUser({
                type: "warning",
                sticky: false,
                text: _t(
                    "Enter the number of rows to insert (1 or more) in Rows, then click Insert list again."
                ),
            });
            return;
        }
        const zone = getters.getSelectedZone();
        this.env.model.dispatch("RE_INSERT_ODOO_LIST_WITH_TABLE", {
            sheetId: getters.getActiveSheetId(),
            col: zone.left,
            row: zone.top,
            listId,
            linesNumber,
            // Columns are {name, string?} objects since saas-19.3.
            columns: getters.getListDefinition(listId).columns,
            mode: "dynamic",
        });
    }
    delete() {
        this.env.askConfirmation(
            _t("Are you sure you want to delete this list?"),
            () => {
                this.env.model.dispatch("REMOVE_ODOO_LIST", {
                    listId: this.props.listId,
                });
                this.env.openSidePanel("ListPanel", {});
            }
        );
    }
}

ListPanelDisplay.template = "spreadsheet_oca.ListPanelDisplay";
ListPanelDisplay.components = {
    DomainSelector,
};
ListPanelDisplay.props = {
    listId: String,
    listDefinition: Object,
};

export class ListPanel extends Component {
    get listId() {
        return this.props.listId;
    }
    get listDefinition() {
        return this.env.model.getters.getListDefinition(this.listId) || {};
    }
}

ListPanel.template = "spreadsheet_oca.ListPanel";
ListPanel.components = {
    ListPanelDisplay,
};

const LIST_PANEL = {title: _t("List information"), Body: ListPanel};
try {
    sidePanelRegistry.add("ListPanel", LIST_PANEL);
} catch {
    sidePanelRegistry.replace("ListPanel", LIST_PANEL);
}
