/** @odoo-module **/

import {_t} from "@web/core/l10n/translation";
import {rpc} from "@web/core/network/rpc";

/**
 * Portal Spreadsheet Dashboard Viewer
 *
 * Fetches dashboard data and renders a read-only HTML table representation
 * for portal users. This avoids loading the full o-spreadsheet library
 * in the frontend bundle.
 *
 * Security: every value coming from the spreadsheet file is untrusted. The
 * DOM is built with createElement/textContent and styles are applied through
 * element.style.setProperty() with whitelisted values only — never through
 * innerHTML or a style="" string.
 */

// Last rendered column (Z) and row (101), 0-based.
const MAX_COL = 25;
const MAX_ROW = 100;
const DATA_SHEET_NAMES = new Set(["Data"]);

const HEX_COLOR_RE = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const RGB_COLOR_RE =
    /^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/i;
const ALIGNMENTS = new Set(["left", "center", "right"]);
const VERTICAL_ALIGNMENTS = new Set(["top", "middle", "bottom"]);
const BORDER_STYLES = {
    thin: ["1px", "solid"],
    medium: ["2px", "solid"],
    thick: ["3px", "solid"],
    dashed: ["1px", "dashed"],
    dotted: ["1px", "dotted"],
};
const CELL_REF_RE = /^\$?([A-Z]{1,3})\$?(\d{1,7})$/i;
// A pure translation label =_t("Revenue"). The literal may not contain an
// unescaped double quote, so =_t("a")&ODOO.LIST.HEADER(1,"field") does not
// match (same rule as the server-side sanitizer).
const T_LITERAL_RE = /^=_t\(\s*"((?:[^"\\]|\\[\s\S])*)"\s*\)$/;
// Integer literals o-spreadsheet squishes: 42, -7, 1,000.
const INTEGER_RE = /^\s*[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)\s*$/;

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSquished(value) {
    return isObject(value) && ("N" in value || "S" in value || "R" in value);
}

// ---------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------

function parseCellRef(ref) {
    const match = typeof ref === "string" ? ref.trim().match(CELL_REF_RE) : null;
    if (!match) {
        return null;
    }
    let col = 0;
    const letters = match[1].toUpperCase();
    for (let i = 0; i < letters.length; i++) {
        col = col * 26 + (letters.charCodeAt(i) - 64);
    }
    return {col: col - 1, row: parseInt(match[2], 10) - 1};
}

/**
 * Parse "A1" or "A1:B3" into {left, top, right, bottom}.
 *
 * @param {String} xc
 * @returns {Object|null}
 */
function parseZone(xc) {
    if (typeof xc !== "string") {
        return null;
    }
    const [firstRef, lastRef] = xc.split(":");
    const first = parseCellRef(firstRef);
    const last = lastRef === undefined ? first : parseCellRef(lastRef);
    if (!first || !last) {
        return null;
    }
    return {
        left: Math.min(first.col, last.col),
        top: Math.min(first.row, last.row),
        right: Math.max(first.col, last.col),
        bottom: Math.max(first.row, last.row),
    };
}

function zoneSize(zone) {
    return (zone.right - zone.left + 1) * (zone.bottom - zone.top + 1);
}

/**
 * Yield [col, row] of a zone in column order, clipped to maxCol/maxRow.
 *
 * @param {Object} zone
 * @param {Number} maxCol
 * @param {Number} maxRow
 */
function* iterateZone(zone, maxCol, maxRow) {
    const right = Math.min(zone.right, maxCol);
    const bottom = Math.min(zone.bottom, maxRow);
    for (let col = zone.left; col <= right; col++) {
        for (let row = zone.top; row <= bottom; row++) {
            yield [col, row];
        }
    }
}

/**
 * Parse merge definitions like "A1:B3" into span/hidden maps, clipped to the
 * rendered area.
 *
 * @param {Array} merges
 * @param {Number} maxCol
 * @param {Number} maxRow
 * @returns {Object}
 */
function parseMerges(merges, maxCol, maxRow) {
    const spans = new Map();
    const hidden = new Set();
    for (const merge of Array.isArray(merges) ? merges : []) {
        const zone = parseZone(merge);
        if (!zone || zone.left > maxCol || zone.top > maxRow) {
            continue;
        }
        spans.set(`${zone.left},${zone.top}`, {
            colspan: Math.min(zone.right, maxCol) - zone.left + 1,
            rowspan: Math.min(zone.bottom, maxRow) - zone.top + 1,
        });
        for (const [col, row] of iterateZone(zone, maxCol, maxRow)) {
            if (col !== zone.left || row !== zone.top) {
                hidden.add(`${col},${row}`);
            }
        }
    }
    return {spans, hidden};
}

