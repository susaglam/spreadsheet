.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_contract_sla_oca
   :alt: OCA/spreadsheet

Contract & SLA Tracker
======================

|badge1| |badge2| |badge3|

Contract renewal calendar, SLA compliance tracking, and automated reminders.

**Table of contents**

.. contents::
   :local:

Features
========

* Contract registry (sales, purchase, service, other)
* Contract state auto-computed (draft, active, expiring, expired)
* SLA metrics per contract with target/actual/compliance
* Calendar view showing contract periods
* Automated email reminder before expiry
* Renewal action copies period forward

Usage
=====

1. Go to **Spreadsheets** > **Contracts & SLA**
2. Create a contract: partner, dates, value, responsible user
3. Add SLA metrics in the tab (e.g., 99.9% uptime)
4. Cron sends daily reminders for contracts nearing expiry
5. Click **Renew Contract** to extend for the same duration

Configuration
=============

* Daily cron checks expiring contracts (configurable)
* Email template customizable

Dependencies
============

* ``spreadsheet_oca``
* ``spreadsheet_kpi_alert_oca``
* ``mail``

Known issues / Roadmap
======================

* Contract templates
* E-signature integration
* Automatic SLA computation from support tickets

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
