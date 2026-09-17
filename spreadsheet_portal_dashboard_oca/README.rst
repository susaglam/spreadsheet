.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_portal_dashboard_oca
   :alt: OCA/spreadsheet

Spreadsheet Portal Dashboard
============================

|badge1| |badge2| |badge3|

Share spreadsheet dashboards with portal users (dealers, distributors) as a
read-only preview of the dashboard layout and labels.

**Table of contents**

.. contents::
   :local:

Features
========

* Assign dashboards to specific portal partners (a company includes the portal
  users of all its contacts) or to all portal users
* Portal users see a "Dashboards" card on ``/my`` and their list at
  ``/my/dashboards``
* Read-only HTML preview with style, merged cell and border support
* Server-side sanitized payload: no revisions, pivot/list definitions, hidden or
  ``Data`` sheets, or formula sources ever reach the browser. Calculated values
  are shown as an em dash, not computed.
* Archived assignments or dashboards stop being shared immediately

Usage
=====

Creating and editing assignments requires the **Dashboard: Admin**
right (``spreadsheet_dashboard.group_dashboard_manager``). You can only share
dashboards you are allowed to open yourself.

1. Go to **Dashboards** > **Configuration** > **Portal Dashboards** (also
   available under **Spreadsheets** > **Configuration** for dashboard
   administrators)
2. Create a new assignment: pick a dashboard and select portal partners, or
   tick **All Portal Users**
3. Portal users see their dashboards at ``/my/dashboards`` in the portal
4. Click any dashboard to view the read-only preview

Configuration
=============

* **All Portal Users** only covers portal (external) users. An internal
  employee only gets access when their own contact is listed in
  **Portal Partners**; their company is not enough.
* The preview shows the stored dashboard file, not live figures: it does not
  evaluate formulas, so record rules do not filter it per portal user.

Changelog
=========

saas~19.4.1.1.2
~~~~~~~~~~~~~~~

* Security: only Dashboard administrators can create, edit or delete portal
  assignments (Spreadsheet users keep read access), and only for dashboards
  they can open themselves. Review assignments created earlier by other users.
* Security: the preview payload is built server-side from a sanitized snapshot
  and cannot be called over RPC; portal users no longer receive the
  spreadsheet bus channel (live revisions) nor ORM read access to assignments.
* Security: ``All Portal Users`` no longer grants internal users access, and a
  company match only applies to portal users.
* The ``/my`` card is now a ``portal.entry`` record.
* The preview supports the saas-19.4 spreadsheet file format and no longer
  waits for an event that never fires on lazy-loaded frontend assets.

Dependencies
============

* ``spreadsheet_dashboard_oca``
* ``portal``

Known issues / Roadmap
======================

* Full o-spreadsheet read-only viewer
* Export to PDF from portal
* Time-limited share links

Credits
=======

Authors
~~~~~~~

* Codesnap

Contributors
~~~~~~~~~~~~

* Sukru Saglam <info@codesnap.nl>

Maintainers
~~~~~~~~~~~

This module is part of the OCA/spreadsheet project on GitHub.
