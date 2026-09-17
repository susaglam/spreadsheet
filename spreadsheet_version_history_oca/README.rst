.. |badge1| image:: https://img.shields.io/badge/maturity-Alpha-red.png
   :target: https://odoo-community.org/page/development-status
   :alt: Alpha
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/version-saas~19.4-blue.png
   :target: https://github.com/OCA/spreadsheet/tree/saas-19.4/spreadsheet_version_history_oca
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

Access rights
=============

A snapshot holds a full copy of its spreadsheet and can be restored over it, so
its access follows the spreadsheet's own sharing:

* Everyone who can open the spreadsheet (its owner, contributors and readers,
  and spreadsheet managers of its company) can see its snapshots and their diff.
* Only users who can edit the spreadsheet (its owner, contributors and
  spreadsheet managers) can take a snapshot, edit a snapshot's name, label and
  note, move a snapshot to another spreadsheet they can edit, or restore it.
* Only spreadsheet managers can delete snapshots.
* The captured content of a snapshot and the user who captured it cannot be
  changed once the snapshot exists.

Dependencies
============

* ``spreadsheet_oca``

Known issues / Roadmap
======================

* Automatic daily snapshots
* Compare any two versions
* Snapshot retention policies
* The visual diff compares cell contents (values and formulas) only;
  formatting-only changes (styles, number formats, borders) are not listed yet.
  Compressed cell runs saved by the spreadsheet editor are expanded on the
  server; the rare run that cannot be expanded is shown as stored, with a
  warning above the diff.
* To keep the snapshot form fast, each side of the diff expands at most
  250,000 cells and a bounded amount of formula work (about 600 KB of stored
  formulas, far more than any dashboard shipped with Odoo), and at most 2,000
  differing cells are listed. Beyond that, the remaining entries are shown as
  stored with a "too large" warning; the added/changed/removed counters still
  include the differences that are not listed.

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
