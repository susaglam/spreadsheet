.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_api_oca
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

* Bearer token authentication (only a SHA-256 hash of each token is stored)
* Rate limiting (per-minute, configurable per token) and a per-IP throttle on
  failed authentication attempts
* Webhook delivery on spreadsheet creation, change and deletion, signed with
  HMAC-SHA256
* Webhook retry (up to 3 attempts) with logging
* Read endpoints: list, get, cells
* Token-scoped access to specific spreadsheets

Usage
=====

1. Create a token via **Spreadsheets** > **Configuration** > **API Tokens**
   and click **Generate Token**. Copy the secret from the dialog: it is shown
   only once (regenerate it if lost).
2. Optionally restrict to specific spreadsheets, set rate limit, add webhook URL
3. Call the API with the token in the ``Authorization`` header::

    curl -H "Authorization: Bearer YOUR_TOKEN" \
      https://your-odoo.example.com/api/spreadsheet/list

4. Webhooks POST to your URL when a spreadsheet the token user can read is
   created, changed or deleted. Verify the ``X-Spreadsheet-Signature`` header:
   ``sha256=`` + HMAC-SHA256 of the raw body, keyed with
   ``sha256(YOUR_TOKEN).hexdigest()``.

Security
========

* API calls run with the token user's access rights. Spreadsheet users can only
  create tokens for themselves; managers may choose another active internal
  user; only administrators may create, change or regenerate a token that runs
  as an administrator. The superuser, portal/public users and archived users
  are always refused.
* Tokens in the URL query string (``?token=``) are refused by default because
  URLs leak into logs. Set the system parameter
  ``spreadsheet_api_oca.allow_query_token`` to ``True`` only if a client cannot
  send headers.
* Failed authentications are throttled per client address (IPv6 per /64). A
  valid token is never refused because of someone else's failures on the same
  address; it is only subject to its own rate limit. Behind a reverse proxy,
  start Odoo with ``proxy_mode = True``, otherwise every client shares the
  proxy's address.
* Webhook targets must be public http(s) endpoints. The host is resolved again
  at every delivery, private/loopback/link-local/reserved addresses are
  refused, the connection is pinned to the checked IP, redirects are not
  followed and each call is stopped after 10 seconds in total. Webhooks connect
  directly: ``HTTP_PROXY``/``HTTPS_PROXY`` environment variables are ignored,
  because a proxy could reach internal addresses on the server's behalf. The
  response excerpt is visible to Spreadsheet managers only, and nobody can
  create or edit delivery events by hand.
* Events are only sent for tokens that have a secret (click **Generate Token**
  first), so every call can be signed.

Errors
======

Every error response is JSON with a stable shape::

    {"error": "Not found", "code": "not_found", "message": "..."}

``error`` keeps the labels of earlier versions, ``code`` is meant for programs
(``missing_token``, ``query_token_disabled``, ``invalid_token``,
``rate_limited``, ``forbidden_scope``, ``not_found``) and ``message`` explains
what failed and how to fix it.

Upgrading from 1.0.2
====================

* Existing tokens are converted to hashes automatically and keep working.
* The ``X-Spreadsheet-Token`` webhook header (which exposed the secret) is
  replaced by ``X-Spreadsheet-Signature``; update webhook receivers.
* Clients that pass the token as ``?token=`` now get HTTP 401. Switch them to
  the ``Authorization: Bearer <token>`` header. As a temporary workaround an
  administrator can set ``spreadsheet_api_oca.allow_query_token`` to ``True``;
  refused query tokens are logged with the token id so you can find the client.
* Undelivered webhook events about spreadsheets the token user cannot read are
  deleted during the upgrade.

Configuration
=============

* Webhook cron runs every 2 minutes (configurable)
* Rate limits are enforced in-process (per Odoo worker)
* ``spreadsheet_api_oca.failed_auth_per_minute`` (system parameter, default 20):
  failed authentications allowed per client IP per minute; 0 disables the
  throttle

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

* Codesnap

Contributors
~~~~~~~~~~~~

* Sukru Saglam <info@codesnap.nl>

Maintainers
~~~~~~~~~~~

This module is part of the OCA/spreadsheet project on GitHub.
