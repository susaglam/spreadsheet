import * as spreadsheet from "@odoo/o-spreadsheet";
import {describe, expect, test} from "@odoo/hoot";
import {createModelWithDataSource} from "@spreadsheet/../tests/helpers/model";
import {defineSpreadsheetModels} from "@spreadsheet/../tests/helpers/data";
import {getEvaluatedCell} from "@spreadsheet/../tests/helpers/getters";
import {setCellContent} from "@spreadsheet/../tests/helpers/commands";

const {DEFAULT_LOCALE} = spreadsheet.constants;

describe.current.tags("headless");
defineSpreadsheetModels();

// Same sample as the "Forecast Examples" help spreadsheet: month numbers in
// column A, sales in column B. Least-squares fit: y = 28 * x + 68.
const MONTHLY_SALES = {
    A1: "1",
    A2: "2",
    A3: "3",
    A4: "4",
    A5: "5",
    B1: "100",
    B2: "120",
    B3: "150",
    B4: "180",
    B5: "210",
};

// Decimal comma, dot thousands separator, ";" between formula arguments.
const GERMAN_LOCALE = {
    ...DEFAULT_LOCALE,
    name: "German",
    code: "de_DE",
    decimalSeparator: ",",
    thousandsSeparator: ".",
    formulaArgSeparator: ";",
};

async function createForecastModel(cells, locale = undefined) {
    const {model} = await createModelWithDataSource();
    if (locale) {
        model.dispatch("UPDATE_LOCALE", {locale});
    }
    for (const [xc, content] of Object.entries(cells)) {
        setCellContent(model, xc, content);
    }
    return model;
}

function expectNumber(model, xc, expected) {
    const cell = getEvaluatedCell(model, xc);
    expect(cell.type).toBe("number", {message: `${xc}: ${cell.message}`});
    expect(cell.value).toBeCloseTo(expected, {margin: 1e-9});
}

function expectError(model, xc, message, value = "#ERROR") {
    const cell = getEvaluatedCell(model, xc);
    expect(cell.type).toBe("error");
    expect(cell.value).toBe(value);
    if (message !== undefined) {
        expect(cell.message).toBe(message);
    }
}

describe("ODOO.FORECAST", () => {
    test("predicts y from a linear regression of the known points", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.FORECAST(6,B1:B5,A1:A5)",
            C2: "=ODOO.FORECAST(12,B1:B5,A1:A5)",
        });
        expectNumber(model, "C1", 236);
        expectNumber(model, "C2", 404);
    });

    test("skips blank and text rows without breaking the x/y pairing", async () => {
        // Row 3 has a text x, row 4 a blank y: both rows are dropped as a
        // whole. The remaining pairs lie exactly on y = 10 * x.
        const model = await createForecastModel({
            A1: "1",
            A2: "2",
            A3: "skip",
            A4: "4",
            A5: "5",
            A6: "6",
            B1: "10",
            B2: "20",
            B3: "30",
            B5: "50",
            B6: "60",
            C1: "=ODOO.FORECAST(10,B1:B6,A1:A6)",
        });
        expectNumber(model, "C1", 100);
    });

    test("rejects ranges of different sizes", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.FORECAST(6,B1:B4,A1:A5)",
        });
        expectError(
            model,
            "C1",
            "ODOO.FORECAST: known_x has 5 cells but known_y has 4. Select two ranges of the same size so every x value is paired with its y value."
        );
    });

    test("needs at least two numeric pairs", async () => {
        const model = await createForecastModel({
            A1: "1",
            A2: "2",
            B1: "10",
            B2: "text",
            C1: "=ODOO.FORECAST(3,B1:B2,A1:A2)",
        });
        expectError(
            model,
            "C1",
            "ODOO.FORECAST needs at least 2 rows where both known_x and known_y are numbers. Blank and non-numeric cells are skipped."
        );
    });

    test("explains identical x values", async () => {
        const model = await createForecastModel({
            A1: "3",
            A2: "3",
            B1: "10",
            B2: "20",
            C1: "=ODOO.FORECAST(4,B1:B2,A1:A2)",
        });
        expectError(
            model,
            "C1",
            "ODOO.FORECAST cannot fit a trend line because all known_x values are identical. Use at least two different x values."
        );
    });

    test("non-numeric target_x is a spreadsheet error, not a crash", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: '=ODOO.FORECAST("abc",B1:B5,A1:A5)',
        });
        expectError(
            model,
            "C1",
            "The function ODOO.FORECAST expects a number value, but 'abc' is a string, and cannot be coerced to a number."
        );
    });

    test("propagates an error found in the known data", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            B3: "=1/0",
            C1: "=ODOO.FORECAST(6,B1:B5,A1:A5)",
        });
        expectError(model, "C1", undefined, "#DIV/0!");
    });
});

