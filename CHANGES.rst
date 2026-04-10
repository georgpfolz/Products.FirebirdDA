Changelog
=========

0.8.0 (2026-04-09)
------------------

Python 3.11+ modernisation
~~~~~~~~~~~~~~~~~~~~~~~~~~
- Require Python 3.11 or newer.
- Code style: f-strings, ``contextlib.suppress``, proper exception
  chaining, remove unused imports and dead code.
- Unify docstring/comment style across the codebase.
- Extract ISQL meta command translation into a dedicated ``isql_meta``
  module.

Driver support
~~~~~~~~~~~~~~
- Add support for ``firebird-driver`` as alternative to ``firebirdsql``.
- Add ``gds_codes`` module for connection-loss detection with the
  ``firebird-driver`` backend.

Reliability
~~~~~~~~~~~
- Simplify connection retry logic and improve error resilience.
- Raise ``OperationalError`` when retries are exhausted instead of
  silently failing.

Error reporting
~~~~~~~~~~~~~~~
- Enrich ``firebird-driver`` errors with GDS codes, SQLSTATE, SQLCODE and
  SQL snippet.
- Add ISQL ``show`` meta commands in the Test tab.

Security
~~~~~~~~
- Remove unused connection cache that held plaintext credentials.
- Restrict SQL snippets in error messages to Manager callers.
- Restrict ISQL meta commands to Manager callers.

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
