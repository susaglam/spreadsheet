.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_multicompany_oca
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
* Balances are the posted journal items of each company. A branch that is not
  listed on the profile is included in its parent company's column; list the
  branch too to give it its own column (it is then never counted twice)
* Elimination accounts must be configured manually. The report has one row per
  account code; for each selected account, the whole row with its code is
  cancelled in the Eliminations column for all consolidated companies together.
  The code is looked up in each consolidated company's own chart of accounts,
  so selecting the inter-company account ``1100`` of one company also cancels
  the ``1100`` balances of the other consolidated companies. Archived accounts
  selected for elimination are still eliminated
* Companies (or branches with posted journal items) that are left out get a
  warning at the top of the generated sheet, with the reason and the fix: no
  access for your user, archived company, or journal items your access rights
  do not allow you to read. Names of companies and accounts you cannot open
  yourself are not shown, only counted
* When a listed company is left out but you can access some of its branches,
  each of those branches gets its own column, so balances you are allowed to
  see are never dropped

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

* Codesnap

Contributors
~~~~~~~~~~~~

* Sukru Saglam <info@codesnap.nl>

Maintainers
~~~~~~~~~~~

This module is part of the OCA/spreadsheet project on GitHub.
