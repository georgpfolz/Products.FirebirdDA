Changelog
=========

0.8.0 (2026-04-09)
------------------

Python 3.11+ modernisation
~~~~~~~~~~~~~~~~~~~~~~~~~~
- Require Python 3.11 or newer.
- Replace ``%``-formatting with f-strings.
- Replace ``try/except Exception: pass`` with ``contextlib.suppress`` in
  ``DB.close`` and the cursor cleanup in ``_execute_query``.
- Rewrite ``fetchallmap`` to iterate via ``zip(desc, row)`` instead of
  ``range(len(desc))``.
- Build ``conn_args`` in ``DB.__init__`` via a dict comprehension.
- Chain the re-raised ``OperationalError`` in the ``firebirdsql`` retry
  loop via ``raise ... from e`` for correct tracebacks.
- Rename the ``type`` loop variable in ``_execute_query`` to ``type_`` to
  stop shadowing the builtin.
- Remove the unused ``_IDENT_RE`` regex, the duplicated ``import re``
  inside ``_convert_dsn`` and an unused ``import sys`` in ``DA.py``.
- ``setup.py``: read ``README.rst`` / ``CHANGES.rst`` via
  ``pathlib.Path.read_text`` with an explicit UTF-8 encoding instead of
  bare ``open().read()``.
- Unify the docstring/comment style (one-line docstrings
  stating *what*, inline comments explaining *why*).
- Extract ISQL meta command translation (constants, regex, SQL templates
  and ``translate_isql_meta()``) from ``db.py`` into a dedicated
  ``isql_meta`` module, following the same pattern as ``gds_codes``.

Driver support
~~~~~~~~~~~~~~
- Add support for ``firebird-driver`` as alternative to ``firebirdsql``,
  selectable via the ``FIREBIRDDA_DRIVER`` environment variable. Uses
  READ_COMMITTED TPB with an explicit ``commit()`` after each query to
  guarantee a fresh snapshot for the next query. [11228eb]
- Add ``gds_codes`` module with symbolic constants for the most relevant
  Firebird GDS codes and a ``RECONNECT_GDS_CODES`` set used by the
  ``firebird-driver`` path to detect connection loss. [11228eb]

Reliability
~~~~~~~~~~~
- Simplify connection retry logic and improve error resilience. [cba035f]
- Raise ``OperationalError`` when ``firebirdsql`` retries are exhausted
  instead of silently failing. [6231ee0]
- Replace bare ``except`` in ``fetchallmap`` with ``AttributeError``.
  [0ce656a]

Error reporting
~~~~~~~~~~~~~~~
- Enrich ``firebird-driver`` errors with GDS codes, SQLSTATE, SQLCODE and
  SQL snippet. [a9c7afd]
- Add ISQL ``show`` meta commands in the Test tab. [e7cf6c7]

Security
~~~~~~~~
- Remove unused ``_connections`` cache that held plaintext credentials.
  [ac00513]
- Hide SQL snippet in errors for non-Manager callers. [c13d3ce]
- Restrict ISQL meta command translation to Manager callers. [9373211]

0.7.1 (2024-01-04)
------------------
- Reopen connection on "too many handles" errors and fix
  ``OperationalError`` output. [044144c]
- Add connection retries in ``query()`` method. [8cd2b8b]

0.7.0 (2020-06-20)
------------------
- Port to Zope 4 and Python 3. [1e2033f]
- Refactoring of forms, classifiers and imports. [9c7af69, 0984739, c2f8eda,
  1e080d7]

0.6.x (2014)
------------
- Disable connection pool (do not reuse connections across requests).
  [3fefc46]
- Enable ``set_autocommit(True)``. [a2e57f5]
- Declare ``Products`` namespace package. [3ebe2f8]
- Add trove classifiers. [0c61502]

0.5.0 (2012-01)
---------------
- Initial release by Hajime Nakagami, forked from ``ZKinterbasdbDA 0.5.0``
  and switched to the ``firebirdsql`` driver. [77e9b51, d7f6336]
