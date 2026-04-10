FirebirdDA
==============

FirebirdDA https://github.com/nakagami/Products.FirebirdDA is Zope database
adapter for Interbase/Firebird.

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

