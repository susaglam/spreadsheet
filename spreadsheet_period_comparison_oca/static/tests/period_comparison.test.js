import {DEFAULT_LOCALES, registries} from "@odoo/o-spreadsheet";
import {describe, expect, test} from "@odoo/hoot";
import {createModelWithDataSource} from "@spreadsheet/../tests/helpers/model";
import {defineSpreadsheetModels} from "@spreadsheet/../tests/helpers/data";
import {getEvaluatedCell} from "@spreadsheet/../tests/helpers/getters";
import {setCellContent} from "@spreadsheet/../tests/helpers/commands";

describe.current.tags("headless");
defineSpreadsheetModels();

const FUNCTION_NAMES = [
    "ODOO.PERCENT_CHANGE",
    "ODOO.VARIANCE",
    "ODOO.GROWTH_ARROW",
    "ODOO.YOY",
];
const FR_LOCALE = DEFAULT_LOCALES.find((locale) => locale.code === "fr_FR");

/**
 * Evaluate each formula in its own cell of column A.
 *
 * @param {Object} model
 * @param {String[]} formulas
 * @returns {Object[]} evaluated cells, in the order of the formulas
 */
function evaluate(model, formulas) {
    formulas.forEach((formula, index) =>
        setCellContent(model, `A${index + 1}`, formula)
    );
    return formulas.map((formula, index) => getEvaluatedCell(model, `A${index + 1}`));
}

function values(model, formulas) {
    return evaluate(model, formulas).map((cell) => cell.value);
}

/**
 * A handled error is a spreadsheet error with a teaching message, never the
 * generic "unexpected error" o-spreadsheet shows for crashing functions.
 *
 * @param {Object} cell
 * @param {String} errorValue
 */
function expectHandledError(cell, errorValue) {
    expect(cell.value).toBe(errorValue);
    expect(cell.message).not.toInclude("unexpected error");
    expect(cell.message).not.toInclude("[[FUNCTION_NAME]]");
}

test("all functions are registered in the Odoo category", () => {
    const {functionRegistry} = registries;
    for (const name of FUNCTION_NAMES) {
        const definition = functionRegistry.get(name);
        expect(definition.category).toBe("Odoo");
        expect(definition.args.length).toBe(2);
    }
});

test("ODOO.PERCENT_CHANGE computes the relative change in percent", async () => {
    const {model} = await createModelWithDataSource();
    expect(
        values(model, [
            "=ODOO.PERCENT_CHANGE(1500, 1200)",
            "=ODOO.PERCENT_CHANGE(900, 1200)",
            "=ODOO.PERCENT_CHANGE(1200, 1200)",
            // A negative base: -100 -> -50 is an improvement.
            "=ODOO.PERCENT_CHANGE(-50, -100)",
            "=ODOO.PERCENT_CHANGE(0, 0)",
            "=ODOO.PERCENT_CHANGE(B1, B2)",
        ])
    ).toEqual([25, -25, 0, 50, 0, 0]);
});

test("ODOO.PERCENT_CHANGE from a zero previous value is #DIV/0!", async () => {
    const {model} = await createModelWithDataSource();
    const [cell] = evaluate(model, ["=ODOO.PERCENT_CHANGE(5, 0)"]);
    expectHandledError(cell, "#DIV/0!");
    expect(cell.message).toInclude("ODOO.PERCENT_CHANGE");
    expect(cell.message).toInclude("previous value is 0");
    expect(cell.message).toInclude("IFERROR");
    const [fallback] = evaluate(model, ['=IFERROR(ODOO.PERCENT_CHANGE(5, 0), "n/a")']);
    expect(fallback.value).toBe("n/a");
});

test("ODOO.YOY computes the year-over-year change in percent", async () => {
    const {model} = await createModelWithDataSource();
    expect(
        values(model, [
            "=ODOO.YOY(1500, 1200)",
            "=ODOO.YOY(900, 1200)",
            "=ODOO.YOY(-50, -100)",
            "=ODOO.YOY(0, 0)",
        ])
    ).toEqual([25, -25, 50, 0]);
});