// ---------------------------------------------------------------------------
// Styles (whitelisted values only)
// ---------------------------------------------------------------------------

function safeColor(value) {
    if (typeof value !== "string") {
        return null;
    }
    const color = value.trim();
    return HEX_COLOR_RE.test(color) || RGB_COLOR_RE.test(color) ? color : null;
}

function safeNumber(value, min, max) {
    const number = typeof value === "number" ? value : Number.NaN;
    return Number.isFinite(number) && number >= min && number <= max ? number : null;
}

function applyTextStyle(td, style) {
    if (style.bold === true) {
        td.style.setProperty("font-weight", "bold");
    }
    if (style.italic === true) {
        td.style.setProperty("font-style", "italic");
    }
    const decorations = [];
    if (style.underline === true) {
        decorations.push("underline");
    }
    if (style.strikethrough === true) {
        decorations.push("line-through");
    }
    if (decorations.length) {
        td.style.setProperty("text-decoration", decorations.join(" "));
    }
    // Font sizes in o-spreadsheet are expressed in points.
    const fontSize = safeNumber(style.fontSize, 1, 200);
    if (fontSize) {
        td.style.setProperty("font-size", `${fontSize}pt`);
    }
}

function applyCellStyle(td, style) {
    applyTextStyle(td, style);
    const textColor = safeColor(style.textColor);
    if (textColor) {
        td.style.setProperty("color", textColor);
    }
    const fillColor = safeColor(style.fillColor);
    if (fillColor) {
        td.style.setProperty("background-color", fillColor);
    }
    if (ALIGNMENTS.has(style.align)) {
        td.style.setProperty("text-align", style.align);
    }
    if (VERTICAL_ALIGNMENTS.has(style.verticalAlign)) {
        td.style.setProperty("vertical-align", style.verticalAlign);
    }
}

function applyBorder(td, border) {
    for (const side of ["top", "right", "bottom", "left"]) {
        let descr = border[side];
        // Legacy files stored [style, color]; o-spreadsheet >= 16.3 stores
        // {style, color}.
        if (Array.isArray(descr)) {
            descr = {style: descr[0], color: descr[1]};
        }
        if (!isObject(descr)) {
            continue;
        }
        const [width, lineStyle] = BORDER_STYLES[descr.style] || BORDER_STYLES.thin;
        const color = safeColor(descr.color) || "#000000";
        td.style.setProperty(`border-${side}`, `${width} ${lineStyle} ${color}`);
    }
}

// ---------------------------------------------------------------------------
// Cells: legacy and saas-19.4 formats
// ---------------------------------------------------------------------------

function formatNumber(number, grouped) {
    const text = String(number);
    return grouped ? text.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : text;
}

function resolveStringDisplay(value, state) {
    if (value.startsWith("=")) {
        const match = value.match(T_LITERAL_RE);
        if (match) {
            state.mode = "label";
            state.label = match[1];
            return {text: match[1], computed: false};
        }
        state.mode = "formula";
        return {text: "", computed: true};
    }
    if (INTEGER_RE.test(value)) {
        state.mode = "number";
        state.grouped = value.includes(",");
        state.number = parseInt(value.replace(/,/g, ""), 10);
    } else {
        state.mode = "text";
    }
    return {text: value, computed: false};
}

function resolveSquishedDisplay(value, state) {
    if (state.mode === "label") {
        // "=" means "same label as the previous cell".
        const strings = Array.isArray(value.S) ? value.S : [];
        if (typeof strings[0] === "string" && strings[0] !== "=") {
            state.label = strings[0];
        }
        return {text: state.label, computed: false};
    }
    if (state.mode === "number") {
        const offset = typeof value.N === "string" ? parseFloat(value.N) : Number.NaN;
        if (Number.isFinite(offset)) {
            state.number += offset;
            return {text: formatNumber(state.number, state.grouped), computed: false};
        }
        return null;
    }
    if (state.mode === "formula") {
        return {text: "", computed: true};
    }
    // Offset of a static value this preview cannot format (or a malformed
    // file): show an empty cell rather than a fake "calculated" placeholder.
    return null;
}

