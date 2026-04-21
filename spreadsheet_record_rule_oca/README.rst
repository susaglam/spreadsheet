.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_record_rule_oca
   :alt: OCA/spreadsheet

Dashboard Record Rule Filter
============================

|badge1| |badge2| |badge3|

Apply user-based domain filters to spreadsheet dashboard data sources.

**Table of contents**

.. contents::
   :local:

Features
========

* Define additional domain expressions per dashboard × model × group
* Rules combined with AND against existing data source domains
* Supports ``user`` variable in domain expressions
* Per-group rule activation
* Domain expression validation

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Dashboard Data Filters**
2. Create a rule: select dashboard, model (e.g., ``sale.order``), group
3. Enter a domain, e.g., ``[('user_id', '=', user.id)]``
4. Rules auto-apply when users open the dashboard

Configuration
=============

Only users matching all the rule's groups see their filters applied.

Dependencies
============

* ``spreadsheet_oca``
* ``spreadsheet_dashboard``

Known issues / Roadmap
======================

* Rules for non-dashboard spreadsheets
* Company-based rules

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
