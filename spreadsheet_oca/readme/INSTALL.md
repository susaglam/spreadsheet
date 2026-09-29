## Upgrading an existing database

Version `saas~19.4.1.0.1` adds the shared *Spreadsheet* page in
Settings (view `spreadsheet_oca.res_config_settings_view_form`). The
add-ons `spreadsheet_api_oca`, `spreadsheet_contract_sla_oca`,
`spreadsheet_public_share_oca`, `spreadsheet_kpi_alert_oca` and
`spreadsheet_scheduled_refresh_oca` put their settings on that page, so
it has to exist in the database before they are upgraded.

When you upgrade a database that runs an older version, always include
`spreadsheet_oca` in the upgrade:

``` bash
odoo-bin module upgrade -c <config> -d <database> spreadsheet_oca
# or, with the server command:
odoo-bin -c <config> -d <database> -u spreadsheet_oca --stop-after-init
```

Upgrading `spreadsheet_oca` also upgrades every installed module that
depends on it, so this one command is enough. Upgrading only one of the
add-ons above (for example `-u spreadsheet_api_oca`) stops with
`External ID not found in the system: spreadsheet_oca.res_config_settings_view_form`
and that add-on is not upgraded. To recover, run the command above.
