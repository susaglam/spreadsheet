.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_email_report_oca
   :alt: OCA/spreadsheet

Scheduled Email Report
======================

|badge1| |badge2| |badge3|

Schedule automatic email delivery of spreadsheet reports with a JSON attachment.

**Table of contents**

.. contents::
   :local:

Features
========

* Per-spreadsheet schedule (days/weeks/months)
* Multiple recipients (partners + extra email addresses)
* JSON attachment (native spreadsheet data; open in the Spreadsheets app)
* Send-now button for manual trigger
* Automatic next-send computation

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Email Reports**
2. Create a schedule: spreadsheet, recipients, format, interval
3. The hourly cron sends due reports
4. Click **Send Now** to trigger immediately

Configuration
=============

Email template customizable via **Settings** > **Technical** > **Email Templates**.

Dependencies
============

* ``spreadsheet_oca``
* ``mail``

Known issues / Roadmap
======================

* PDF attachment (requires ``spreadsheet_pdf_report_oca``)
* Conditional send (only when data changes)

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
