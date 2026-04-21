.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_template_oca
   :alt: OCA/spreadsheet

Spreadsheet Template System
===========================

|badge1| |badge2| |badge3|

Save any spreadsheet as a reusable template and create new spreadsheets from them.

**Table of contents**

.. contents::
   :local:

Features
========

* Save any existing spreadsheet as a template via File > "Save as Template"
* Browse templates in a kanban view with thumbnails and categories
* Create new spreadsheets from templates in one click
* Template categories (Sales, Finance, HR, Operations, General)
* Per-template usage counter
* Thumbnail support for visual identification
* Template Manager security group for governance

Usage
=====

1. Open any spreadsheet you want to save as template
2. Click **File** > **Save as Template** in the topbar
3. Choose a name and category
4. Browse templates via **Spreadsheets** > **Templates**
5. Click **Use Template** on any card to create a new spreadsheet from it

Configuration
=============

* Categories can be managed via **Spreadsheets** > **Configuration** > **Template Categories**
* Pre-built templates can be shipped via XML data files (see ``data/`` pattern)
* Assign users to the **Template Manager** group to grant full CRUD access

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Auto-generate thumbnails from spreadsheet snapshot
* Template sharing across companies

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
