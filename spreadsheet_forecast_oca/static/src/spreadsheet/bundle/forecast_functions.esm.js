/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {_t} from "@web/core/l10n/translation";

// In o-spreadsheet, arg lives in spreadsheet.helpers, not registries
const {EvaluationError} = spreadsheet;
const {functionRegistry} = spreadsheet.registries;
const {arg, isEvaluationError, isNumber, toNumber} = spreadsheet.helpers;

// ---------------------------------------------------------------------------
// Helpers (defined before the registrations that use them)
// ---------------------------------------------------------------------------

/**
 * Convert one evaluated range cell to a number.
 *
 * Blank and non-numeric cells become NaN so the callers can skip them. Text
 * that looks like a number is parsed with the spreadsheet locale ("10,5" is
 * 10.5 in a locale whose decimal separator is a comma). An error cell is
 * re-thrown, like core o-spreadsheet functions do, so the formula shows the
 * source error (e.g. "Loading..." while an Odoo pivot loads) instead of
 * silently computing on partial data.
 *
 * @param {Object} cell evaluated cell ({value, format}) or a raw value
 * @param {Object} locale spreadsheet locale
 * @returns {Number}
 */
function cellToNumber(cell, locale) {
    const isCellObject = cell !== null && typeof cell === "object" && "value" in cell;
    const value = isCellObject ? cell.value : cell;
    if (isEvaluationError(value)) {
        throw isCellObject ? cell : new EvaluationError("", value);
    }
    switch (typeof value) {
        case "number":
            return value;
        case "boolean":
            return value ? 1 : 0;
        case "string":
            return isNumber(value, locale) ? toNumber(value, locale) : NaN;
        default:
            // Null / undefined: blank cell
            return NaN;
    }
}

/**
 * Flatten a range (matrix [col][row] of cells) or a single value to a
 * positional array of numbers, NaN for blank / non-numeric cells. Every cell
 * position is kept so that two ranges of the same size stay row-aligned.
 *
 * @param {Array|Object} range
 * @param {Object} locale
 * @returns {Number[]}
 */
function flattenRange(range, locale) {
    if (!Array.isArray(range)) {
        return [cellToNumber(range, locale)];
    }
    const result = [];
    for (const col of range) {
        for (const cell of col) {
            result.push(cellToNumber(cell, locale));
        }
    }
    return result;
}

/**
 * Numeric values of a range, blank and non-numeric cells skipped.
 *
 * @param {Array|Object} range
 * @param {Object} locale
 * @returns {Number[]}
 */
function flattenNumbers(range, locale) {
    return flattenRange(range, locale).filter((n) => !isNaN(n));
}

/**
 * Walk known_x and known_y positionally, keeping only rows where BOTH cells
 * are numeric. A non-numeric cell drops the whole row for both ranges, so the
 * x<->y pairing stays intact and xs.length === ys.length is guaranteed.
 *
 * @param {Array|Object} knownXRange
 * @param {Array|Object} knownYRange
 * @param {Object} locale
 * @returns {{xs: Number[], ys: Number[]}}
 */
function alignedPairs(knownXRange, knownYRange, locale) {
    const rawX = flattenRange(knownXRange, locale);
    const rawY = flattenRange(knownYRange, locale);
    // Mismatched range sizes are a user error, not something to silently
    // truncate to the shorter one (which would mis-pair x<->y).
    if (rawX.length !== rawY.length) {
        throw new EvaluationError(
            _t(
                "[[FUNCTION_NAME]]: known_x has %(x_count)s cells but known_y has %(y_count)s. Select two ranges of the same size so every x value is paired with its y value.",
                {x_count: rawX.length, y_count: rawY.length}
            )
        );
    }
    const xs = [];
    const ys = [];
    for (let i = 0; i < rawX.length; i++) {
        if (!isNaN(rawX[i]) && !isNaN(rawY[i])) {
            xs.push(rawX[i]);
            ys.push(rawY[i]);
        }
    }
    if (xs.length < 2) {
        throw new EvaluationError(
            _t(
                "[[FUNCTION_NAME]] needs at least 2 rows where both known_x and known_y are numbers. Blank and non-numeric cells are skipped."
            )
        );
    }
    return {xs, ys};
}

/**
 * Least-squares straight line through the given points.
 *
 * @param {Number[]} xs
 * @param {Number[]} ys
 * @returns {{slope: Number, intercept: Number}|null} null when every x value
 *     is identical (vertical line: the slope is undefined)
 */
