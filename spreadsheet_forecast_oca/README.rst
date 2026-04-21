.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_forecast_oca
   :alt: OCA/spreadsheet

Spreadsheet Forecast Functions
==============================

|badge1| |badge2| |badge3|

Statistical forecasting functions: ODOO.FORECAST, ODOO.TREND, ODOO.MOVING_AVG.

**Table of contents**

.. contents::
   :local:

Features
========

* ``ODOO.FORECAST(target_x, known_y, known_x)`` — linear regression forecast
* ``ODOO.TREND(known_y, known_x, new_x)`` — trend line value
* ``ODOO.MOVING_AVG(range, window)`` — simple moving average

Usage
=====

Use the functions directly in any spreadsheet cell::

    =ODOO.FORECAST(13, B2:B12, A2:A12)
    =ODOO.TREND(B2:B12, A2:A12, 13)
    =ODOO.MOVING_AVG(B2:B12, 3)

Configuration
=============

No configuration needed.

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Seasonal decomposition
* ARIMA / Holt-Winters
* Confidence intervals

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
