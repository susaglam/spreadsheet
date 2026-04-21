.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_scheduled_refresh_oca
   :alt: OCA/spreadsheet

Scheduled Spreadsheet Refresh
=============================

|badge1| |badge2| |badge3|

Periodically refresh spreadsheet data sources via cron.

**Table of contents**

.. contents::
   :local:

Features
========

* Per-spreadsheet refresh schedule
* Configurable interval (hours, days, weeks, months)
* Bus notification pushed to connected clients
* Next-refresh tracking

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Refresh Schedules**
2. Create a schedule: select spreadsheet, interval
3. The hourly cron triggers due refreshes
4. Connected browser clients receive a live update signal

Configuration
=============

Cron interval (default: hourly) configurable via **Settings** > **Technical** > **Scheduled Actions**.

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Per-datasource refresh (pivot/list level)
* Failure retry

Credits
=======

Authors
~~~~~~~

* Badkamertien

Contributors
~~~~~~~~~~~~

* Sukru Saglam <developer1@badkamertien.nl>

Maintainers
~~~~~~~~~~~

This module is part of the OCA/spreadsheet project on GitHub.