function fitLine(xs, ys) {
    const n = ys.length;
    const sumX = xs.reduce((a, b) => a + b, 0);
    const sumY = ys.reduce((a, b) => a + b, 0);
    const sumXY = xs.reduce((s, xi, i) => s + xi * ys[i], 0);
    const sumX2 = xs.reduce((s, xi) => s + xi * xi, 0);
    const denom = n * sumX2 - sumX * sumX;
    if (denom === 0) {
        return null;
    }
    const slope = (n * sumXY - sumX * sumY) / denom;
    return {slope, intercept: (sumY - slope * sumX) / n};
}

// ---------------------------------------------------------------------------
// Functions
// ---------------------------------------------------------------------------

/**
 * ODOO.FORECAST(target_x, known_y, known_x)
 * Predicts the y value at target_x based on linear regression of known points.
 */
functionRegistry.add("ODOO.FORECAST", {
    description: _t(
        "Predicts the y value at a given x from a least-squares linear regression of known data."
    ),
    args: [
        arg(
            "target_x (number)",
            _t("The x value to predict y for, e.g. the next month number.")
        ),
        arg("known_y (range<number>)", _t("The known values, e.g. past sales.")),
        arg(
            "known_x (range<number>)",
            _t("The x values paired row by row with known_y, e.g. the month numbers.")
        ),
    ],
    returns: ["NUMBER"],
    compute: function (targetX, knownYRange, knownXRange) {
        const x = toNumber(targetX, this.locale);
        const {xs, ys} = alignedPairs(knownXRange, knownYRange, this.locale);
        const line = fitLine(xs, ys);
        if (!line) {
            throw new EvaluationError(
                _t(
                    "[[FUNCTION_NAME]] cannot fit a trend line because all known_x values are identical. Use at least two different x values."
                )
            );
        }
        return line.slope * x + line.intercept;
    },
});

/**
 * ODOO.TREND(known_y, known_x, new_x)
 * Returns the trend value at new_x (the average of known_y when every known_x
 * is identical).
 */
functionRegistry.add("ODOO.TREND", {
    description: _t(
        "Returns the value of the least-squares trend line at a new x. When all known_x values are identical, returns the average of known_y."
    ),
    args: [
        arg("known_y (range<number>)", _t("The known values, e.g. past sales.")),
        arg(
            "known_x (range<number>)",
            _t("The x values paired row by row with known_y, e.g. the month numbers.")
        ),
        arg("new_x (number)", _t("The x value to evaluate the trend line at.")),
    ],
    returns: ["NUMBER"],
    compute: function (knownYRange, knownXRange, newX) {
        const {xs, ys} = alignedPairs(knownXRange, knownYRange, this.locale);
        const x = toNumber(newX, this.locale);
        const line = fitLine(xs, ys);
        if (!line) {
            return ys.reduce((a, b) => a + b, 0) / ys.length;
        }
        return line.slope * x + line.intercept;
    },
});

/**
 * ODOO.MOVING_AVG(values, window)
 * Returns the average of the last `window` numeric values.
 */
functionRegistry.add("ODOO.MOVING_AVG", {
    description: _t(
        "Averages the most recent numeric values of a range (simple moving average)."
    ),
    args: [
        arg(
            "values (range<number>)",
            _t("The values to average. Blank and non-numeric cells are skipped.")
        ),
        arg(
            "window (number)",
            _t(
                "How many of the last values to average, e.g. 3. A window larger than the number of values averages all of them."
            )
        ),
    ],
    returns: ["NUMBER"],
    compute: function (valuesRange, windowSize) {
        const rawWindow = toNumber(windowSize, this.locale);
        const size = Math.trunc(rawWindow);
        if (size < 1) {
            throw new EvaluationError(
                _t(
                    "[[FUNCTION_NAME]] expects a window of at least 1, but got %s.",
                    String(rawWindow)
                )
            );
        }
        const values = flattenNumbers(valuesRange, this.locale);
        if (values.length === 0) {
            throw new EvaluationError(
                _t(
                    "[[FUNCTION_NAME]] needs at least one numeric value in the range. Blank and non-numeric cells are skipped."
                )
            );
        }
        const slice = values.slice(-Math.min(size, values.length));
        return slice.reduce((a, b) => a + b, 0) / slice.length;
    },
});
