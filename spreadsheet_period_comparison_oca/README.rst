.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_period_comparison_oca
   :alt: OCA/spreadsheet

Period Comparison Functions
===========================

|badge1| |badge2| |badge3|

Period-over-period comparison functions for dashboards.

**Table of contents**

.. contents::
   :local:

Features
========

* ``ODOO.PERCENT_CHANGE(current, previous)`` — % change
* ``ODOO.VARIANCE(current, previous)`` — absolute variance
* ``ODOO.GROWTH_ARROW(current, previous)`` — arrow + percentage (e.g., ``▲ 12.5%``)
* ``ODOO.YOY(current, last_year)`` — year-over-year growth

Usage
=====

::

    =ODOO.PERCENT_CHANGE(B2, B1)
    =ODOO.GROWTH_ARROW(B2, B1)
    =ODOO.YOY(Sales!B12, Sales_2025!B12)

The functions are listed under **Insert > Function > Odoo**.

When the previous value is 0, ``ODOO.PERCENT_CHANGE`` and ``ODOO.YOY`` return
``#DIV/0!`` (both values 0 give 0) and ``ODOO.GROWTH_ARROW`` shows ``—``. Use
``=IFERROR(ODOO.PERCENT_CHANGE(B2, B1), "n/a")`` to show a fallback value.
Numbers typed as text (``"1,5"``) and the percentage of ``ODOO.GROWTH_ARROW``
follow the spreadsheet locale (File > Settings).

Configuration
=============

No configuration needed.

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Month-over-month / quarter-over-quarter helpers

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