test("ODOO.YOY from a zero last-year value is #DIV/0!", async () => {
    const {model} = await createModelWithDataSource();
    const [cell] = evaluate(model, ["=ODOO.YOY(5, 0)"]);
    expectHandledError(cell, "#DIV/0!");
    expect(cell.message).toInclude("ODOO.YOY");
    expect(cell.message).toInclude("last year's value is 0");
});

test("ODOO.VARIANCE computes the absolute difference", async () => {
    const {model} = await createModelWithDataSource();
    expect(
        values(model, [
            "=ODOO.VARIANCE(1500, 1200)",
            "=ODOO.VARIANCE(1200, 1500)",
            "=ODOO.VARIANCE(B1, B2)",
            '=ODOO.VARIANCE("12", "10")',
            "=ODOO.VARIANCE(TRUE, FALSE)",
        ])
    ).toEqual([300, -300, 0, 2, 1]);
});

test("ODOO.GROWTH_ARROW shows the direction and the percentage", async () => {
    const {model} = await createModelWithDataSource();
    expect(
        values(model, [
            "=ODOO.GROWTH_ARROW(1500, 1200)",
            "=ODOO.GROWTH_ARROW(1200, 1500)",
            "=ODOO.GROWTH_ARROW(1200, 1200)",
            "=ODOO.GROWTH_ARROW(1125, 1000)",
            "=ODOO.GROWTH_ARROW(-50, -100)",
            // No previous value: no direction, and no error in the dashboard.
            "=ODOO.GROWTH_ARROW(5, 0)",
        ])
    ).toEqual(["▲ 25.0%", "▼ 20.0%", "— 0.0%", "▲ 12.5%", "▲ 50.0%", "—"]);
});

test("invalid arguments give a spreadsheet error, not a crash", async () => {
    const {model} = await createModelWithDataSource();
    const cells = evaluate(model, [
        '=ODOO.PERCENT_CHANGE("abc", 1)',
        '=ODOO.VARIANCE(1, "abc")',
        '=ODOO.GROWTH_ARROW("abc", 1)',
        '=ODOO.YOY(1, "abc")',
    ]);
    for (const cell of cells) {
        expectHandledError(cell, "#ERROR");
        expect(cell.message).toInclude("'abc'");
    }
    // Errors of the arguments are propagated unchanged.
    const [propagated] = evaluate(model, ["=ODOO.VARIANCE(1/0, 1)"]);
    expectHandledError(propagated, "#DIV/0!");
});

test("text arguments are parsed with the spreadsheet locale", async () => {
    const {model} = await createModelWithDataSource();
    // En_US: the comma is a thousands separator, "1,5" is not a number.
    const [enComma, enThousands, enDate] = evaluate(model, [
        '=ODOO.VARIANCE("1,5", "1")',
        '=ODOO.VARIANCE("1,500", "500")',
        '=ODOO.VARIANCE("1/15/2024", "1/14/2024")',
    ]);
    expectHandledError(enComma, "#ERROR");
    expect(enThousands.value).toBe(1000);
    expect(enDate.value).toBe(1);

    model.dispatch("UPDATE_LOCALE", {locale: FR_LOCALE});
    expect(model.getters.getLocale().decimalSeparator).toBe(",");
    expect(
        values(model, [
            '=ODOO.VARIANCE("1,5", "1")',
            '=ODOO.PERCENT_CHANGE("1,5", "1")',
            '=ODOO.YOY("2,5", "2")',
            '=ODOO.VARIANCE("15/01/2024", "14/01/2024")',
            '=ODOO.GROWTH_ARROW("1125", "1000")',
        ])
    ).toEqual([0.5, 50, 25, 1, "▲ 12,5%"]);
});