/**
 * Resolve what a cell should display in the engine-less portal preview.
 *
 * Returns {text, computed} or null when there is nothing to show:
 *  - plain (non-formula) content -> shown verbatim;
 *  - a pure translation label =_t("...") (and its squished followers) -> the
 *    literal text, so headers stay meaningful;
 *  - an integer followed by squished number offsets -> the real number;
 *  - any other formula -> computed:true, so the caller shows an honest em
 *    dash rather than faking a value the frontend cannot evaluate.
 *
 * @param {any} value
 * @param {Object} state unsquish state shared by the cells of a sheet
 * @returns {Object|null}
 */
function resolveCellDisplay(value, state) {
    if (value === undefined || value === null || value === "") {
        return null;
    }
    if (typeof value === "number") {
        state.mode = "text";
        return {text: String(value), computed: false};
    }
    if (typeof value === "string") {
        return resolveStringDisplay(value, state);
    }
    if (isSquished(value)) {
        return resolveSquishedDisplay(value, state);
    }
    return null;
}

function sortedCellKeys(cells) {
    const keys = [];
    for (const key of Object.keys(cells)) {
        const zone = parseZone(key);
        if (zone) {
            keys.push({key, zone});
        }
    }
    // Squished offsets are relative to the previous cell in column order.
    keys.sort((a, b) =>
        a.zone.left === b.zone.left
            ? a.zone.top - b.zone.top
            : a.zone.left - b.zone.left
    );
    return keys;
}

function legacyIds(legacy) {
    const ids = {};
    if (legacy && Number.isInteger(legacy.style)) {
        ids.styleId = legacy.style;
    }
    if (legacy && Number.isInteger(legacy.border)) {
        ids.borderId = legacy.border;
    }
    return ids;
}

/**
 * Build a map "col,row" -> {col, row, text, computed, styleId, borderId}.
 *
 * Supports both storage formats:
 *  - legacy (o-spreadsheet < 18.1.1): cells[xc] = {content, style, border}
 *    with style/border ids pointing to the workbook-level maps;
 *  - current (saas-19.4): cells[xc] = "content", where xc may be a range
 *    ("B2:B9") and the content may be a "squished" offset ({N, S, R})
 *    relative to the previous cell of the column. Styles/borders live in
 *    per-sheet zone maps (sheet.styles / sheet.borders).
 *
 * @param {Object} sheet
 * @returns {Map}
 */
function buildCellGrid(sheet) {
    const grid = new Map();
    const cells = isObject(sheet.cells) ? sheet.cells : {};
    const state = {mode: null, label: "", number: 0, grouped: false};
    for (const {key, zone} of sortedCellKeys(cells)) {
        if (zone.left > MAX_COL) {
            // Keys are sorted by column: nothing further can be displayed.
            break;
        }
        let value = cells[key];
        let legacy = null;
        if (isObject(value) && !isSquished(value)) {
            legacy = value;
            value = typeof value.content === "string" ? value.content : "";
        }
        let visited = 0;
        for (const [col, row] of iterateZone(zone, MAX_COL, MAX_ROW)) {
            visited++;
            const display = resolveCellDisplay(value, state);
            if (display) {
                grid.set(`${col},${row}`, {col, row, ...display, ...legacyIds(legacy)});
            }
        }
        // Cells outside the preview area still move the unsquish state, so
        // the next visible cell of the sequence resolves to the right value.
        if (!visited) {
            resolveCellDisplay(value, state);
            visited = 1;
        }
        const remaining = zoneSize(zone) - visited;
        const offset = isSquished(value) ? parseFloat(value.N) : Number.NaN;
        if (remaining > 0 && state.mode === "number" && Number.isFinite(offset)) {
            state.number += offset * remaining;
        }
    }
    return grid;
}

/**
 * Apply per-sheet zone maps ({"A1:B3": id}) of the saas-19.4 format to the
 * cells of the rendered area.
 *
 * @param {Map} grid
 * @param {Object} zoneMap
 * @param {String} attribute
 * @param {Number} maxCol
 * @param {Number} maxRow
 */
function applyZoneItems(grid, zoneMap, attribute, maxCol, maxRow) {
    if (!isObject(zoneMap)) {
        return;
    }
    for (const [zoneXc, itemId] of Object.entries(zoneMap)) {
        const zone = parseZone(zoneXc);
        if (!zone || !Number.isInteger(itemId)) {
            continue;
        }
        for (const [col, row] of iterateZone(zone, maxCol, maxRow)) {
            const key = `${col},${row}`;
            let entry = grid.get(key);
            if (!entry) {
                // Styled but empty cell (e.g. a coloured header band).
                entry = {col, row, text: "", computed: false};
                grid.set(key, entry);
            }
            entry[attribute] = itemId;
        }
    }
}

