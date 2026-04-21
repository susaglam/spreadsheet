# Spreadsheet OCA Modules — Installation & Test Guide

This document describes how to install and test all 26 spreadsheet modules in this repository on Odoo saas-19.2.

## Prerequisites

- Odoo saas-19.2 instance
- Python packages: `requests` (for webhook delivery in `spreadsheet_api_oca`)
- `wkhtmltopdf` (Odoo standard — required for `spreadsheet_pdf_report_oca`)
- Core modules: `spreadsheet`, `spreadsheet_dashboard`, `mail`, `portal`, `base`

## General Installation Steps

1. Copy the desired module directories into your Odoo addons path
2. Update the Apps List: **Apps** > **Update Apps List**
3. Search for the module by name and click **Install**
4. Many modules `auto_install` when their base dependency is present

---

## Module-by-Module Tests

### 1. `spreadsheet_template_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
1. **Save as Template** — Open a spreadsheet with data, click **File** > **Save as Template**. Pick a name and category. Verify a new record appears under **Spreadsheets** > **Templates**.
2. **Use Template** — Go to Templates kanban, click **Use Template** on a card. Verify a new spreadsheet opens with the template data. Check `usage_count` increments.
3. **Permission** — As a non-Template Manager user, verify you can read/use templates but not edit them.
4. **Category search** — Use the left searchpanel to filter by category.

---

### 2. `spreadsheet_kpi_alert_oca`

**Install**: Depends on `spreadsheet_oca`, `mail`.

**Test Scenarios**:
1. **Create alert** — Open a spreadsheet with a literal value in B2 (e.g., `1500`). Click the **KPI Alerts** smart button on the form. Create an alert: cell `B2`, operator `>`, threshold `1000`. Notify yourself.
2. **Test notification** — Click **Test Alert** button on the alert form. Check your Discuss inbox for the notification and the spreadsheet chatter for the message.
3. **Cron check** — Run the cron manually: **Settings** > **Technical** > **Scheduled Actions** > **"Spreadsheet: KPI Alert Threshold Check"** > **Run Manually**. Verify the alert triggers (cell value > threshold).
4. **Cooldown** — Trigger again immediately; verify no duplicate notification fires within the cooldown period.
5. **JS value sync** — Open a spreadsheet with a formula (e.g., `=SUM(A1:A10)`). Wait 5 minutes; verify `last_value` updates on the alert record.
6. **Email delivery** — Enable "Send Email" on an alert; trigger; check email inbox.

---

### 3. `spreadsheet_pdf_report_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
1. **Basic PDF** — Open any spreadsheet. **File** > **Download PDF**. Verify PDF downloads with company logo header.
2. **Formulas** — Create a cell with `=SUM(A1:A10)`. Download PDF; verify the computed value (not the formula) is rendered.
3. **Turkish characters** — Add text like "ÖğrenciçğüşıÖĞÜŞİÇ". Download; verify characters render correctly.
4. **Styles** — Apply bold, italic, colors to cells. Download; verify styles appear in PDF.
5. **Merged cells** — Merge some cells in the spreadsheet. Verify PDF preserves merges via colspan/rowspan.
6. **Multiple sheets** — Add 2–3 sheets. Verify all render in one PDF with sheet titles.

---

### 4. Pre-Built Dashboards (CRM/Sales/HR/Stock/E-commerce/Campaign/Stock-Sales/Loyalty/Segmentation/Quote-Conversion/Vendor)

**Install**: Auto-installs when their base app is present.

**Test Scenarios**:
1. **Dashboard visibility** — After install, open the **Dashboards** app. Verify the new dashboard appears in the sidebar.
2. **Data loading** — Open the dashboard. Verify pivots/lists show real data (KPIs, trend chart, tables).
3. **Global filters** — Use the Period filter (default "last 3 months"). Verify KPIs update.
4. **Scorecard comparison** — Check that current vs previous period comparison shows up/down arrows.
5. **Drill-down** — Click a chart section; verify it opens the underlying record list.

