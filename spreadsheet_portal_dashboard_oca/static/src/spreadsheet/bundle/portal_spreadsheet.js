/** @odoo-module **/

import {rpc} from "@web/core/network/rpc";
import {_t} from "@web/core/l10n/translation";

/**
 * Portal Spreadsheet Dashboard Viewer
 *
 * Fetches dashboard data and renders a read-only HTML table representation
 * for portal users. This avoids loading the full o-spreadsheet library
 * in the frontend bundle.
 */
document.addEventListener("DOMContentLoaded", async () => {
    const container = document.getElementById("portal-spreadsheet-container");
    if (!container) return;

    const dashboardId = parseInt(container.dataset.dashboardId, 10);
    if (!dashboardId) return;

    try {
        const data = await rpc(`/my/dashboards/${dashboardId}/data`, {});

        if (data.error) {
            container.innerHTML = `
                <div class="alert alert-danger m-3">
                    <i class="fa fa-exclamation-triangle me-2"></i>
                    ${data.error}
                </div>`;
            return;
        }

        renderDashboard(container, data);
    } catch (e) {
        container.innerHTML = `
            <div class="alert alert-warning m-3">
                <i class="fa fa-exclamation-triangle me-2"></i>
                ${_t("Unable to load dashboard data. Please try again later.")}
            </div>`;
        console.error("Portal dashboard load error:", e);
    }
});

function renderDashboard(container, data) {
    const raw = data.spreadsheet_raw;
    if (!raw || !raw.sheets) {
        container.innerHTML = `
            <div class="alert alert-info m-3">
                <i class="fa fa-info-circle me-2"></i>
                ${_t("This dashboard has no data yet.")}
            </div>`;
        return;
    }

    const styles = raw.styles || {};
    const borders = raw.borders || {};
    let html = "";

    for (const sheet of raw.sheets) {
        if (sheet.name === "Data") continue;

        html += `<div class="portal-sheet-section p-3">`;
        html += `<h5 class="portal-sheet-title mb-3">
                    <i class="fa fa-table me-2"></i>${escapeHtml(sheet.name)}
                 </h5>`;

        const cells = sheet.cells || {};
        const cols = sheet.cols || {};
        const rows = sheet.rows || {};
        const merges = parseMerges(sheet.merges || []);

        if (Object.keys(cells).length === 0) {
            html += `<p class="text-muted">${_t("Empty sheet")}</p></div>`;
            continue;
        }

        let maxCol = 0;
        let maxRow = 0;
        for (const ref of Object.keys(cells)) {
            const {col, row} = parseCellRef(ref);
            if (col > maxCol) maxCol = col;
            if (row > maxRow) maxRow = row;
        }
        maxCol = Math.min(maxCol, 25);
        maxRow = Math.min(maxRow, 100);

        html += `<div class="table-responsive">`;
        html += `<table class="table table-sm portal-sheet-table">`;

        // Column widths
        html += `<colgroup>`;
        for (let col = 0; col <= maxCol; col++) {
            const size = (cols[col] && cols[col].size) || 100;
            html += `<col style="width:${size}px" />`;
        }
        html += `</colgroup>`;

        html += `<tbody>`;
        for (let row = 0; row <= maxRow; row++) {
            const rowHeight = (rows[row] && rows[row].size) || null;
            html += `<tr${rowHeight ? ` style="height:${rowHeight}px"` : ""}>`;
            for (let col = 0; col <= maxCol; col++) {
                const mergeKey = `${col},${row}`;
                // Skip hidden cells inside merges
                if (merges.hidden.has(mergeKey)) continue;

                const ref = colToLetter(col) + (row + 1);
                const cell = cells[ref];
                let value = "";
                let style = "";

                if (cell) {
                    const content = cell.content || "";
                    const resolved = resolveCellDisplay(content);
                    if (resolved.computed) {
                        // Honest placeholder: this lightweight viewer has no
                        // o-spreadsheet engine, so a computed value cannot be
                        // shown here. An em dash says "no value" without the
                        // old "f(x)" masquerading as content.
                        value = `<span class="text-muted" title="Live value — open the full dashboard to see computed figures">—</span>`;
                    } else {
                        value = escapeHtml(resolved.text);
                    }
                    if (cell.style && styles[cell.style]) {
                        style += styleToCss(styles[cell.style]);
                    }
                    if (cell.border && borders[cell.border]) {
                        style += borderToCss(borders[cell.border]);
                    }
                }

                const span = merges.spans.get(mergeKey);
                const spanAttrs = span
                    ? ` colspan="${span.colspan}" rowspan="${span.rowspan}"`
                    : "";
                html += `<td${spanAttrs}${style ? ` style="${style}"` : ""}>${value}</td>`;
            }
            html += `</tr>`;
        }
        html += `</tbody></table></div></div>`;
    }

    // Render figures info (scorecards and charts are described but not rendered)
    for (const sheet of raw.sheets) {
        const figures = sheet.figures || [];
        if (figures.length > 0 && sheet.name !== "Data") {
            html += `<div class="portal-figures-info p-3 border-top">`;
            html += `<h6 class="text-muted mb-2">
                        <i class="fa fa-pie-chart me-2"></i>${_t("Charts & KPIs")}
                     </h6>`;
            html += `<div class="row">`;
            for (const fig of figures) {
                if (fig.data && fig.data.type === "scorecard") {
                    // Show the KPI's real title, but an honest em dash instead
                    // of a chart icon that implied a value we cannot compute in
                    // this preview.
                    html += `
                        <div class="col-md-3 col-sm-6 mb-2">
                            <div class="card text-center p-2">
                                <div class="card-body p-2">
                                    <div class="text-muted small">${escapeHtml(fig.data.title || _t("KPI"))}</div>
                                    <div class="h5 mb-0 text-muted" title="Live value — open the full dashboard to see computed figures">—</div>
                                </div>
                            </div>
                        </div>`;
                }
            }
            html += `</div></div>`;
        }
    }

    // A one-line notice so the preview never misrepresents itself: it shows
    // layout + labels; live figures come from the full dashboard.
    const banner = `
        <div class="alert alert-info d-flex align-items-center m-3" role="alert">
            <i class="fa fa-info-circle me-2"></i>
            <span>${_t("This is a lightweight preview showing the dashboard layout and labels. Live KPI and pivot figures are calculated when you open the full dashboard.")}</span>
        </div>`;
    container.innerHTML = html
        ? banner + html
        : `
        <div class="alert alert-info m-3">
            <i class="fa fa-info-circle me-2"></i>
            ${_t("Dashboard loaded but no displayable content found.")}
        </div>`;
}

