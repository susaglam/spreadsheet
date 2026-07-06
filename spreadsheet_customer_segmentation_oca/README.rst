.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_customer_segmentation_oca
   :alt: OCA/spreadsheet

Customer Segmentation Dashboard
===============================

|badge1| |badge2| |badge3|

Customer overview with counts, a new-customer trend, and a top-customers list.

**Table of contents**

.. contents::
   :local:

Features
========

* Total Customers, Companies, New Customers (with vs-previous-period delta)
  and Individual Buyers scorecards
* Monthly new-customer trend chart
* Top Customers list
* Period (creation-date) filter

Usage
=====

After installation, the dashboard appears under **Dashboards**.

Configuration
=============

Auto-installs with ``sale``.

Dependencies
============

* ``spreadsheet_dashboard``
* ``sale``

Known issues / Roadmap
======================

* VIP and At-Risk customer scorecards
* Country filter
* Full RFM (Recency/Frequency/Monetary) scoring
* CLV (Customer Lifetime Value) computation
* Cohort analysis

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
