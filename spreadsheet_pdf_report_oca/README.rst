.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_pdf_report_oca
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
* Cell styling preserved as displayed (bold, italic, text/fill colors including
  conditional formats and table styles, alignment, font size)
* Merge cell support via colspan/rowspan
* Hidden sheets are left out of the PDF
* Landscape A4 paper format (configurable, see below)
* Full UTF-8 support (Turkish, Chinese, Arabic characters)

Usage
=====

1. Open any spreadsheet
2. Click **File** > **Download PDF** in the topbar
3. PDF downloads with all computed values, styles, and company branding

Configuration
=============

* Paper format: open **Settings** > **Technical** > **Actions** >
  **Reports** >
  *Spreadsheet PDF Export* and change its *Paper Format* (default
  *Spreadsheet Landscape A4*: A4 landscape, 15 mm / 7 mm margins).
* PDF engine: the export uses the same engine as every Odoo report, i.e. the
  system parameter ``report.pdf_engine_default``. To use a specific engine for
  this export only, set the *Report Type* of *Spreadsheet PDF Export* to
  *PDF (Wkhtmltopdf)* or *PDF (Paper Muncher)*.
* *Spreadsheet PDF Export* only carries these settings. Printing it directly
  (``/report/...``) shows a static page that points to **File** > **Download
  PDF**; the export itself is rendered by the ``/spreadsheet/pdf`` controller.
* Logo is taken from the current company's ``logo`` field

Security and limits
===================

* Only internal users can export; portal and public users get a clear refusal.
* The request is CSRF-protected (the web client sends the token automatically).
* Cell styles are validated server-side: colors must be ``#rgb``, ``#rrggbb``,
  ``rgb()`` or ``rgba()``, alignment ``left``/``center``/``right``, font size a
  number from 1 to 400 (the spreadsheet editor's range). Anything else is
  refused, so no CSS can be injected into the PDF.
* Size limits per export: 50 sheets, 1000 rows per sheet, 200 cells per row,
  50,000 cells in total and 8 MB of data. The limits apply to the table the PDF
  engine lays out: a merged cell counts for every cell it covers, and a row's
  width includes cells merged down from the rows above. The used range of
  every visible sheet counts, so one value far away (e.g. in AZ1000) can reach
  the total limit. The editor checks the total before uploading. Larger
  spreadsheets get a message suggesting to hide sheets, remove unused ranges or
  use **Download XLSX**.

Dependencies
============

* ``spreadsheet_oca``
* A PDF engine: ``base_report_wkhtmltox`` (auto-installed, needs the
  ``wkhtmltopdf`` program) or ``base_report_paper_muncher``. Without a usable
  engine the export shows a message explaining what to install.

Known issues / Roadmap
======================

* Per-sheet page breaks
* Cover page with table of contents
* Password-protected PDF output

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
