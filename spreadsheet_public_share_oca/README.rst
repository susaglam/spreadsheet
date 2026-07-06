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
* Optional password protection
* Optional expiry date
* Optional JSON download (re-imports losslessly)
* View count and last-viewed tracking
* HTML rendering with merge cells, styles, borders

Usage
=====

1. Go to **Spreadsheets** > **Configuration** > **Public Share Links**
2. Create a share: pick spreadsheet, optional password, expiry, download permission
3. Click **Show Link** to get the URL
4. Share with external users — no login required
5. Revoke by setting ``active = False`` or regenerating the token

Configuration
=============

Requires the base URL to be set in **Settings** > **General Settings** > **Website URL**.

Dependencies
============

* ``spreadsheet_oca``
* ``spreadsheet_kpi_alert_oca``
* ``portal``

Known issues / Roadmap
======================

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
