/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {_t} from "@web/core/l10n/translation";

// Saas-19.2: arg is in spreadsheet.helpers, not registries
const {functionRegistry} = spreadsheet.registries;
const {arg, toNumber} = spreadsheet.helpers;

/**
 * Simple linear regression forecast.
 * ODOO.FORECAST(target_x, known_y, known_x)
 * Predicts the y value at target_x based on linear regression of known points.
 */
functionRegistry.add("ODOO.FORECAST", {
    description: _t("Forecast future value using linear regression."),
    args: [
        arg("target_x (number)", _t("The x value to predict y for.")),
        arg("known_y (range<number>)", _t("Known y values.")),
        arg("known_x (range<number>)", _t("Known x values.")),
    ],
    returns: ["NUMBER"],
    compute: function (targetX, knownYRange, knownXRange) {
        const x = toNumber(targetX);
        const ys = flattenNumbers(knownYRange);
        const xs = flattenNumbers(knownXRange);

        if (ys.length !== xs.length || ys.length < 2) {
            throw new Error(_t("Known x and y must have the same non-empty length."));
        }

        const n = ys.length;
        const sumX = xs.reduce((a, b) => a + b, 0);
        const sumY = ys.reduce((a, b) => a + b, 0);
        const sumXY = xs.reduce((s, xi, i) => s + xi * ys[i], 0);
        const sumX2 = xs.reduce((s, xi) => s + xi * xi, 0);

        const denom = n * sumX2 - sumX * sumX;
        if (denom === 0) {
            throw new Error(_t("Cannot compute forecast: x values are identical."));
        }

        const slope = (n * sumXY - sumX * sumY) / denom;
        const intercept = (sumY - slope * sumX) / n;
        return slope * x + intercept;
    },
});

/**
 * ODOO.TREND(known_y, known_x, new_x)
 * Returns the trend value at new_x.
 */
functionRegistry.add("ODOO.TREND", {
    description: _t("Compute trend value using linear regression."),
    args: [
        arg("known_y (range<number>)", _t("Known y values.")),
        arg("known_x (range<number>)", _t("Known x values (optional).")),
        arg("new_x (number)", _t("New x value to compute trend for.")),
    ],
    returns: ["NUMBER"],
    compute: function (knownYRange, knownXRange, newX) {
        const ys = flattenNumbers(knownYRange);
        let xs;
        if (knownXRange === undefined || knownXRange === null) {
            xs = ys.map((_, i) => i + 1);
        } else {
            xs = flattenNumbers(knownXRange);
        }

        const x = toNumber(newX);
        const n = ys.length;
        if (n < 2) {
            throw new Error(_t("Need at least 2 data points."));
        }

        const sumX = xs.reduce((a, b) => a + b, 0);
        const sumY = ys.reduce((a, b) => a + b, 0);
        const sumXY = xs.reduce((s, xi, i) => s + xi * ys[i], 0);
        const sumX2 = xs.reduce((s, xi) => s + xi * xi, 0);

        const denom = n * sumX2 - sumX * sumX;
        if (denom === 0) return sumY / n;

        const slope = (n * sumXY - sumX * sumY) / denom;
        const intercept = (sumY - slope * sumX) / n;
        return slope * x + intercept;
    },
});

/**
 * ODOO.MOVING_AVG(range, window)
 * Returns the moving average of the last `window` values.
 */
functionRegistry.add("ODOO.MOVING_AVG", {
    description: _t("Simple moving average over a window of values."),
    args: [
        arg("values (range<number>)", _t("Numeric values.")),
        arg("window (number)", _t("Window size.")),
    ],
    returns: ["NUMBER"],
    compute: function (valuesRange, windowSize) {
        const values = flattenNumbers(valuesRange);
        const size = Math.max(1, Math.min(toNumber(windowSize), values.length));
        const slice = values.slice(-size);
        return slice.reduce((a, b) => a + b, 0) / slice.length;
    },
});

function flattenNumbers(range) {
    // Saas-19.2 o-spreadsheet: range args are matrices [col][row] of {value, format} cells
    const result = [];
    if (!Array.isArray(range)) {
        // Single scalar or a single cell-like {value}
        const v =
            range && typeof range === "object" && "value" in range
                ? range.value
                : range;
        const n = Number(v);
        if (!isNaN(n)) result.push(n);
        return result;
    }
    for (const col of range) {
        if (Array.isArray(col)) {
            for (const cell of col) {
                const v =
                    cell && typeof cell === "object" && "value" in cell
                        ? cell.value
                        : cell;
                const n = Number(v);
                if (!isNaN(n)) result.push(n);
            }
        } else {
            const v =
                col && typeof col === "object" && "value" in col ? col.value : col;
            const n = Number(v);
            if (!isNaN(n)) result.push(n);
        }
    }
    return result;
}
