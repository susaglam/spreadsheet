.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_multicompany_oca
   :alt: OCA/spreadsheet

Multi-Company Consolidation
===========================

|badge1| |badge2| |badge3|

Generate consolidated financial reports across multiple companies with inter-company elimination.

**Table of contents**

.. contents::
   :local:

Features
========

* Define consolidation profiles with companies and elimination accounts
* Auto-generate a spreadsheet with per-company and consolidated columns
* Multi-currency conversion to a chosen consolidation currency
* Inter-company account elimination
* Opens as standard editable spreadsheet

Usage
=====

1. Go to **Spreadsheets** > **Consolidation**
2. Create a profile: select companies, elimination accounts, target currency
3. Click **Generate Consolidated Report** — a new spreadsheet opens with the data

Configuration
=============

* Requires access to account data across multiple companies
* Elimination accounts must be configured manually

Dependencies
============

* ``spreadsheet_oca``
* ``account``

Known issues / Roadmap
======================

* Automated consolidation cron
* IFRS/GAAP mapping
* Sub-consolidation layers

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
