{
    "name": "Spreadsheet dashboard for purchases",
    "category": "Hidden",
    "depends": ["spreadsheet_dashboard", "purchase_stock"],
    "version": "saas~19.4.1.0.0",
    "website": "https://github.com/OCA/spreadsheet",
    "author": "Odoo S.A., Tecnativa, Odoo Community Association (OCA)",
    "data": ["data/dashboards.xml"],
    "installable": True,
    "auto_install": ["purchase_stock"],
    "license": "LGPL-3",
}
