import * as spreadsheet from "@odoo/o-spreadsheet";
import {Component, onWillDestroy, onWillUpdateProps, proxy} from "@odoo/owl";
import {BACKEND_INTERVAL_OPTIONS} from "@web/search/utils/dates";
import {Domain} from "@web/core/domain";
import {DomainSelector} from "@web/core/domain_selector/domain_selector";
import {Many2XAutocomplete} from "@web/views/fields/relational_utils";
import {_t} from "@web/core/l10n/translation";
import {useService} from "@web/core/utils/hooks";

const {ChartPanel} = spreadsheet.components;
const {chartDataSourceSidePanelComponentRegistry} = spreadsheet.registries;

/**
 * Data source section of the configuration panel of a chart fed by Odoo data
 * (a graph view inserted in a spreadsheet): the "odoo" chart data source.
 *
 * The core ChartDataSourceComponent renders the component registered for the
 * type of the chart data source in chartDataSourceSidePanelComponentRegistry.
 * Community saas-19.4 only registers "range", so without this entry the side
 * panel of such a chart crashed ("Cannot find odoo in this registry!").
 *
 * Nothing here blocks the panel: the model and field labels are loaded in the
 * background and the technical names are shown until then, or when they
 * cannot be loaded (renamed or uninstalled model).
 */
export class OdooChartDataSourcePanel extends Component {
    setup() {
        this.orm = useService("orm");
        this.fieldService = useService("field");
        this.state = proxy({modelLabel: "", fields: undefined, loadError: ""});
        this.loadRequest = 0;
        // A request still running when the panel closes must not write into
        // the state of a destroyed component: invalidate it.
        onWillDestroy(() => this.loadRequest++);
        this.loadModelInfo(this.getDataSource(this.props));
        onWillUpdateProps((nextProps) => {
            const nextDataSource = this.getDataSource(nextProps);
            if (nextDataSource.metaData?.resModel !== this.resModel) {
                this.loadModelInfo(nextDataSource);
            }
        });
    }
    /**
     * @param {Object} props
     * @returns {Object} the "odoo" chart data source of the chart
     */
    getDataSource(props) {
        return props.dataSource || props.definition?.dataSource || {};
    }
    get dataSource() {
        return this.getDataSource(this.props);
    }
    get metaData() {
        return this.dataSource.metaData || {};
    }
    get resModel() {
        return this.metaData.resModel || "";
    }
    /** Domain of the chart, as the string DomainSelector expects. */
    get domain() {
        try {
            return new Domain(this.dataSource.searchParams?.domain || []).toString();
        } catch (error) {
            console.warn("spreadsheet_oca: unreadable chart domain", error);
            return "[]";
        }
    }
    /**
     * @param {String} fieldName
     * @returns {String} the field label, its technical name until the fields
     *   are loaded
     */
    getFieldLabel(fieldName) {
        return this.state.fields?.[fieldName]?.string || fieldName;
    }
    get measureLabel() {
        const measure = this.metaData.measure;
        if (!measure || measure === "__count") {
            return _t("Count");
        }
        return this.getFieldLabel(measure);
    }
    /** @returns {String[]} group bys, e.g. "Created on (Month)" for "create_date:month" */
    get groupByLabels() {
        return (this.metaData.groupBy || []).map((groupBy) => {
            const [fieldName, interval] = String(groupBy).split(":");
            const label = this.getFieldLabel(fieldName);
            if (!interval) {
                return label;
            }
            const intervalLabel = BACKEND_INTERVAL_OPTIONS[interval]?.description;
            return `${label} (${intervalLabel || interval})`;
        });
    }
    /**
     * Load the model label and its fields for the labels shown in the panel.
     *
     * @param {Object} dataSource
     */
    async loadModelInfo(dataSource) {
        const request = ++this.loadRequest;
        const resModel = dataSource.metaData?.resModel;
        const info = {modelLabel: "", fields: undefined, loadError: ""};
        if (resModel) {
            try {
                const [fields, modelNames] = await Promise.all([
                    this.fieldService.loadFields(resModel),
                    this.orm.call("ir.model", "display_name_for", [[resModel]]),
                ]);
                info.fields = fields;
                info.modelLabel = modelNames?.[0]?.display_name || "";
            } catch (error) {
                console.warn(
                    `spreadsheet_oca: cannot load the model ${resModel} of the chart`,
                    error
                );
                info.loadError = _t(
                    "The model %(model)s of this chart could not be loaded, so its technical names are shown. Check that the module providing this model is still installed, or insert the chart again from its graph view.",
                    {model: resModel}
                );
            }
        }
        // The panel may have switched to another chart in the meantime.
        if (request === this.loadRequest) {
            Object.assign(this.state, info);
        }
    }
}
OdooChartDataSourcePanel.template = "spreadsheet_oca.OdooChartDataSourcePanel";
OdooChartDataSourcePanel.components = {DomainSelector};

