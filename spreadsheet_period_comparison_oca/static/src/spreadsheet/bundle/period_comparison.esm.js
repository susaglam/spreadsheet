/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {_t} from "@web/core/l10n/translation";

// Saas-19.2: arg is in spreadsheet.helpers, not registries
const {functionRegistry} = spreadsheet.registries;
const {arg, toNumber} = spreadsheet.helpers;

/**
 * ODOO.PERCENT_CHANGE(current, previous)
 * Returns the percentage change between two values.
 */
functionRegistry.add("ODOO.PERCENT_CHANGE", {
    description: _t("Percentage change between current and previous values."),
    args: [
        arg("current (number)", _t("Current value.")),
        arg("previous (number)", _t("Previous value.")),
    ],
    returns: ["NUMBER"],
    compute: function (current, previous) {
        const curr = toNumber(current);
        const prev = toNumber(previous);
        if (prev === 0) return 0;
        return ((curr - prev) / Math.abs(prev)) * 100;
    },
});

/**
 * ODOO.VARIANCE(current, previous)
 * Returns the absolute variance between two values.
 */
functionRegistry.add("ODOO.VARIANCE", {
    description: _t("Absolute variance between current and previous."),
    args: [
        arg("current (number)", _t("Current value.")),
        arg("previous (number)", _t("Previous value.")),
    ],
    returns: ["NUMBER"],
    compute: function (current, previous) {
        return toNumber(current) - toNumber(previous);
    },
});

/**
 * ODOO.GROWTH_ARROW(current, previous)
 * Returns an up/down arrow with the percentage change.
 */
functionRegistry.add("ODOO.GROWTH_ARROW", {
    description: _t("Arrow + percentage showing growth direction."),
    args: [
        arg("current (number)", _t("Current value.")),
        arg("previous (number)", _t("Previous value.")),
    ],
    returns: ["STRING"],
    compute: function (current, previous) {
        const curr = toNumber(current);
        const prev = toNumber(previous);
        if (prev === 0) return "—";
        const change = ((curr - prev) / Math.abs(prev)) * 100;
        const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "—";
        return `${arrow} ${Math.abs(change).toFixed(1)}%`;
    },
});

/**
 * ODOO.YOY(current, last_year)
 * Year-over-year comparison as percentage.
 */
functionRegistry.add("ODOO.YOY", {
    description: _t("Year-over-year growth percentage."),
    args: [
        arg("current (number)", _t("Current year value.")),
        arg("last_year (number)", _t("Last year value.")),
    ],
    returns: ["NUMBER"],
    compute: function (current, lastYear) {
        const curr = toNumber(current);
        const prev = toNumber(lastYear);
        if (prev === 0) return 0;
        return ((curr - prev) / Math.abs(prev)) * 100;
    },
});
