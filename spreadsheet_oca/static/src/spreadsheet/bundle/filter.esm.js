import * as spreadsheet from "@odoo/o-spreadsheet";
import {Component, onWillStart, proxy} from "@odoo/owl";
import {DefaultDateValue} from "@spreadsheet/global_filters/components/default_date_value/default_date_value";
import {Domain} from "@web/core/domain";
import {DomainSelector} from "@web/core/domain_selector/domain_selector";
import {DomainSelectorDialog} from "@web/core/domain_selector_dialog/domain_selector_dialog";
import {FilterValue} from "@spreadsheet/global_filters/components/filter_value/filter_value";
import {ModelFieldSelector} from "@web/core/model_field_selector/model_field_selector";
import {ModelSelector} from "@web/core/model_selector/model_selector";
import {MultiRecordSelector} from "@web/core/record_selectors/multi_record_selector";
import {TextFilterValue} from "@spreadsheet/global_filters/components/filter_text_value/filter_text_value";
import {_t} from "@web/core/l10n/translation";
import {globalFieldMatchingRegistry} from "@spreadsheet/global_filters/helpers";
import {useService} from "@web/core/utils/hooks";
import {user} from "@web/core/user";

const {Checkbox} = spreadsheet.components;
const {sidePanelRegistry, topbarMenuRegistry} = spreadsheet.registries;
const uuidGenerator = spreadsheet.helpers.UuidGenerator;

// Field types a data source field may have to be matched with a filter of the
// given type. Relational fields are always listed so the user can follow them
// to a field of a related model.
const ALLOWED_FIELD_TYPES = {
    date: ["date", "datetime"],
    relation: ["many2one", "many2many", "one2many"],
    text: ["char", "text", "html", "selection", "many2one"],
    selection: ["selection"],
    numeric: ["integer", "float", "monetary"],
    boolean: ["boolean"],
};

// "file" menu is already registered by o-spreadsheet core in Odoo 19
topbarMenuRegistry.addChild("filters", ["file"], {
    name: _t("Filters"),
    sequence: 70,
    execute: (env) => env.openSidePanel("FilterPanel", {}),
    icon: "o-spreadsheet-Icon.GLOBAL_FILTERS",
});
topbarMenuRegistry.addChild("save", ["file"], {
    name: _t("Save"),
    sequence: 10,
    execute: (env) => env.saveSpreadsheet(),
    icon: "o-spreadsheet-Icon.DOWNLOAD",
});
topbarMenuRegistry.addChild("download", ["file"], {
    name: _t("Download XLSX"),
    sequence: 20,
    execute: (env) => env.downloadAsXLXS(),
    icon: "o-spreadsheet-Icon.EXPORT_XLSX",
});

function registerSidePanel(name, panel) {
    if (sidePanelRegistry.contains(name)) {
        sidePanelRegistry.replace(name, panel);
    } else {
        sidePanelRegistry.add(name, panel);
    }
}

/**
 * Serialize a domain (list or string) for the components that expect a string.
 * An unreadable domain is shown as empty instead of breaking the panel.
 */
function domainToString(domain) {
    try {
        return new Domain(domain || []).toString();
    } catch (error) {
        console.warn("spreadsheet_oca: invalid filter domain ignored", domain, error);
        return "[]";
    }
}

export class FilterPanel extends Component {
    onEditFilter(filter) {
        this.env.openSidePanel("EditFilterPanel", {filter});
    }
    onAddFilter(type) {
        this.env.openSidePanel("EditFilterPanel", {filter: {type: type}});
    }
    getGlobalFilterValue(filterId) {
        return this.env.model.getters.getGlobalFilterValue(filterId);
    }
    setGlobalFilterValue(filterId, value) {
        this.env.model.dispatch("SET_GLOBAL_FILTER_VALUE", {id: filterId, value});
    }
}

FilterPanel.template = "spreadsheet_oca.FilterPanel";
FilterPanel.components = {
    FilterValue,
};

registerSidePanel("FilterPanel", {title: _t("Filters"), Body: FilterPanel});

