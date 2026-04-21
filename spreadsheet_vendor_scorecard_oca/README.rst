.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_vendor_scorecard_oca
   :alt: OCA/spreadsheet

Vendor Performance Scorecard
============================

|badge1| |badge2| |badge3|

Supplier performance tracking with delivery, quality, and lead time metrics.

**Table of contents**

.. contents::
   :local:

Features
========

* Monthly automated scorecard computation
* Weighted score (40% delivery + 40% quality + 20% lead time)
* Color-coded list view (green > 80, yellow 50-80, red < 50)
* Pre-built dashboard with trend chart
* Top vendors list with drill-down
* Manual score override

Usage
=====

1. Install the module — a monthly cron will populate scorecards
2. View via **Purchase** > **Reporting** > **Vendor Scorecards**
3. Filter high performers (>= 80) or low performers (< 50)
4. Click any vendor to see detailed metrics and notes

Configuration
=============

* Adjust monthly cron via **Settings** > **Technical** > **Scheduled Actions**
* Weight customization requires overriding ``_compute_score``

Dependencies
============

* ``spreadsheet_oca``
* ``spreadsheet_dashboard``
* ``purchase_stock``

Known issues / Roadmap
======================

* Quality integration with MRP/QC module
* Vendor rating API

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
