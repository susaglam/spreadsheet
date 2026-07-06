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

Share spreadsheet dashboards with portal users (dealers, distributors) — they see only their own data.

**Table of contents**

.. contents::
   :local:

Features
========

* Assign dashboards to specific portal partners or all portal users
* Portal users see a dashboard list at ``/my/dashboards``
* Read-only HTML renderer with style, merge cell, and border support
* Per-partner data filtering via record rules
* Websocket access for portal users (assigned dashboards only)

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Portal Dashboards**
2. Create a new assignment: pick a dashboard and select portal partners
3. Portal users see their dashboards at ``/my/dashboards`` in the portal
4. Click any dashboard to view the read-only rendering

Configuration
=============

* The base ir.websocket restriction is relaxed for assigned dashboards
* Combine with ``spreadsheet_record_rule_oca`` for per-user data filtering

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