export class EditFilterPanel extends Component {
    setup() {
        const filter = this.props.filter;
        this.filterId = filter.id;
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.relatedModels = [];
        this.state = proxy({
            label: filter.label,
            type: filter.type,
            // Kept in the saas-19.4 command format (checkFilterDefaultValueIsValid
            // in @spreadsheet/global_filters/helpers): relation {operator, ids},
            // text {operator, strings}, date a globalFilterDateRegistry key.
            defaultValue: filter.defaultValue,
            modelData: {technical: filter.modelName, label: null},
            objects: {},
            includeChildren:
                filter.includeChildren || filter.defaultValue?.operator === "child_of",
            domainOfAllowedValues: filter.domainOfAllowedValues,
            valuesRestricted: domainToString(filter.domainOfAllowedValues) !== "[]",
        });
        onWillStart(async () => {
            await this.loadModelData();
            await this.loadDataSources();
        });
    }
    async loadModelData() {
        const technicalName = this.state.modelData.technical;
        if (!technicalName) {
            return;
        }
        const [modelInfo] = await this.orm.call("ir.model", "display_name_for", [
            [technicalName],
        ]);
        this.state.modelData.label = modelInfo?.display_name || technicalName;
        this.state.modelData.hasParentRelation =
            this.state.includeChildren ||
            (await this.orm.call("ir.model", "has_parent_relation", [technicalName]));
    }
    /**
     * Collect the data sources (pivots, lists, charts) the filter can be
     * matched with. A data source whose model cannot be loaded (renamed or
     * uninstalled) is skipped with a warning so the other ones stay editable.
     */
    async loadDataSources() {
        const getters = this.env.model.getters;
        const relatedModels = new Set();
        const unavailable = [];
        for (const type of globalFieldMatchingRegistry.getKeys()) {
            const matcher = globalFieldMatchingRegistry.get(type);
            let ids = [];
            try {
                ids = matcher.getIds(getters);
                await Promise.allSettled(matcher.waitForReady(getters) || []);
            } catch (error) {
                console.warn(
                    `spreadsheet_oca: cannot list ${type} data sources`,
                    error
                );
                continue;
            }
            for (const objectId of ids) {
                let name = `${type} ${objectId}`;
                try {
                    name = matcher.getDisplayName(getters, objectId);
                    const fields = matcher.getFields(getters, objectId);
                    if (!fields || !Object.keys(fields).length) {
                        throw new Error(`No fields loaded for ${type} ${objectId}`);
                    }
                    for (const field of Object.values(fields)) {
                        if (field.relation) {
                            relatedModels.add(field.relation);
                        }
                    }
                    const key = `${type}_${objectId}`;
                    this.state.objects[key] = {
                        id: key,
                        objectId,
                        name,
                        tag: await matcher.getTag(getters, objectId),
                        // Copy: the panel edits it before the command is sent,
                        // the getter returns the plugin's own object.
                        fieldMatch: {
                            ...matcher.getFieldMatching(
                                getters,
                                objectId,
                                this.filterId
                            ),
                        },
                        type,
                        model: matcher.getModel(getters, objectId),
                    };
                } catch (error) {
                    console.warn(
                        `spreadsheet_oca: field matching unavailable for ${type} ${objectId}`,
                        error
                    );
                    unavailable.push(name);
                }
            }
        }
        this.relatedModels = [...relatedModels];
        if (unavailable.length) {
            this.notification.add(
                _t(
                    "The fields of these data sources could not be loaded, so this filter cannot be matched with them: %(names)s. Their model may have been renamed or uninstalled; fix or delete these data sources, then open the filter again.",
                    {names: unavailable.join(", ")}
                ),
                {type: "warning"}
            );
        }
    }
    /**
     * Models offered for a relation filter: the relations of the data source
     * fields, or every model when the spreadsheet has no data source yet.
     */
    get models() {
        return this.relatedModels.length ? this.relatedModels : undefined;
    }
    get dateOffset() {
        return [
            {value: 0, name: ""},
            {value: -1, name: _t("Previous")},
            {value: -2, name: _t("Before Previous")},
            {value: 1, name: _t("Next")},
            {value: 2, name: _t("After next")},
        ];
    }
    get dateDefaultValue() {
        const value = this.state.defaultValue;
        return typeof value === "string" ? value : undefined;
    }
    get textDefaultStrings() {
        return this.state.defaultValue?.strings || [];
    }
    get relationDefaultIds() {
        const ids = this.state.defaultValue?.ids;
        return Array.isArray(ids) ? ids : [];
    }
    get isCurrentUserDefault() {
        return this.state.defaultValue?.ids === "current_user";
    }
    /** Domain of the allowed values, as the string DomainSelector expects. */
    get allowedValuesDomain() {
        return domainToString(this.state.domainOfAllowedValues);
    }
    onChangeFieldMatchOffset(object, ev) {
        this.state.objects[object.id].fieldMatch.offset = parseInt(ev.target.value, 10);
    }
    async onModelSelected({technical, label}) {
        if (technical !== this.state.modelData.technical) {
            // Record ids and domains of the previous model are meaningless now.
            this.state.defaultValue = undefined;
            this.state.domainOfAllowedValues = undefined;
            this.state.valuesRestricted = false;
        }
        this.state.modelData.technical = technical;
        this.state.modelData.label = label;
        this.state.modelData.hasParentRelation = await this.orm.call(
            "ir.model",
            "has_parent_relation",
            [technical]
        );
    }
    onDateDefaultValueChanged(value) {
        this.state.defaultValue = value;
    }
    onTextDefaultValueChanged(strings) {
        const operator = this.state.defaultValue?.strings
            ? this.state.defaultValue.operator
            : "ilike";
        this.state.defaultValue = strings.length ? {operator, strings} : undefined;
    }
    onRecordsSelected(resIds) {
        this.state.defaultValue = resIds.length
            ? {operator: "in", ids: resIds}
            : undefined;
    }
    onCurrentUserDefaultChanged(checked) {
        this.state.defaultValue = checked
            ? {operator: "in", ids: "current_user"}
            : undefined;
    }
    onUpdateDomain(domain) {
        this.state.domainOfAllowedValues = domain;
    }
    /** Domain of the allowed values evaluated as a list (MultiRecordSelector). */
    getCorrectDomain() {
        const domain = this.state.domainOfAllowedValues;
        if (!domain) {
            return [];
        }
        try {
            return new Domain(domain).toList(user.context);
        } catch (error) {
            console.warn(
                "spreadsheet_oca: invalid filter domain ignored",
                domain,
                error
            );
            return [];
        }
    }
    changeDomainRestriction(value) {
        this.state.valuesRestricted = value;
        this.state.domainOfAllowedValues = undefined;
    }
    editDomain() {
        this.dialog.add(DomainSelectorDialog, {
            resModel: this.state.modelData.technical,
            domain: this.allowedValuesDomain,
            readonly: false,
            isDebugMode: Boolean(this.env.debug),
            onConfirm: this.onUpdateDomain.bind(this),
        });
    }
    getRelationDefaultValue() {
        const value = this.state.defaultValue;
        if (!value || !("ids" in value)) {
            // No default, or a default this editor does not handle (e.g. set /
            // not set): keep it as is.
            return value;
        }
        if (value.ids !== "current_user" && !value.ids?.length) {
            return undefined;
        }
        let operator = value.operator;
        if (this.state.includeChildren) {
            operator = "child_of";
        } else if (!operator || operator === "child_of") {
            operator = "in";
        }
        return {...value, operator};
    }
    getFilterDefinition() {
        const original = this.props.filter;
        const filter = {
            // Keep the keys this editor does not manage (e.g. the model of a
            // selection filter).
            ...original,
            id: this.filterId || uuidGenerator.smallUuid(),
            type: this.state.type,
            label: (this.state.label || "").trim(),
            defaultValue: this.state.defaultValue,
        };
        delete filter.defaultValueDisplayNames;
        delete filter.rangeType;
        if (filter.type === "relation") {
            filter.modelName = this.state.modelData.technical;
            filter.includeChildren = Boolean(this.state.includeChildren);
            filter.defaultValue = this.getRelationDefaultValue();
            // A list when the domain is static, the string when it uses context
            // values (e.g. uid) so they are evaluated when the filter is used.
            filter.domainOfAllowedValues =
                this.state.valuesRestricted && this.allowedValuesDomain !== "[]"
                    ? new Domain(this.allowedValuesDomain).toJson()
                    : undefined;
        }
        if (original.rangesOfAllowedValues?.length) {
            // Commands take range data, the getter returns ranges.
            filter.rangesOfAllowedValues = original.rangesOfAllowedValues.map(
                (range) => ({_sheetId: range.sheetId, _zone: range.unboundedZone})
            );
        }
        return filter;
    }
    getFieldMatchings() {
        const fieldMatchings = {};
        for (const object of Object.values(this.state.objects)) {
            const {chain, type, offset} = object.fieldMatch || {};
            const fieldMatch = {};
            if (chain) {
                Object.assign(fieldMatch, {chain, type});
                if (this.state.type === "date" && offset) {
                    fieldMatch.offset = offset;
                }
            }
            fieldMatchings[object.type] = fieldMatchings[object.type] || {};
            fieldMatchings[object.type][object.objectId] = fieldMatch;
        }
        return fieldMatchings;
    }
    get invalidDefaultValueMessage() {
        return _t(
            "The default value does not fit this filter type. Clear the default value or pick it again, then save."
        );
    }
    getRejectionMessage(result, filter) {
        if (result.isCancelledBecause("InvalidFilterLabel")) {
            return _t(
                "Give the filter a label before saving it: the label identifies the filter in the Filters panel and in ODOO.FILTER.VALUE formulas."
            );
        }
        if (result.isCancelledBecause("DuplicatedFilterLabel")) {
            return _t(
                'Another filter is already labelled "%(label)s". Choose a unique label so formulas can tell the filters apart.',
                {label: filter.label}
            );
        }
        if (result.isCancelledBecause("InvalidValueTypeCombination")) {
            return this.invalidDefaultValueMessage;
        }
        if (result.isCancelledBecause("InvalidFieldMatch")) {
            return _t(
                "A date offset is set on a data source without a matched field. Pick the field to filter on, or reset the offset, then save."
            );
        }
        return _t(
            "The filter could not be saved (%(reasons)s). Close this panel, open the filter again and retry.",
            {reasons: result.reasons.join(", ")}
        );
    }
    onSave() {
        const action = this.filterId ? "EDIT_GLOBAL_FILTER" : "ADD_GLOBAL_FILTER";
        const filter = this.getFilterDefinition();
        let result = null;
        try {
            result = this.env.model.dispatch(action, {
                filter,
                ...this.getFieldMatchings(),
            });
        } catch (error) {
            // The core validation throws ("No behavior found ...") on a default
            // value in an unknown format instead of rejecting the command.
            console.warn("spreadsheet_oca: global filter rejected", filter, error);
            this.notification.add(this.invalidDefaultValueMessage, {type: "danger"});
            return;
        }
        if (!result.isSuccessful) {
            // Stay on the panel so the user does not lose the edition.
            this.notification.add(this.getRejectionMessage(result, filter), {
                type: "danger",
            });
            return;
        }
        this.env.openSidePanel("FilterPanel", {});
    }
    onCancel() {
        this.env.openSidePanel("FilterPanel", {});
    }
    onRemove() {
        if (this.filterId) {
            this.env.model.dispatch("REMOVE_GLOBAL_FILTER", {id: this.filterId});
        }
        this.env.openSidePanel("FilterPanel", {});
    }
    onFieldMatchUpdate(object, path, fieldInfo) {
        const fieldMatch = this.state.objects[object.id].fieldMatch;
        if (!path) {
            this.state.objects[object.id].fieldMatch = {};
            return;
        }
        this.state.objects[object.id].fieldMatch = {
            chain: path,
            type: fieldInfo?.fieldDef?.type || "",
            offset: fieldMatch.offset,
        };
    }
    getModelField(fieldMatch) {
        return fieldMatch?.chain || "";
    }
    filterModelFieldSelectorField(field, path, resModel) {
        if (!field.searchable) {
            return false;
        }
        if (field.name === "id") {
            // "id" matches a relation filter on the model of the page itself.
            return (
                this.state.type === "relation" &&
                resModel === this.state.modelData.technical
            );
        }
        const allowedTypes = ALLOWED_FIELD_TYPES[this.state.type] || [];
        return allowedTypes.includes(field.type) || Boolean(field.relation);
    }
}

EditFilterPanel.template = "spreadsheet_oca.EditFilterPanel";
EditFilterPanel.components = {
    Checkbox,
    DefaultDateValue,
    DomainSelector,
    ModelFieldSelector,
    ModelSelector,
    MultiRecordSelector,
    TextFilterValue,
};

registerSidePanel("EditFilterPanel", {
    title: (env, props) => (props.filter?.id ? _t("Edit Filter") : _t("New Filter")),
    Body: EditFilterPanel,
});