if (!chartDataSourceSidePanelComponentRegistry.contains("odoo")) {
    chartDataSourceSidePanelComponentRegistry.add("odoo", OdooChartDataSourcePanel);
}

/**
 * "Link to Odoo menu" section of the chart side panel.
 *
 * It is rendered by the core ChartPanel under the configuration panel of the
 * chart (see spreadsheet.xml), so every chart type gets it, whether it shows
 * cell ranges or Odoo data. The link is stored by the core ChartOdooLinkPlugin
 * (UPDATE_ODOO_LINK_TO_CHART / getChartOdooLink); a dashboard opens the linked
 * menu when the chart is clicked.
 */
export class ChartOdooMenuLink extends Component {
    setup() {
        this.menus = useService("menu");
    }
    get menuProps() {
        return {
            fieldString: _t("Menu Items"),
            resModel: "ir.ui.menu",
            update: this.updateMenu.bind(this),
            activeActions: {},
            getDomain: this.getDomain.bind(this),
            placeholder: _t("Select a menu..."),
            value: this.linkedMenu?.name || "",
        };
    }
    /**
     * Only the menus the user can open are proposed: the menu service holds
     * exactly those.
     *
     * @returns {Array}
     */
    getDomain() {
        const menuIds = this.menus
            .getAll()
            .map((menu) => menu.id)
            .filter((menuId) => menuId !== "root");
        return [["id", "in", menuIds]];
    }
    /**
     * @returns {Object|undefined} the menu (from the menu service) the chart is
     *   linked to. A chart linked to a pivot or list data source has no menu.
     */
    get linkedMenu() {
        const odooLink = this.env.model.getters.getChartOdooLink(this.props.chartId);
        if (odooLink?.type !== "odooMenu") {
            return undefined;
        }
        return this.env.model.getters.getIrMenu(odooLink.odooMenuId);
    }
    /**
     * @param {Object[]|false|undefined} records the selected menu, nothing when
     *   the input was cleared
     */
    updateMenu(records) {
        const menu = records?.length
            ? this.env.model.getters.getIrMenu(records[0].id)
            : undefined;
        // Clearing the input must not drop a data source link it never showed.
        if (!menu && !this.linkedMenu) {
            return;
        }
        this.env.model.dispatch("UPDATE_ODOO_LINK_TO_CHART", {
            chartId: this.props.chartId,
            // The xml id keeps the link valid in another database.
            odooLink: menu
                ? {type: "odooMenu", odooMenuId: menu.xmlid || menu.id}
                : undefined,
        });
    }
}
ChartOdooMenuLink.template = "spreadsheet_oca.ChartOdooMenuLink";
ChartOdooMenuLink.components = {Many2XAutocomplete};
ChartOdooMenuLink.props = {
    chartId: String,
};

ChartPanel.components = {
    ...ChartPanel.components,
    ChartOdooMenuLink,
};
