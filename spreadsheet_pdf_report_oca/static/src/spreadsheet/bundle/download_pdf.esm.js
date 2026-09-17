/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {useSubEnv} from "@odoo/owl";
import {SpreadsheetRenderer} from "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {waitForDataLoaded} from "@spreadsheet/helpers/model";
import {download} from "@web/core/network/download";

const {topbarMenuRegistry} = spreadsheet.registries;
const {colorToRGBA, isDateTimeFormat, rgbaToHex} = spreadsheet.helpers;

// Must match the limits enforced by the server (controllers/main.py).
/** MAX_CELLS_PER_ROW */
export const MAX_SCAN_COLS = 200;
/** MAX_ROWS_PER_SHEET */
export const MAX_SCAN_ROWS = 1000;
/** MAX_TOTAL_CELLS: table slots over all exported sheets */
export const MAX_TOTAL_CELLS = 50000;
/** MIN_FONT_SIZE / MAX_FONT_SIZE, same bounds as the o-spreadsheet editor */
export const MIN_FONT_SIZE = 1;
export const MAX_FONT_SIZE = 400;

const ALIGNMENTS = new Set(["left", "center", "right"]);
// 19.4 styles may hold "light-dark(<light>, <dark>)"; a PDF is printed light.
const LIGHT_DARK_RE = /^light-dark\(\s*(rgba?\([0-9.,\s]+\)|#[a-f0-9]+)\s*,/i;

/**
 * Raised by extractPDFData when the used ranges exceed MAX_TOTAL_CELLS, so
 * the user gets an explanation before megabytes are uploaded for nothing.
 */
export class PDFExportTooLargeError extends Error {
    constructor(cellCount, limit) {
        super(`Spreadsheet PDF export has ${cellCount} cells (limit ${limit})`);
        this.name = "PDFExportTooLargeError";
        this.cellCount = cellCount;
        this.limit = limit;
    }
}

/**
 * Convert an o-spreadsheet colour to the strict grammar the server accepts
 * (#RRGGBB or rgba(r, g, b, a)). Unknown values are dropped rather than sent:
 * the server refuses anything else to prevent CSS injection.
 *
 * @param {String} color
 * @returns {String|undefined}
 */
export function toPdfColor(color) {
    if (!color || typeof color !== "string") {
        return undefined;
    }
    const lightDark = color.trim().match(LIGHT_DARK_RE);
    try {
        const {r, g, b, a} = colorToRGBA(lightDark ? lightDark[1] : color.trim());
        if (a >= 1) {
            return rgbaToHex({r, g, b, a: 1});
        }
        return `rgba(${r}, ${g}, ${b}, ${a})`;
    } catch {
        return undefined;
    }
}

/**
 * Horizontal alignment as the grid shows it. An explicit alignment wins;
 * "default" (or none) falls back to the evaluated cell's default alignment:
 * numbers and date-times right, booleans and errors centered. In 19.4 a date
 * is a number cell whose format is a date-time format (there is no "date"
 * cell type). A default "left" is omitted because it is the PDF default.
 *
 * @returns {String|undefined}
 */
export function getPDFAlignment(style, evaluatedCell) {
    if (ALIGNMENTS.has(style.align)) {
        return style.align;
    }
    let align = evaluatedCell.defaultAlign;
    if (!align) {
        const isNumber = evaluatedCell.type === "number";
        const isDateTime =
            isNumber &&
            Boolean(evaluatedCell.format) &&
            isDateTimeFormat(evaluatedCell.format);
        align = isNumber || isDateTime ? "right" : undefined;
    }
    return ALIGNMENTS.has(align) && align !== "left" ? align : undefined;
}

/**
 * Find the last row and column that contain data (within the scan limits).
 *
 * @returns {{maxCol: Number, maxRow: Number}} -1 when the sheet is empty
 */
export function getUsedRange(getters, sheetId) {
    const scanCols = Math.min(getters.getNumberCols(sheetId), MAX_SCAN_COLS);
    const scanRows = Math.min(getters.getNumberRows(sheetId), MAX_SCAN_ROWS);
    let maxCol = -1;
    let maxRow = -1;
    for (let row = 0; row < scanRows; row++) {
        for (let col = 0; col < scanCols; col++) {
            const cell = getters.getEvaluatedCell({sheetId, col, row});
            if (cell.type !== "empty") {
                if (col > maxCol) maxCol = col;
                if (row > maxRow) maxRow = row;
            }
        }
    }
    return {maxCol, maxRow};
}

/**
 * Collect merge information for the used range.
 * Returns:
 *   - spans: Map of "col,row" -> {colspan, rowspan} for top-left cells of merges
 *   - hidden: Set of "col,row" strings for cells hidden by merges
 * Spans are clipped to the used range: a merge reaching past the last
 * exported row/column would otherwise stretch the PDF table.
 */
export function collectMerges(getters, sheetId, maxCol, maxRow) {
    const spans = new Map();
    const hidden = new Set();
    for (let row = 0; row <= maxRow; row++) {
        for (let col = 0; col <= maxCol; col++) {
            const merge = getters.getMerge({sheetId, col, row});
            if (!merge) continue;
            if (col === merge.left && row === merge.top) {
                const colspan = Math.min(merge.right, maxCol) - merge.left + 1;
                const rowspan = Math.min(merge.bottom, maxRow) - merge.top + 1;
                if (colspan > 1 || rowspan > 1) {
                    spans.set(`${col},${row}`, {colspan, rowspan});
                }
            } else {
                hidden.add(`${col},${row}`);
            }
        }
    }
    return {spans, hidden};
}

/**
 * Build the JSON payload of /spreadsheet/pdf: evaluated values and displayed
 * styles of the used range of every visible sheet.
 *
 * @param {Object} getters o-spreadsheet model getters
 * @param {String} name report (spreadsheet) name
 * @param {Date} [today]
 * @throws {PDFExportTooLargeError} when the export exceeds MAX_TOTAL_CELLS
 */
export function extractPDFData(getters, name, today = new Date()) {
    // Hidden sheets are left out, like when the spreadsheet is displayed.
    const ranges = getters.getVisibleSheetIds().map((sheetId) => ({
        sheetId,
        ...getUsedRange(getters, sheetId),
    }));
    // Every slot of the used rectangle becomes one PDF table slot (a merge
    // covers exactly the slots of its hidden cells): same count as the server.
    const cellCount = ranges.reduce(
        (total, {maxCol, maxRow}) =>
            maxCol < 0 || maxRow < 0 ? total : total + (maxCol + 1) * (maxRow + 1),
        0
    );
    if (cellCount > MAX_TOTAL_CELLS) {
        throw new PDFExportTooLargeError(cellCount, MAX_TOTAL_CELLS);
    }

    const sheets = [];
    for (const {sheetId, maxCol, maxRow} of ranges) {
        const sheetName = getters.getSheetName(sheetId);
        if (maxCol < 0 || maxRow < 0) {
            sheets.push({name: sheetName, rows: []});
            continue;
        }
        const merges = collectMerges(getters, sheetId, maxCol, maxRow);
        const rows = [];
        for (let row = 0; row <= maxRow; row++) {
            const rowCells = [];
            for (let col = 0; col <= maxCol; col++) {
                const mergeKey = `${col},${row}`;
                // Skip cells that are part of a merge but not the top-left
                if (merges.hidden.has(mergeKey)) {
                    continue;
                }
                const pos = {sheetId, col, row};
                const evaluatedCell = getters.getEvaluatedCell(pos);
                const cell = {value: evaluatedCell.formattedValue || ""};

                // 19.4 evaluated cells carry no style: the computed style
                // merges cell style, table style and conditional formats,
                // i.e. what the grid displays.
                const style = getters.getCellComputedStyle(pos) || {};
                if (style.bold) cell.bold = true;
                if (style.italic) cell.italic = true;
                const textColor = toPdfColor(style.textColor);
                if (textColor) cell.color = textColor;
                const fillColor = toPdfColor(style.fillColor);
                if (fillColor) cell.bg = fillColor;
                if (Number.isFinite(style.fontSize) && style.fontSize > 0) {
                    cell.fontSize = Math.min(
                        Math.max(style.fontSize, MIN_FONT_SIZE),
                        MAX_FONT_SIZE
                    );
                }
                const align = getPDFAlignment(style, evaluatedCell);
                if (align) cell.align = align;

                const mergeInfo = merges.spans.get(mergeKey);
                if (mergeInfo?.colspan > 1) cell.colspan = mergeInfo.colspan;
                if (mergeInfo?.rowspan > 1) cell.rowspan = mergeInfo.rowspan;
                rowCells.push(cell);
            }
            rows.push(rowCells);
        }
        sheets.push({name: sheetName, rows});
    }

    return {
        name,
        report_date: today.toLocaleDateString(undefined, {
            year: "numeric",
            month: "long",
            day: "numeric",
        }),
        sheets,
    };
}

topbarMenuRegistry.addChild("download_pdf", ["file"], {
    name: _t("Download PDF"),
    sequence: 25,
    execute: (env) => env.downloadAsPDF(),
    icon: "o-spreadsheet-Icon.PRINT",
});

patch(SpreadsheetRenderer.prototype, {
    setup() {
        super.setup();
        useSubEnv({
            downloadAsPDF: this._downloadAsPDF.bind(this),
        });
    },

    /**
     * Extract evaluated cell data from all visible sheets and trigger the PDF
     * download. `download` posts the CSRF token (odoo.csrf_token) itself.
     */
    async _downloadAsPDF() {
        this.ui.block();
        try {
            await waitForDataLoaded(this.spreadsheet_model);
            let data = null;
            try {
                data = this._extractPDFData();
            } catch (error) {
                if (!(error instanceof PDFExportTooLargeError)) {
                    throw error;
                }
                this.notifications.add(
                    _t(
                        "This spreadsheet has %(count)s cells to print (the used range of every visible sheet), but the PDF export is limited to %(limit)s cells. Very large exports take minutes to render and block the server for other users. Remove unused rows and columns, hide the sheets you do not need in the PDF, or use File > Download XLSX to get the full data.",
                        {count: error.cellCount, limit: error.limit}
                    ),
                    {type: "warning", sticky: true}
                );
                return;
            }
            await download({
                url: "/spreadsheet/pdf",
                data: {data: JSON.stringify(data)},
            });
        } finally {
            this.ui.unblock();
        }
    },

    /**
     * Build the structured JSON payload for the visible sheets.
     */
    _extractPDFData() {
        return extractPDFData(this.spreadsheet_model.getters, this.props.record.name);
    },
});
