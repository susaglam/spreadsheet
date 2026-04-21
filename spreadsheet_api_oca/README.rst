.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_api_oca
   :alt: OCA/spreadsheet

Spreadsheet REST API
====================

|badge1| |badge2| |badge3|

REST API for external integrations with rate limiting and webhook delivery.

**Table of contents**

.. contents::
   :local:

Features
========

* Bearer token authentication
* Rate limiting (per-minute, configurable per token)
* Webhook delivery on spreadsheet changes
* Webhook retry (up to 3 attempts) with logging
* Read endpoints: list, get, cells
* Token-scoped access to specific spreadsheets

Usage
=====

1. Create a token via **Spreadsheets** > **Configuration** > **API Tokens**
2. Optionally restrict to specific spreadsheets, set rate limit, add webhook URL
3. Call the API::

    curl -H "Authorization: Bearer YOUR_TOKEN" \
      https://your-odoo.example.com/api/spreadsheet/list

4. Webhooks POST to your URL when spreadsheets change

Configuration
=============

* Webhook cron runs every 2 minutes (configurable)
* Rate limits are enforced in-process (per Odoo worker)

Dependencies
============

* ``spreadsheet_oca``
* ``requests`` (Python library)

Known issues / Roadmap
======================

* Write endpoints (create/update)
* OAuth2 support
* Power BI / Google Sheets connectors

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