describe("ODOO.TREND", () => {
    test("returns the trend line value at new_x", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.TREND(B1:B5,A1:A5,10)",
            C2: "=ODOO.TREND(B1:B5,A1:A5,15)",
        });
        expectNumber(model, "C1", 348);
        expectNumber(model, "C2", 488);
    });

    test("returns the average of known_y when every x is identical", async () => {
        const model = await createForecastModel({
            A1: "2",
            A2: "2",
            A3: "2",
            B1: "1",
            B2: "2",
            B3: "6",
            C1: "=ODOO.TREND(B1:B3,A1:A3,5)",
        });
        expectNumber(model, "C1", 3);
    });

    test("rejects ranges of different sizes and too few points", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.TREND(B1:B5,A1:A3,10)",
            C2: "=ODOO.TREND(B1:B1,A1:A1,10)",
        });
        expectError(
            model,
            "C1",
            "ODOO.TREND: known_x has 3 cells but known_y has 5. Select two ranges of the same size so every x value is paired with its y value."
        );
        expectError(
            model,
            "C2",
            "ODOO.TREND needs at least 2 rows where both known_x and known_y are numbers. Blank and non-numeric cells are skipped."
        );
    });
});

describe("ODOO.MOVING_AVG", () => {
    test("averages the last `window` values", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.MOVING_AVG(B1:B5,3)",
            C2: "=ODOO.MOVING_AVG(B1:B5,5)",
            C3: "=ODOO.MOVING_AVG(B1:B5,50)",
            C4: "=ODOO.MOVING_AVG(B1:B5,2.9)",
        });
        expectNumber(model, "C1", 180);
        expectNumber(model, "C2", 152);
        // A window larger than the data averages everything.
        expectNumber(model, "C3", 152);
        // Fractional windows are truncated.
        expectNumber(model, "C4", 195);
    });

    test("skips blank cells instead of counting them as zero", async () => {
        // Open-ended range: B6:B10 are still empty (future months).
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.MOVING_AVG(B1:B10,3)",
        });
        expectNumber(model, "C1", 180);
    });

    test("rejects a window smaller than 1", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            C1: "=ODOO.MOVING_AVG(B1:B5,0)",
        });
        expectError(
            model,
            "C1",
            "ODOO.MOVING_AVG expects a window of at least 1, but got 0."
        );
    });

    test("needs at least one numeric value", async () => {
        const model = await createForecastModel({
            B1: "text",
            C1: "=ODOO.MOVING_AVG(B1:B3,2)",
        });
        expectError(
            model,
            "C1",
            "ODOO.MOVING_AVG needs at least one numeric value in the range. Blank and non-numeric cells are skipped."
        );
    });

    test("propagates an error found in the values", async () => {
        const model = await createForecastModel({
            ...MONTHLY_SALES,
            B5: "=1/0",
            C1: "=ODOO.MOVING_AVG(B1:B5,3)",
        });
        expectError(model, "C1", undefined, "#DIV/0!");
    });
});

describe("locale", () => {
    // "10,5" is not a number for the en_US literal parser, so these cells
    // are stored as text. Their meaning depends on the spreadsheet locale.
    const DECIMAL_COMMA_DATA = {
        A1: "1",
        A2: "2",
        A3: "3",
        B1: "10,5",
        B2: "20,5",
        B3: "30,5",
        C1: '=ODOO.FORECAST("4,5",B1:B3,A1:A3)',
        C2: '=ODOO.TREND(B1:B3,A1:A3,"4,5")',
        C3: '=ODOO.MOVING_AVG(B1:B3,"2")',
    };

    test("decimal comma text is parsed with the spreadsheet locale", async () => {
        const model = await createForecastModel(DECIMAL_COMMA_DATA, GERMAN_LOCALE);
        // Y = 10 * x + 0.5
        expectNumber(model, "C1", 45.5);
        expectNumber(model, "C2", 45.5);
        expectNumber(model, "C3", 25.5);
    });

    test("the same text is not a number in an en_US spreadsheet", async () => {
        const model = await createForecastModel(DECIMAL_COMMA_DATA);
        expectError(model, "C1");
        expectError(
            model,
            "C3",
            "ODOO.MOVING_AVG needs at least one numeric value in the range. Blank and non-numeric cells are skipped."
        );
    });
});
