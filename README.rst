FirebirdDA
==============

FirebirdDA https://github.com/nakagami/Products.FirebirdDA is Zope database
adapter for Interbase/Firebird.

Requirements
------------

- Python >= 3.11
- Zope 4

Installation
-----------------

buildout.cfg::

   eggs =
       ...
       Products.FirebirdDA

Driver Configuration
--------------------

FirebirdDA supports two Firebird Python drivers:

- ``firebirdsql`` (default, auto-detected)
- ``firebird-driver``

Set the ``FIREBIRDDA_DRIVER`` environment variable to select a driver
explicitly.  In a Zope deployment this is typically done in ``zope.conf``::

   <environment>
     FIREBIRDDA_DRIVER firebird-driver
   </environment>

If the variable is not set, FirebirdDA auto-detects: it tries to import
``firebirdsql`` first and falls back to ``firebird-driver``.

To use ``firebird-driver``, install it as an extra::

   pip install Products.FirebirdDA[firebird-driver]

Connection String
-----------------

The connection string uses space-separated ``key=value`` pairs::

   dsn=host:/path/to/database.fdb user=sysdba password=masterkey

The ``dsn``, ``user`` and ``password`` keys are passed directly to the
driver's ``connect()`` function.  When using ``firebird-driver``, the
DSN is automatically converted from ``firebirdsql`` format
(``host:/path``) to ``firebird-driver`` format (``host:path``).

Test Tab
--------

The ZMI Test tab supports ISQL-style meta commands (Manager only):

- ``show tables`` — list all user tables
- ``show table NAME`` — show columns of a table
- ``show views`` — list all user views
- ``show version`` — show Firebird engine version
- ``show database`` — show database name, engine version and current user

