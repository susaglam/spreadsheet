/** @odoo-module **/

import * as spreadsheet from "@odoo/o-spreadsheet";
import {useSubEnv} from "@odoo/owl";
import {SpreadsheetRenderer} from "@spreadsheet_oca/spreadsheet/bundle/spreadsheet_renderer.esm";
import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";
import {waitForDataLoaded} from "@spreadsheet/helpers/model";
import {download} from "@web/core/network/download";

const {topbarMenuRegistry} = spreadsheet.registries;

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
     * Extract evaluated cell data from all sheets and trigger PDF download.
     */
    async _downloadAsPDF() {
        this.ui.block();
        try {
            await waitForDataLoaded(this.spreadsheet_model);
            const data = this._extractPDFData();
            await download({
                url: "/spreadsheet/pdf",
                data: {data: JSON.stringify(data)},
            });
        } finally {
            this.ui.unblock();
        }
    },

    /**
     * Build a structured JSON payload with evaluated cell values for all sheets.
     * Only the "used range" (non-empty cells) is included.
     */
    _extractPDFData() {
        const getters = this.spreadsheet_model.getters;
        const sheetIds = getters.getSheetIds();
        const today = new Date();
        const reportDate = today.toLocaleDateString(undefined, {
            year: "numeric",
            month: "long",
            day: "numeric",
        });

        const sheets = [];
        for (const sheetId of sheetIds) {
            const sheetName = getters.getSheetName(sheetId);
            const {maxCol, maxRow} = this._getUsedRange(sheetId);

            if (maxCol < 0 || maxRow < 0) {
                sheets.push({name: sheetName, rows: []});
                continue;
            }

            // Collect merge info for this sheet
            const merges = this._collectMerges(sheetId, maxCol, maxRow);

            // Build row-by-row grid
            const rows = [];
            for (let row = 0; row <= maxRow; row++) {
                const rowCells = [];
                for (let col = 0; col <= maxCol; col++) {
                    const pos = {sheetId, col, row};

                    // Skip cells that are part of a merge but not the top-left
                    const mergeKey = `${col},${row}`;
                    if (merges.hidden.has(mergeKey)) {
                        continue;
                    }

                    const evaluatedCell = getters.getEvaluatedCell(pos);
                    const cell = {
                        value: evaluatedCell.formattedValue || "",
                    };

                    // Style info
                    const style = evaluatedCell.style || {};
                    if (style.bold) cell.bold = true;
                    if (style.italic) cell.italic = true;
                    if (style.textColor) cell.color = style.textColor;
                    if (style.fillColor) cell.bg = style.fillColor;
                    if (style.fontSize) cell.fontSize = style.fontSize;
                    if (style.align) {
                        cell.align = style.align;
                    } else if (
                        evaluatedCell.type === "number" ||
                        evaluatedCell.type === "date"
                    ) {
                        cell.align = "right";
                    }

                    // Merge info (colspan/rowspan)
                    const mergeInfo = merges.spans.get(mergeKey);
                    if (mergeInfo) {
                        if (mergeInfo.colspan > 1) cell.colspan = mergeInfo.colspan;
                        if (mergeInfo.rowspan > 1) cell.rowspan = mergeInfo.rowspan;
                    }

                    rowCells.push(cell);
                }
                rows.push(rowCells);
            }
            sheets.push({name: sheetName, rows});
        }

        return {
            name: this.props.record.name,
            report_date: reportDate,
            sheets,
        };
    },

    /**
     * Find the last row and column that contain data.
     */
    _getUsedRange(sheetId) {
        const getters = this.spreadsheet_model.getters;
        const numCols = getters.getNumberCols(sheetId);
        const numRows = getters.getNumberRows(sheetId);

        let maxCol = -1;
        let maxRow = -1;

        // Scan a reasonable range (max 200 cols, 1000 rows)
        const scanCols = Math.min(numCols, 200);
        const scanRows = Math.min(numRows, 1000);

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
    },

    /**
     * Collect merge information for the used range.
     * Returns:
     *   - spans: Map of "col,row" -> {colspan, rowspan} for top-left cells of merges
     *   - hidden: Set of "col,row" strings for cells hidden by merges
     */
    _collectMerges(sheetId, maxCol, maxRow) {
        const getters = this.spreadsheet_model.getters;
        const spans = new Map();
        const hidden = new Set();

        for (let row = 0; row <= maxRow; row++) {
            for (let col = 0; col <= maxCol; col++) {
                const merge = getters.getMerge({sheetId, col, row});
                if (!merge) continue;

                const topLeft = `${merge.left},${merge.top}`;
                const current = `${col},${row}`;

                if (col === merge.left && row === merge.top) {
                    // This is the top-left cell of the merge
                    const colspan = merge.right - merge.left + 1;
                    const rowspan = merge.bottom - merge.top + 1;
                    if (colspan > 1 || rowspan > 1) {
                        spans.set(topLeft, {colspan, rowspan});
                    }
                } else {
                    // This cell is hidden by the merge
                    hidden.add(current);
                }
            }
        }
        return {spans, hidden};
    },
});
