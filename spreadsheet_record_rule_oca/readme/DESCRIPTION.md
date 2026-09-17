Narrow the data a spreadsheet dashboard displays for specific groups of users, for
example "each salesperson only sees their own orders on the Sales dashboard".

A rule targets one dashboard and one model (e.g. `sale.order`). Its Additional Domain is
AND-ed to the domain of every pivot, list and Odoo chart (including carousel charts) of
that model, for the users in the rule's groups. Rules are applied both in the core
Dashboards app and in the OCA spreadsheet viewer / portal dashboards.

**This is a display filter, NOT a security boundary.** The extra domain is added to the
dashboard data that is sent to the browser, so a technical user could remove it there,
and revisions stored on an OCA dashboard are not filtered. Nobody ever sees more than
their normal Odoo access rights allow, because every pivot, list and chart still reads
its records with the viewer's own access rights. When data must really be hidden, use
access rights (Settings > Technical > Security > Access Rights) instead of, or in
addition to, these rules.

Domains are evaluated safely with plain values only: `user_id`, `partner_id`,
`company_id` (active company), `company_ids` (active companies) and `group_xmlids`
(external IDs of the user's groups). A rule that cannot be evaluated **fails closed**:
the matching data sources show no records, a warning is logged and the rule shows its
Evaluation Problem in the configuration screen.
