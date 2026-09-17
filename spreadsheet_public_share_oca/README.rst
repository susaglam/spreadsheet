.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_public_share_oca
   :alt: OCA/spreadsheet

Spreadsheet Public Share
========================

|badge1| |badge2| |badge3|

Create token-based read-only public share links for external users.

**Table of contents**

.. contents::
   :local:

Features
========

* Secure token generation (URL-safe, 32-byte)
* Optional password protection: the password is stored as a salted PBKDF2 hash
  (the same passlib context as user passwords) and can never be read back
* Brute-force protection: after 5 wrong passwords from the same IP address for
  the same link, the prompt is locked for up to 15 minutes (counted from the
  first wrong password)
* The password is only accepted from the form (HTTP POST), never from the
  address bar, so it does not end up in proxy logs, browser history or
  ``Referer`` headers
* Optional expiry date
* Optional JSON download (re-imports losslessly)
* View count and last-viewed tracking
* HTML rendering with merge cells, styles, borders, for both the current
  o-spreadsheet format (``exportData()``: string cells, per-sheet style maps,
  squished ranges) and the legacy format (cell objects)

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Public Share Links**
2. Create a share: pick spreadsheet, optional password, expiry, download permission
3. Click **Show Link** to get the URL
4. Share with external users — no login required
5. Revoke by setting ``active = False`` or regenerating the token

Who can share what
~~~~~~~~~~~~~~~~~~

* You can only create a link for a spreadsheet you are allowed to **edit**
  (its owner, a contributor, or a Spreadsheet manager). Readers cannot publish
  a spreadsheet.
* Spreadsheet users only see and manage the links they created; Spreadsheet
  managers see every link.
* A link only opens while its creator is still allowed to edit the
  spreadsheet. When the creator is removed as contributor, or the spreadsheet
  changes owner, the link shows "Invalid or Expired Link". Links created before
  this rule existed on spreadsheets their creator cannot edit stop opening
  after the upgrade as well.
* Only a Spreadsheet manager can hand a link over to another user (change
  *Created By*) or set its token by hand; everybody else uses
  **Regenerate Link** for a new random token.
* Duplicating a password-protected link keeps its password.

What visitors see
~~~~~~~~~~~~~~~~~

* **Preview** – visible sheets only, limited to the first 100 rows and 26
  columns. Hidden sheets, the dashboards' ``Data`` helper sheet, hidden rows
  and columns, and folded row/column groups are never shown. The server has no
  spreadsheet engine: formula results appear as a dash, plain values, labels
  and styles are shown as stored.
* **Download (JSON)** – only when *Allow Download* is ticked. The file is the
  **complete workbook**, including hidden sheets, hidden rows and columns, and
  helper sheets such as ``Data``: formulas on the visible sheets read from
  them, so removing them would break the file. Only enable the download when
  the whole workbook may be published.
* A password-protected link asks for the password once per browser session;
  the download button then works without asking again.

Configuration
=============

Requires the base URL to be set in **Settings** > **General Settings** > **Website URL**.

Dependencies
============

* ``spreadsheet_oca``
* ``portal``

Known issues / Roadmap
======================

* The password attempt counter lives in each worker process's memory: with
  several workers an attacker gets the limit per worker, and a restart resets
  it.
* View-only iframe embed
* One-time-use links
* Watermarks

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