/**
 * Chart titles are `{text: "..."}` objects since o-spreadsheet 17.4; older
 * files stored a plain string.
 *
 * @param {Object} figureData
 * @returns {String}
 */
function figureTitle(figureData) {
    const title = figureData.title;
    if (typeof title === "string") {
        return title;
    }
    if (isObject(title) && typeof title.text === "string") {
        return title.text;
    }
    return "";
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function createEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) {
        el.className = className;
    }
    if (text !== undefined && text !== null) {
        el.textContent = String(text);
    }
    return el;
}

function createIcon(iconClass) {
    const icon = createEl("i", `fa ${iconClass} me-2`);
    icon.setAttribute("aria-hidden", "true");
    return icon;
}

function buildAlert(level, iconClass, message) {
    const alert = createEl("div", `alert alert-${level} d-flex align-items-center m-3`);
    alert.setAttribute("role", "alert");
    alert.append(createIcon(iconClass), createEl("span", "", message));
    return alert;
}

function showAlert(container, level, iconClass, message) {
    container.replaceChildren(buildAlert(level, iconClass, message));
}

function computedPlaceholder(className) {
    // Honest placeholder: this lightweight viewer has no o-spreadsheet engine,
    // so a computed value cannot be shown here.
    const span = createEl("span", className || "text-muted", "—");
    span.title = _t("Calculated value, not shown in this preview");
    return span;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderCell(entry, styles, borders) {
    const td = createEl("td");
    if (!entry) {
        return td;
    }
    if (entry.computed) {
        td.append(computedPlaceholder());
    } else if (entry.text) {
        td.textContent = entry.text;
    }
    if (entry.styleId !== undefined && isObject(styles[entry.styleId])) {
        applyCellStyle(td, styles[entry.styleId]);
    }
    if (entry.borderId !== undefined && isObject(borders[entry.borderId])) {
        applyBorder(td, borders[entry.borderId]);
    }
    return td;
}

function renderTable(sheet, raw, grid) {
    let maxCol = 0;
    let maxRow = 0;
    for (const entry of grid.values()) {
        maxCol = Math.max(maxCol, entry.col);
        maxRow = Math.max(maxRow, entry.row);
    }
    applyZoneItems(grid, sheet.styles, "styleId", maxCol, maxRow);
    applyZoneItems(grid, sheet.borders, "borderId", maxCol, maxRow);

    const styles = isObject(raw.styles) ? raw.styles : {};
    const borders = isObject(raw.borders) ? raw.borders : {};
    const cols = isObject(sheet.cols) ? sheet.cols : {};
    const rows = isObject(sheet.rows) ? sheet.rows : {};
    const merges = parseMerges(sheet.merges, maxCol, maxRow);

    const table = createEl("table", "table table-sm portal-sheet-table");
    const colgroup = createEl("colgroup");
    for (let col = 0; col <= maxCol; col++) {
        const colEl = createEl("col");
        const size = safeNumber(cols[col] && cols[col].size, 1, 2000) || 100;
        colEl.style.setProperty("width", `${size}px`);
        colgroup.append(colEl);
    }
    table.append(colgroup);

    const tbody = createEl("tbody");
    for (let row = 0; row <= maxRow; row++) {
        const tr = createEl("tr");
        const rowHeight = safeNumber(rows[row] && rows[row].size, 1, 2000);
        if (rowHeight) {
            tr.style.setProperty("height", `${rowHeight}px`);
        }
        for (let col = 0; col <= maxCol; col++) {
            const key = `${col},${row}`;
            // Skip cells covered by a merge
            if (merges.hidden.has(key)) {
                continue;
            }
            const td = renderCell(grid.get(key), styles, borders);
            const span = merges.spans.get(key);
            if (span) {
                td.colSpan = span.colspan;
                td.rowSpan = span.rowspan;
            }
            tr.append(td);
        }
        tbody.append(tr);
    }
    table.append(tbody);
    return table;
}

function renderSheet(sheet, raw) {
    const section = createEl("div", "portal-sheet-section p-3");
    const title = createEl("h5", "portal-sheet-title mb-3");
    title.append(
        createIcon("fa-table"),
        document.createTextNode(String(sheet.name || ""))
    );
    section.append(title);

    const grid = buildCellGrid(sheet);
    if (!grid.size) {
        section.append(createEl("p", "text-muted", _t("Empty sheet")));
        return section;
    }
    const wrapper = createEl("div", "table-responsive");
    wrapper.append(renderTable(sheet, raw, grid));
    section.append(wrapper);
    return section;
}

function renderFigures(sheet) {
    const figures = Array.isArray(sheet.figures) ? sheet.figures : [];
    const scorecards = figures.filter(
        (fig) => fig && isObject(fig.data) && fig.data.type === "scorecard"
    );
    if (!scorecards.length) {
        return null;
    }
    const section = createEl("div", "portal-figures-info p-3 border-top");
    const heading = createEl("h6", "text-muted mb-2");
    heading.append(
        createIcon("fa-pie-chart"),
        document.createTextNode(_t("Charts & KPIs"))
    );
    section.append(heading);
    const row = createEl("div", "row");
    for (const fig of scorecards) {
        // Show the KPI's real title, but an honest em dash instead of a value
        // we cannot compute in this preview.
        const col = createEl("div", "col-md-3 col-sm-6 mb-2");
        const card = createEl("div", "card text-center p-2");
        const body = createEl("div", "card-body p-2");
        body.append(
            createEl("div", "text-muted small", figureTitle(fig.data) || _t("KPI")),
            computedPlaceholder("h5 mb-0 text-muted d-block")
        );
        card.append(body);
        col.append(card);
        row.append(col);
    }
    section.append(row);
    return section;
}

function renderDashboard(container, data) {
    const raw = data.spreadsheet_raw;
    if (!raw || !Array.isArray(raw.sheets)) {
        showAlert(
            container,
            "info",
            "fa-info-circle",
            _t("This dashboard has no data yet.")
        );
        return;
    }

    const content = document.createDocumentFragment();
    const visibleSheets = raw.sheets.filter(
        (sheet) =>
            sheet && sheet.isVisible !== false && !DATA_SHEET_NAMES.has(sheet.name)
    );
    for (const sheet of visibleSheets) {
        content.append(renderSheet(sheet, raw));
    }
    // Figures (scorecards are described, charts are not rendered).
    for (const sheet of visibleSheets) {
        const figuresSection = renderFigures(sheet);
        if (figuresSection) {
            content.append(figuresSection);
        }
    }

    if (!content.childNodes.length) {
        showAlert(
            container,
            "info",
            "fa-info-circle",
            _t("Dashboard loaded but no displayable content found.")
        );
        return;
    }
    // A one-line notice so the preview never misrepresents itself: it shows
    // layout + labels only. Portal users have no backend dashboard to open,
    // so the notice points them to someone who can give them the figures.
    container.replaceChildren(
        buildAlert(
            "info",
            "fa-info-circle",
            _t(
                "This preview shows the dashboard layout and labels. Calculated figures, such as KPIs and pivot values, are not shown here. Ask your contact person if you need the latest figures."
            )
        ),
        content
    );
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function loadDashboard(container, dashboardId) {
    let data = null;
    try {
        data = await rpc(`/my/dashboards/${dashboardId}/data`, {});
    } catch (e) {
        console.error("Portal dashboard load error:", e);
        showAlert(
            container,
            "warning",
            "fa-exclamation-triangle",
            _t("Unable to load dashboard data. Please try again later.")
        );
        return;
    }
    if (data && data.error) {
        showAlert(container, "danger", "fa-exclamation-triangle", String(data.error));
        return;
    }
    try {
        renderDashboard(container, data || {});
    } catch (e) {
        // A malformed file must not leave the spinner running forever.
        console.error("Portal dashboard render error:", e);
        showAlert(
            container,
            "warning",
            "fa-exclamation-triangle",
            _t("Unable to load dashboard data. Please try again later.")
        );
    }
}

function start() {
    const container = document.getElementById("portal-spreadsheet-container");
    if (!container || container.dataset.portalDashboardStarted) {
        return;
    }
    const dashboardId = parseInt(container.dataset.dashboardId, 10);
    if (!dashboardId) {
        return;
    }
    container.dataset.portalDashboardStarted = "1";
    loadDashboard(container, dashboardId);
}

// The web.assets_frontend bundle is lazy-loaded after window "load"
// (web/static/src/public/lazyloader.js): DOMContentLoaded has usually fired
// long before this module runs, so a bare listener would never be called.
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, {once: true});
} else {
    start();
}
