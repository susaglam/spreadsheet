1. As an administrator (Settings / Administration rights), go to **Spreadsheets >
   Configuration > Dashboard Data Filters**.
2. Create a rule: pick the dashboard, enter the technical model name used by its pivots,
   lists or charts (e.g. `sale.order`) and choose the groups it applies to (empty = all
   users).
3. Enter the Additional Domain, for example:
   - `[('user_id', '=', user_id)]`: only the viewer's own records;
   - `[('company_id', 'in', company_ids + [False])]`: only the active companies;
   - `[] if 'sales_team.group_sale_manager' in group_xmlids else [('user_id', '=', user_id)]`:
     managers see everything, others only their own records.
4. Open the dashboard as a user of that group: its data sources are narrowed.

Several applicable rules for the same dashboard and model are combined with AND. Users
who can edit the dashboard design open it unfiltered in the OCA spreadsheet editor, so
their personal filter is never saved into the dashboard itself.

If a rule is shown in red in the list, open it: the Evaluation Problem explains what is
wrong and how to fix it. Until then the rule hides the data of its model (fail closed).
