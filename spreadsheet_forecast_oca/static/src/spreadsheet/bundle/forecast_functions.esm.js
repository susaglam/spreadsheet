/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {_t} from "@web/core/l10n/translation";

// o-spreadsheet: arg lives in spreadsheet.helpers, not registries
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
        const {xs, ys} = alignedPairs(knownXRange, knownYRange);

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
        arg("known_x (range<number>)", _t("Known x values.")),
        arg("new_x (number)", _t("New x value to compute trend for.")),
    ],
    returns: ["NUMBER"],
    compute: function (knownYRange, knownXRange, newX) {
        const {xs, ys} = alignedPairs(knownXRange, knownYRange);

        const x = toNumber(newX);
        const n = ys.length;
        if (xs.length !== ys.length || n < 2) {
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
        if (values.length === 0) {
            throw new Error(_t("ODOO.MOVING_AVG needs at least one numeric value."));
        }
        const size = Math.max(1, Math.min(toNumber(windowSize), values.length));
        const slice = values.slice(-size);
        return slice.reduce((a, b) => a + b, 0) / slice.length;
    },
});

function flattenNumbers(range) {
    // saas-19.4 o-spreadsheet: range args are matrices [col][row] of {value, format} cells
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

function flattenRaw(range) {
    // Flatten a range/scalar to a positional array of Numbers (NaN for non-numeric cells),
    // preserving every cell position so paired ranges stay row-aligned.
    const toNum = (cell) => {
        const v =
            cell && typeof cell === "object" && "value" in cell ? cell.value : cell;
        // Empty cells (o-spreadsheet blanks) must be NaN, not Number("")===0,
        // so alignedPairs drops the whole row instead of injecting a fake 0.
        return v === null || v === undefined || v === "" ? NaN : Number(v);
    };
    const result = [];
    if (!Array.isArray(range)) {
        result.push(toNum(range));
        return result;
    }
    for (const col of range) {
        if (Array.isArray(col)) {
            for (const cell of col) {
                result.push(toNum(cell));
            }
        } else {
            result.push(toNum(col));
        }
    }
    return result;
}

function alignedPairs(knownXRange, knownYRange) {
    // Walk known_x and known_y positionally, keeping only rows where BOTH cells are
    // numeric. A non-numeric cell drops the whole row for both ranges, so x<->y pairing
    // stays intact and xs.length === ys.length is guaranteed.
    const rawX = flattenRaw(knownXRange);
    const rawY = flattenRaw(knownYRange);
    // Mismatched range sizes are a user error, not something to silently
    // truncate to the shorter one (which would mis-pair x<->y).
    if (rawX.length !== rawY.length) {
        throw new Error(
            _t("known_x and known_y must contain the same number of cells.")
        );
    }
    const len = rawX.length;
    const xs = [];
    const ys = [];
    for (let i = 0; i < len; i++) {
        if (!isNaN(rawX[i]) && !isNaN(rawY[i])) {
            xs.push(rawX[i]);
            ys.push(rawY[i]);
        }
    }
    return {xs, ys};
}
