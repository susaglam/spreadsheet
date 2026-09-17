/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {_t} from "@web/core/l10n/translation";

// In o-spreadsheet, error classes are top-level exports, arg/formatValue/toNumber live in
// spreadsheet.helpers and functionRegistry in spreadsheet.registries.
// Errors are returned as EvaluationError subclasses (like core DIVIDE): a plain Error
// is reported as "An unexpected error occurred" and logged as a crash.
const {DivisionByZeroError} = spreadsheet;
const {functionRegistry} = spreadsheet.registries;
const {arg, formatValue, toNumber} = spreadsheet.helpers;

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
    category: "Odoo",
    returns: ["NUMBER"],
    compute: function (current, previous) {
        // Text arguments such as "1,5" are parsed with the spreadsheet locale.
        const curr = toNumber(current, this.locale);
        const prev = toNumber(previous, this.locale);
        if (prev === 0) {
            if (curr === 0) return 0;
            return new DivisionByZeroError(
                _t(
                    "[[FUNCTION_NAME]] cannot compute a percentage change because the previous value is 0. Use ODOO.VARIANCE for the absolute difference, or wrap the formula in IFERROR to show a fallback value."
                )
            );
        }
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
    category: "Odoo",
    returns: ["NUMBER"],
    compute: function (current, previous) {
        return toNumber(current, this.locale) - toNumber(previous, this.locale);
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
    category: "Odoo",
    returns: ["STRING"],
    compute: function (current, previous) {
        const curr = toNumber(current, this.locale);
        const prev = toNumber(previous, this.locale);
        if (prev === 0) return "—";
        const change = (curr - prev) / Math.abs(prev);
        const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "—";
        // The percentage uses the spreadsheet decimal separator (▲ 12,5% in nl/tr/de).
        const percentage = formatValue(Math.abs(change), {
            format: "0.0%",
            locale: this.locale,
        });
        return `${arrow} ${percentage}`;
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
    category: "Odoo",
    returns: ["NUMBER"],
    compute: function (current, lastYear) {
        const curr = toNumber(current, this.locale);
        const prev = toNumber(lastYear, this.locale);
        if (prev === 0) {
            if (curr === 0) return 0;
            return new DivisionByZeroError(
                _t(
                    "[[FUNCTION_NAME]] cannot compute a year-over-year change because last year's value is 0. Use ODOO.VARIANCE for the absolute difference, or wrap the formula in IFERROR to show a fallback value."
                )
            );
        }
        return ((curr - prev) / Math.abs(prev)) * 100;
    },
});