**Note**: If a dashboard module depends on an app (e.g., `loyalty`) that isn't installed, the dashboard module won't auto-install — that's by design.

---

### 5. `spreadsheet_portal_dashboard_oca`

**Install**: Depends on `spreadsheet_dashboard_oca`, `portal`.

**Test Scenarios**:
1. **Backend config** — Create an assignment: **Spreadsheets** > **Configuration** > **Portal Dashboards**. Pick a dashboard, select portal partner(s).
2. **Portal login** — Log in as a portal user (or use /web/session/authenticate with a portal user's credentials).
3. **View dashboards list** — Navigate to `/my/dashboards`. Verify assigned dashboards appear as cards.
4. **View dashboard detail** — Click "View Dashboard". Verify read-only HTML rendering with styles, merges, borders.
5. **Access control** — Log in as an unassigned portal user; verify empty list at `/my/dashboards`.
6. **Record rules** — Combine with `spreadsheet_record_rule_oca` to filter data per portal user's partner.

---

### 6. `spreadsheet_vendor_scorecard_oca`

**Install**: Depends on `spreadsheet_oca`, `purchase_stock`.

**Test Scenarios**:
1. **Manual create** — Go to **Purchase** > **Reporting** > **Vendor Scorecards** > **New**. Fill in vendor and metrics; save.
2. **Score calculation** — Verify the `score` field auto-computes (40% delivery + 40% quality + 20% lead time).
3. **Cron computation** — Run the monthly cron manually: **Scheduled Actions** > **"Compute Vendor Scorecards"** > **Run Manually**. Verify records auto-populate based on purchase orders.
4. **Decoration** — Verify color coding: green ≥ 80, yellow 50–80, red < 50.
5. **Dashboard** — Open the pre-built "Vendor Performance" dashboard; verify data loads.

---

### 7. `spreadsheet_multicompany_oca`

**Install**: Depends on `spreadsheet_oca`, `account`. Requires multi-company setup.

**Test Scenarios**:
1. **Create profile** — **Spreadsheets** > **Consolidation** > **New**. Select 2+ companies, a consolidation currency, elimination accounts.
2. **Generate report** — Click **Generate Consolidated Report**. Verify a new spreadsheet opens with per-company columns + consolidated total.
3. **Currency conversion** — Set different company currencies. Verify amounts convert to the consolidation currency.
4. **Eliminations** — Add inter-company elimination accounts; verify those rows zero out in the consolidated column.

---

### 8. `spreadsheet_contract_sla_oca`

**Install**: Depends on `spreadsheet_oca`, `sale`, `purchase`, `mail`.

**Test Scenarios**:
1. **Create contract** — **Spreadsheets** > **Contracts & SLA** > **New**. Fill in partner, type, dates, amount.
2. **Status auto-compute** — Set `date_end` to 20 days from now with `reminder_days=30`; verify status becomes "Expiring Soon".
3. **SLA metrics** — Add SLA metrics in the tab (e.g., target 99.9, actual 98.5). Verify compliance shows "Breached".
4. **Calendar view** — Switch to calendar; verify contracts render across their date range.
5. **Cron reminder** — Run "Contract Expiry Check" cron manually. Verify activity is scheduled and email sent for contracts exactly at reminder days before expiry.
6. **Renewal** — Click **Renew Contract**; verify dates shift forward by the original duration.

---

### 9. `spreadsheet_forecast_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
Open a spreadsheet. Enter known data in A1:A5 (x values 1-5), B1:B5 (y values 10, 12, 15, 19, 24).
1. `=ODOO.FORECAST(6, B1:B5, A1:A5)` — should return ~28 (linear extrapolation).
2. `=ODOO.TREND(B1:B5, A1:A5, 10)` — should return the trend value at x=10.
3. `=ODOO.MOVING_AVG(B1:B5, 3)` — should return average of last 3 values ≈ 19.3.

---

### 10. `spreadsheet_accounting_formulas_oca`

**Install**: Depends on `spreadsheet_oca`, `account`.

**Test Scenarios**:
1. Open a spreadsheet in a database with accounting data.
2. `=ODOO.BALANCE("6001")` — first call returns 0 (loading). Wait 1–2 seconds; cell re-evaluates and shows the real balance.
3. `=ODOO.CREDIT("1200", "2026-01-01", "2026-12-31")` — credit totals for the account.
4. `=ODOO.DEBIT("4000")` — debit totals.
5. Check the console: should see RPC calls to `account.account` with the method names.

---

### 11. `spreadsheet_period_comparison_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
Enter 1500 in B1, 1200 in B2.
1. `=ODOO.PERCENT_CHANGE(B1, B2)` — should return 25 (25% growth).
2. `=ODOO.VARIANCE(B1, B2)` — should return 300.
3. `=ODOO.GROWTH_ARROW(B1, B2)` — should return `▲ 25.0%`.
4. `=ODOO.YOY(B1, B2)` — same as PERCENT_CHANGE.

---

### 12. `spreadsheet_record_rule_oca`

**Install**: Depends on `spreadsheet_oca`, `spreadsheet_dashboard`.

**Test Scenarios**:
1. **Create a rule** — **Spreadsheets** > **Configuration** > **Dashboard Data Filters** > **New**. Pick a dashboard (e.g., Sales), model `sale.order`, domain `[('user_id', '=', user.id)]`, group = Sales User.
2. **Test as Sales User** — Log in as a user in the Sales group. Open the dashboard; verify only their own orders appear.
3. **Test as Admin** — Log in as admin (not in the group); verify all orders appear (rule doesn't apply).
4. **Domain syntax** — Enter invalid domain like `[('foo', '=', user.bar)]`; verify validation error on save.

---

### 13. `spreadsheet_api_oca`

**Install**: Depends on `spreadsheet_oca`. Requires `requests` Python package.

**Test Scenarios**:
1. **Create token** — **Spreadsheets** > **Configuration** > **API Tokens** > **New**. Save — a token is auto-generated.
2. **List API** —
   ```
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://your-odoo/api/spreadsheet/list
   ```
   Verify JSON with spreadsheets the user can access.
3. **Get detail** — `GET /api/spreadsheet/<id>` with Bearer token; verify full spreadsheet_raw.
4. **Rate limit** — Set `rate_limit_per_minute=5`. Make 6 calls in a minute; 6th should return 429.
5. **Webhook** — Set `webhook_url` to a service like `https://webhook.site`. Edit a spreadsheet that the token has access to. Wait 2 minutes (cron); check webhook.site for a POST with the payload.
6. **Regenerate token** — Click regenerate; verify old token returns 401, new token works.

---

### 14. `spreadsheet_version_history_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
1. **Create snapshot** — Open a spreadsheet with data. Click **New Snapshot** smart button.
2. **Modify and create another snapshot** — Change some cells; create a second snapshot.
3. **View versions** — Click **Versions** smart button; see the list.
4. **Open a version** — Click the oldest version. Visit the **Visual Diff vs Current** tab; verify cell-level diff shows added/changed/removed cells with badges.
5. **Restore** — Click **Restore This Version**. Confirm. Verify the spreadsheet returns to that version's state.
6. **Counts** — Verify `cells_added`, `cells_changed`, `cells_removed` summary fields are populated.

---

### 15. `spreadsheet_scheduled_refresh_oca`

**Install**: Depends on `spreadsheet_oca`.

**Test Scenarios**:
1. **Create schedule** — **Spreadsheets** > **Configuration** > **Refresh Schedules** > **New**. Pick a spreadsheet, interval=1 hours.
2. **Cron** — Run "Scheduled Data Refresh" cron manually. Verify `last_refresh` updates, `next_refresh` shifts forward.
3. **Bus notification** — Have the spreadsheet open in a browser. Run the cron; the browser should receive a `refresh_data` bus event (visible in browser DevTools network tab > WS frames).

---

### 16. `spreadsheet_email_report_oca`

**Install**: Depends on `spreadsheet_oca`, `mail`.

**Test Scenarios**:
1. **Create schedule** — **Spreadsheets** > **Configuration** > **Email Reports** > **New**. Pick spreadsheet, recipients (your email), format (xlsx), interval=1 weeks.
2. **Send now** — Click **Send Now**. Verify an email arrives with the xlsx attached.
3. **Next send** — Verify `next_send` auto-advances after manual send.
4. **Cron delivery** — Modify `next_send` to the past. Run the hourly cron; verify email sent and `last_sent`/`send_count` update.
5. **JSON format** — Change format to JSON. Send; verify attachment is a `.json` file.
6. **Extra emails** — Add comma-separated extra emails; verify they receive copies.

---

### 17. `spreadsheet_public_share_oca`

**Install**: Depends on `spreadsheet_oca`, `portal`.

**Test Scenarios**:
1. **Create share** — **Spreadsheets** > **Configuration** > **Public Share Links** > **New**. Pick a spreadsheet, save.
2. **Open link** — Copy the `share_url`. Open in a private/incognito window. Verify the spreadsheet renders read-only with cells, styles, merges.
3. **Download** — Enable "Allow Download". Open link, click download. Verify XLSX downloads.
4. **Password** — Set a password. Open link; verify password prompt appears. Enter correct/incorrect password; verify behavior.
5. **Expiry** — Set `expires_at` to past date. Open link; verify "Invalid or Expired Link" message.
6. **View counter** — Open the link multiple times; verify `view_count` and `last_viewed` update.
7. **Regenerate** — Click regenerate; verify old URL breaks, new URL works.

---

## Unified Settings Test

After installing any subset of `spreadsheet_api_oca`, `spreadsheet_kpi_alert_oca`, `spreadsheet_contract_sla_oca`, `spreadsheet_email_report_oca`, `spreadsheet_scheduled_refresh_oca`, `spreadsheet_public_share_oca`:

1. Go to **Settings** — you should see a **Spreadsheet** tab.
2. Verify all installed modules' configuration blocks appear in that tab.
3. Change a setting (e.g., "Default KPI Alert Cooldown Hours"), click Save. Verify it persists via `ir.config_parameter`.

---

## Translation Test

Switch user language to `tr`, `nl`, or `de` (via preferences). Verify:
1. Menu labels translate (e.g., "Templates" → "Sablonlar" in Turkish)
2. Button labels translate (e.g., "Save as Template" → "Sablon Olarak Kaydet")
3. Model names in the breadcrumb translate
4. Field labels on form views translate

---

## Security / Permission Test

1. **User tier (group_user)**: Can read spreadsheets, dashboards, templates (read-only). Can create own spreadsheets. Cannot edit system templates or dashboard rules.
2. **Manager tier (group_manager)**: Full CRUD on all spreadsheet resources. Automatically gets Template Manager privilege.
3. **No Access (None)**: Via **Users** > assign "No Access" in the Spreadsheet privilege dropdown. User sees no menus.
4. **Portal user**: Sees `/my/dashboards` when assigned; cannot access any `/odoo/` menus.

---

## Troubleshooting

- **"Module not installable"** — check the Python `requests` package is installed (for API module).
- **Assets not loading** — clear browser cache, restart Odoo with `--dev=all` flag.
- **Webhook not firing** — check the `ir.cron` "Spreadsheet API: Deliver Webhooks" is active and running every 2 minutes.
- **PDF export blank** — verify wkhtmltopdf is installed and accessible to Odoo.
- **Portal user gets AccessDenied on bus** — the module's `ir.websocket` override should handle this; verify `spreadsheet_portal_dashboard_oca` is installed.
