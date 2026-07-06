.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_kpi_alert_oca
   :alt: OCA/spreadsheet

Spreadsheet KPI Alert
=====================

|badge1| |badge2| |badge3|

Set threshold alerts on spreadsheet cells with cron-based notifications via mail and internal chat.

**Table of contents**

.. contents::
   :local:

Features
========

* Define alerts on any spreadsheet cell with comparison operator (>, <, =, etc.)
* Cron-based threshold checking (default: every 15 minutes)
* Multi-channel notification: Discuss inbox + optional email
* Cooldown period to prevent alert spam
* JS client syncs computed formula values to server every 5 minutes
* Manual test button to preview notifications
* Smart button on spreadsheet form shows alert count

Usage
=====

1. Open a spreadsheet
2. Click the **KPI Alerts** smart button on the form view, or **Data** > **KPI Alerts** in the editor
3. Create an alert: pick the cell (e.g., B2), operator, threshold, and notification recipients
4. Enable/disable email delivery as needed
5. The cron checks values and sends notifications when breached

Configuration
=============

* Adjust cron interval via **Settings** > **Technical** > **Scheduled Actions**
* Customize email template via **Settings** > **Technical** > **Email Templates**

Dependencies
============

* ``spreadsheet_oca``
* ``mail``

Known issues / Roadmap
======================

* Alert history log
* Slack/Teams webhook delivery
* Conditional formatting of alert cells

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
