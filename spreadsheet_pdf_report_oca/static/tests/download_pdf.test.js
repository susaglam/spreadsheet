import {describe, expect, test} from "@odoo/hoot";
import * as spreadsheet from "@odoo/o-spreadsheet";
import {
    addColumns,
    addRows,
    createSheet,
    setCellContent,
    setCellFormat,
    setCellStyle,
} from "@spreadsheet/../tests/helpers/commands";
import {createModelWithDataSource} from "@spreadsheet/../tests/helpers/model";
import {defineSpreadsheetModels} from "@spreadsheet/../tests/helpers/data";
import {
    PDFExportTooLargeError,
    extractPDFData,
    toPdfColor,
} from "@spreadsheet_pdf_report_oca/spreadsheet/bundle/download_pdf.esm";

const {toZone} = spreadsheet.helpers;

describe.current.tags("headless");
defineSpreadsheetModels();

// Same grammar as normalize_color() in controllers/main.py: anything the
// client sends outside of it makes the server refuse the whole export.
const SERVER_COLOR_RE =
    /^(?:#(?:[0-9a-f]{3}|[0-9a-f]{6})|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)|rgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*(?:\d(?:\.\d+)?|\.\d+)\s*\))$/i;

test("displayed styles, fills and alignment reach the PDF payload", async () => {
    const {model} = await createModelWithDataSource();
    setCellContent(model, "A1", "Title");
    setCellStyle(model, "A1", {
        bold: true,
        italic: true,
        textColor: "#00FF00",
        fillColor: "#FF0000",
        fontSize: 14,
    });
    // A date is a number cell with a date format (no "date" type in 19.4).
    setCellContent(model, "B1", "45000");
    setCellFormat(model, "B1", "m/d/yyyy");
    setCellContent(model, "C1", "centered");
    setCellStyle(model, "C1", {align: "center"});

    const data = extractPDFData(model.getters, "Report");
    expect(data.name).toBe("Report");
    const [a1, b1, c1] = data.sheets[0].rows[0];
    expect(a1).toEqual({
        value: "Title",
        bold: true,
        italic: true,
        color: "#00FF00",
        bg: "#FF0000",
        fontSize: 14,
    });
    expect(b1.align).toBe("right");
    expect(c1.align).toBe("center");
});

test("font sizes are clamped to the server bounds", async () => {
    const {model} = await createModelWithDataSource();
    setCellContent(model, "A1", "huge");
    setCellStyle(model, "A1", {fontSize: 1000});
    const [a1] = extractPDFData(model.getters, "Report").sheets[0].rows[0];
    expect(a1.fontSize).toBe(400);
});

test("colours are sent in the grammar the server accepts", () => {
    for (const color of [
        "#abc",
        "#A1B2C3",
        "rgb(1, 2, 3)",
        "rgba(10, 20, 30, 0.5)",
        "light-dark(#111111, #eeeeee)",
    ]) {
        expect(toPdfColor(color)).toMatch(SERVER_COLOR_RE);
    }
    expect(toPdfColor("light-dark(#111111, #eeeeee)")).toBe("#111111");
    expect(toPdfColor("red;background-image:url(http://10.0.0.5/)")).toBe(undefined);
    expect(toPdfColor("")).toBe(undefined);
});

test("merges become spans and hidden sheets are left out", async () => {
    const {model} = await createModelWithDataSource();
    const sheetId = model.getters.getActiveSheetId();
    setCellContent(model, "A1", "merged");
    setCellContent(model, "C2", "last");
    model.dispatch("ADD_MERGE", {sheetId, target: [toZone("A1:B2")]});
    createSheet(model, {sheetId: "pdf_hidden_sheet", name: "Hidden"});
    setCellContent(model, "A1", "secret", "pdf_hidden_sheet");
    model.dispatch("HIDE_SHEET", {sheetId: "pdf_hidden_sheet"});

    const data = extractPDFData(model.getters, "Report");
    expect(data.sheets.map((sheet) => sheet.name)).toEqual([
        model.getters.getSheetName(sheetId),
    ]);
    const rows = data.sheets[0].rows;
    expect(rows[0]).toEqual([{value: "merged", colspan: 2, rowspan: 2}, {value: ""}]);
    // A2 and B2 are covered by the merge: only C2 is sent for row 2.
    expect(rows[1]).toEqual([{value: "last"}]);
});

test("exports above the server cell limit are stopped before the upload", async () => {
    const {model} = await createModelWithDataSource();
    // Grow the sheet to 200 columns x 1000 rows and use its last cell: the
    // used range is 200,000 cells, above the 50,000 the server accepts.
    addColumns(model, "after", "Z", 174);
    addRows(model, "after", 99, 900);
    setCellContent(model, "GR1000", "far away");
    expect(() => extractPDFData(model.getters, "Report")).toThrow(
        PDFExportTooLargeError
    );
});
