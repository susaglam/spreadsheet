.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.2-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.2/spreadsheet_version_history_oca
   :alt: OCA/spreadsheet

Spreadsheet Version History
===========================

|badge1| |badge2| |badge3|

Snapshot, diff, and rollback spreadsheet versions with full audit trail.

**Table of contents**

.. contents::
   :local:

Features
========

* Manual snapshot creation via smart button
* Cell-level visual diff (added/changed/removed)
* One-click restore to any previous version
* Snapshot metadata: label, note, user, size
* Attachment-based storage

Usage
=====

1. Open a spreadsheet
2. Click the **New Snapshot** smart button to create a version
3. Click the **Versions** smart button to see the list
4. Open any version and review the **Visual Diff** tab to see changes
5. Click **Restore This Version** to roll back

Configuration
=============

No configuration needed. Snapshots are stored as attachments.

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Automatic daily snapshots
* Compare any two versions
* Snapshot retention policies

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