/**
 * Resolve what a cell should display in the engine-less portal preview.
 *
 * Returns {text, computed}:
 *  - Plain (non-formula) content -> shown verbatim.
 *  - A pure translation label =_t("...") -> its literal text (headers stay
 *    meaningful instead of collapsing to "f(x)").
 *  - Any other formula -> computed:true, so the caller shows an honest em dash
 *    rather than faking a value the frontend cannot evaluate.
 */
const T_LITERAL_RE = /^=_t\(\s*(["'])([\s\S]*?)\1\s*\)$/;
function resolveCellDisplay(content) {
    if (!content || !content.startsWith("=")) {
        return {text: content || "", computed: false};
    }
    const match = content.match(T_LITERAL_RE);
    if (match) {
        return {text: match[2], computed: false};
    }
    return {text: "", computed: true};
}

/**
 * Parse merge definitions like "A1:B3" into span/hidden maps.
 */
function parseMerges(merges) {
    const spans = new Map();
    const hidden = new Set();
    for (const merge of merges) {
        const [tlRef, brRef] = merge.split(":");
        if (!tlRef || !brRef) continue;
        const tl = parseCellRef(tlRef);
        const br = parseCellRef(brRef);
        const colspan = br.col - tl.col + 1;
        const rowspan = br.row - tl.row + 1;
        spans.set(`${tl.col},${tl.row}`, {colspan, rowspan});
        for (let r = tl.row; r <= br.row; r++) {
            for (let c = tl.col; c <= br.col; c++) {
                if (c === tl.col && r === tl.row) continue;
                hidden.add(`${c},${r}`);
            }
        }
    }
    return {spans, hidden};
}

function styleToCss(s) {
    let css = "";
    if (s.bold) css += "font-weight:bold;";
    if (s.italic) css += "font-style:italic;";
    if (s.underline) css += "text-decoration:underline;";
    if (s.strikethrough) css += "text-decoration:line-through;";
    if (s.textColor) css += `color:${s.textColor};`;
    if (s.fillColor) css += `background-color:${s.fillColor};`;
    if (s.fontSize) css += `font-size:${s.fontSize}px;`;
    if (s.align) css += `text-align:${s.align};`;
    if (s.verticalAlign) css += `vertical-align:${s.verticalAlign};`;
    return css;
}

function borderToCss(b) {
    let css = "";
    const sides = ["top", "right", "bottom", "left"];
    for (const side of sides) {
        if (b[side]) {
            const [style, color] = b[side];
            const width = style === "thin" ? "1px" : style === "thick" ? "3px" : "2px";
            css += `border-${side}:${width} solid ${color || "#000"};`;
        }
    }
    return css;
}

function parseCellRef(ref) {
    const match = ref.match(/^([A-Z]+)(\d+)$/i);
    if (!match) return {col: 0, row: 0};
    let col = 0;
    const letters = match[1].toUpperCase();
    for (let i = 0; i < letters.length; i++) {
        col = col * 26 + (letters.charCodeAt(i) - 64);
    }
    return {col: col - 1, row: parseInt(match[2], 10) - 1};
}

function colToLetter(col) {
    let result = "";
    col += 1;
    while (col > 0) {
        col -= 1;
        result = String.fromCharCode(65 + (col % 26)) + result;
        col = Math.floor(col / 26);
    }
    return result;
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
