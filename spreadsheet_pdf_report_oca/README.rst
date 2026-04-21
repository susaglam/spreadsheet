.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_pdf_report_oca
   :alt: OCA/spreadsheet

Spreadsheet PDF Report
======================

|badge1| |badge2| |badge3|

Export spreadsheets to professional PDF with company logo, styles, and UTF-8 support.

**Table of contents**

.. contents::
   :local:

Features
========

* **File** > **Download PDF** menu in the spreadsheet editor
* Extracts evaluated cell values (including formula results) from the JS model
* QWeb template with company logo header and footer
* Cell styling preserved (bold, italic, colors, alignment, font size)
* Merge cell support via colspan/rowspan
* Landscape A4 paper format
* Full UTF-8 support (Turkish, Chinese, Arabic characters)

Usage
=====

1. Open any spreadsheet
2. Click **File** > **Download PDF** in the topbar
3. PDF downloads with all computed values, styles, and company branding

Configuration
=============

* Paper format can be changed via **Settings** > **Technical** > **Paper Format**
* Logo is taken from the current company's ``logo`` field

Dependencies
============

* ``spreadsheet_oca``
* ``wkhtmltopdf`` (Odoo standard)

Known issues / Roadmap
======================

* Per-sheet page breaks
* Cover page with table of contents
* Password-protected PDF output

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
