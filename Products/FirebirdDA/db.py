##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
import contextlib
import os
import re
import time
import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

from .isql_meta import translate_isql_meta

# Driver selection via environment variable FIREBIRDDA_DRIVER
# Supported values: 'firebirdsql', 'firebird-driver'
# If not set: auto-detect (firebirdsql preferred for backwards compatibility)
_DRIVER = os.environ.get('FIREBIRDDA_DRIVER', '').strip()

if not _DRIVER:
    # Auto-detect: firebirdsql preferred for backwards compatibility
    try:
        import firebirdsql
        _DRIVER = 'firebirdsql'
    except ImportError:
        _DRIVER = 'firebird-driver'

if _DRIVER == 'firebird-driver':
    from firebird.driver import connect as _connect
    from firebird.driver import DatabaseError as Error
    from firebird.driver import InterfaceError
    from firebird.driver import tpb as _make_tpb
    from firebird.driver.types import Isolation as _Isolation
    from .gds_codes import RECONNECT_GDS_CODES, gds_name

    class OperationalError(Exception):
        """FirebirdDA operational error for the firebird-driver backend.

        Does NOT inherit from firebird.base.types.Error, because that class
        defines __getattr__ such that any unset attribute returns None —
        including __call__.  This crashes Zope's DocumentTemplate:
        safe_callable() checks hasattr(e, '__call__') (which returns True)
        and then calls e() on the exception instance.  Since e.__call__ is
        None, rendering <dtml-var error_value> in the ZMI Test tab crashes
        with "TypeError: 'NoneType' object is not callable" — without the
        actual Firebird error message ever reaching the user.

        The original firebird-driver exception is chained via __cause__.
        """
        pass
elif _DRIVER == 'firebirdsql':
    import firebirdsql
    from firebirdsql import OperationalError
    _connect = firebirdsql.connect
    Error = firebirdsql.Error

with_system_flag=0

# Number of retries in the firebirdsql query loop.
# Covers brief outages during a Firebird server restart.
_FIREBIRDSQL_RETRIES = 5

# firebird-driver query loop: how many attempts and how long to wait
# between them when a transient connection-loss is detected.
_FIREBIRD_DRIVER_RETRIES = 2  # must be >= 1
_FIREBIRD_DRIVER_RETRY_DELAY = 0.5  # seconds

# Substring fallback markers (lower-cased) used to recognise
# connection-loss situations on exceptions that do not carry
# gds_codes (e.g. Python-level socket errors raised before the
# server could return a status vector).
_RECONNECT_MARKERS = (
    'broken pipe',
    'connection lost',
    'connection closed',
    'network error',
    'too many open handles',
    'shutdown',
)


def _is_firebird_driver_connection_lost(exc):
    """True if exc indicates a transient connection-loss situation
    where a reconnect + single retry makes sense."""
    # BrokenPipeError is a subclass of ConnectionError.
    if isinstance(exc, (ConnectionError, InterfaceError)):
        return True
    codes = getattr(exc, 'gds_codes', None) or ()
    if any(c in RECONNECT_GDS_CODES for c in codes):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _RECONNECT_MARKERS)


def _caller_is_manager():
    """True if the current Zope user has the Manager role.

    Gates two Manager-only conveniences in this DA: including the
    offending SQL snippet in error messages, and translating ISQL
    meta commands (show tables / show table NAME / ...) into
    system-table queries in _execute_query.  Non-Manager callers get
    sanitised errors without SQL and see meta commands passed
    through to Firebird as-is (producing a normal parse error).

    Uses has_role(('Manager',)) instead of checkPermission because
    checkPermission needs an Acquisition-wrapped context object,
    which the DB instance does not have.
    """
    try:
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser().has_role(('Manager',))
    except Exception:
        # Outside a Zope request (unit test, startup) be conservative:
        # no SQL in errors.
        return False


def _format_firebird_driver_error(exc, query_string, include_sql=False):
    """Format a firebird-driver exception as a multi-line message.

    Includes the driver message, GDS codes, SQLSTATE, SQLCODE and
    optionally the SQL text.  include_sql is gated by
    _caller_is_manager() at the call site: non-Manager callers get a
    placeholder instead of the query text, so errors bubbling into a
    public-facing page do not leak SQL that may contain concatenated
    user input.
    """
    parts = ['Firebird query failed.']

    orig = str(exc).strip()
    if orig:
        parts.append('')
        parts.append('Error:')
        parts.append(orig)

    codes = getattr(exc, 'gds_codes', None) or ()
    if codes:
        formatted = []
        for c in codes:
            name = gds_name(c)
            formatted.append(f'{c} ({name})' if name else str(c))
        parts.append('')
        parts.append(f"GDS codes: {', '.join(formatted)}")

    sqlstate = getattr(exc, 'sqlstate', None)
    if sqlstate:
        if isinstance(sqlstate, bytes):
            sqlstate = sqlstate.decode('ascii', 'replace')
        parts.append(f'SQLSTATE: {sqlstate}')

    sqlcode = getattr(exc, 'sqlcode', None)
    if sqlcode is not None:
        parts.append(f'SQLCODE: {sqlcode}')

    if query_string and include_sql:
        snippet = query_string.strip()
        max_len = 2000
        if len(snippet) > max_len:
            snippet = snippet[:max_len] + '\n  ... (truncated)'
        parts.append('')
        parts.append('SQL:')
        parts.append(snippet)
    elif query_string:
        parts.append('')
        parts.append('SQL: <hidden — caller lacks Manager role>')

    return '\n'.join(parts)

def fetchallmap(c):
    """Fetch all rows from cursor c as a list of {column_name: value} dicts.

    Not called anywhere in this product and not exposed to Zope.
    Kept for backward compatibility with third-party code that may
    import it directly.
    """
    desc = c.description
    r = []
    for row in c.fetchall():
        d = {}
        for col, value in zip(desc, row):
            key = str(col[0])
            try:
                d[key] = value.strip()
            except AttributeError:
                d[key] = value
        r.append(d)
    return r

def _convert_dsn(dsn):
    """Convert firebirdsql DSN format to firebird-driver format.

    firebirdsql:      host:port/path  host:/path  host/path
    firebird-driver:  host/port:path  host:/path  host:path
    """
    # host:port/path -> host/port:path
    m = re.match(r'^([^:/]+):(\d+)/(.+)$', dsn)
    if m:
        return f'{m.group(1)}/{m.group(2)}:{m.group(3)}'
    # host:/path
    m = re.match(r'^([^:/]+):/(.+)$', dsn)
    if m:
        path = m.group(2)
        if '/' not in path:
            # single component like host:/alias -> host:alias
            return f'{m.group(1)}:{path}'
        return dsn
    # host/path -> host:path
    m = re.match(r'^([^:/]+)/(.+)$', dsn)
    if m:
        return f'{m.group(1)}:{m.group(2)}'
    return dsn


class DB(Shared.DC.ZRDB.THUNK.THUNKED_TM):
    database_error=Error
    opened=None

    conn = None

    def open(self):
        if self.conn is not None:
            self.close()
        self.conn = _connect(**self.conn_args)
        if _DRIVER == 'firebirdsql':
            self.conn.set_autocommit(True)
        else:
            self.conn.main_transaction.default_tpb = _make_tpb(_Isolation.READ_COMMITTED)
        self.opened=DateTime()

    def close(self):
        conn = self.conn
        self.conn = None
        self.opened = None
        if conn is None:
            return
        with contextlib.suppress(Exception):
            conn.close()

    def __init__(self,connection):
        conn_args = dict(
            s.split('=', 1) for s in connection.split()
        )
        if _DRIVER == 'firebird-driver' and 'dsn' in conn_args:
            conn_args['database'] = _convert_dsn(conn_args.pop('dsn'))
        self.conn_args = conn_args
        self.db_conn = []
        self.open()

    def _execute_query(self, query_string, max_rows):
        """Execute query_string on self.conn and return (items, rows).

        Translates ISQL meta commands (show tables, show version, ...)
        into real Firebird system queries so they work the same in the
        Zope Test tab as in isql.  Manager callers only — same policy
        as the SQL-in-error-message logic.  Non-Manager callers see
        the query unchanged and get a normal Firebird parse error,
        just like before the ISQL meta translation existed.
        """
        if _caller_is_manager():
            translated = translate_isql_meta(query_string)
            if translated is not None:
                query_string = translated
        c = self.conn.cursor()
        try:
            queries=[q for q in (s.strip() for s in query_string.split('\0')) if q]
            if not queries:
                raise OperationalError('empty query')
            desc=None
            result=[]
            for qs in queries:
                c.execute(qs)

                d=c.description
                if d is None:
                    continue
                if desc is None: desc=d
                elif d != desc:
                    raise OperationalError(
                        'Multiple incompatible selects in '
                        'multiple sql-statement query'
                        )
                if len(result) < max_rows:
                    r = c.fetchmany(max_rows-len(result))
                    if r:
                        result += r
        finally:
            with contextlib.suppress(Exception):
                c.close()

        if _DRIVER == 'firebird-driver':
            # Commit so the next query gets a fresh READ_COMMITTED
            # snapshot. Not needed for firebirdsql (autocommit is on).
            self.conn.commit()

        if desc is None:
            return (), ()

        items=[]
        for name, type_, width, ds, p, scale, null_ok in desc:
            if type_=='NUMBER':
                if scale==0: type_='i'
                else: type_='n'
            elif type_=='DATE':
                type_='d'
            else: type_='s'
            items.append({
                'name': name,
                'type': type_,
                'width': width,
                'null': null_ok,
                })

        return items, result

    def query(self, query_string, max_rows=9999999):
        """Public entry point — dispatch to the active driver backend."""
        if _DRIVER == 'firebirdsql':
            return self._query_firebirdsql(query_string, max_rows)
        return self._query_firebird_driver(query_string, max_rows)

    def _query_firebirdsql(self, query_string, max_rows):
        """Run query via firebirdsql with retries for transient errors.

        Retries cover broken pipe, invalid db handle and recv() packet
        problems that occur briefly when the Firebird server is
        restarted.
        """
        last_exc = None
        for i in range(_FIREBIRDSQL_RETRIES):
            try:
                return self._execute_query(query_string, max_rows)

            except OperationalError as e:
                last_exc = e
                if e and e.args[0] in ('Can not recv() packets',
                    # these error only occurs very briefly
                    # after the firebird server is restarted
                    # soon thereafter, there will be a broken pipe error
                    '_op_allocate_statement() Invalid db handle'):
                    time.sleep(1)
                    self.close()
                    self.open()
                elif e and 'too many open handles to database' in e.args[0]:
                    self.close()
                    self.open()
                else:
                    raise OperationalError(str(e)) from e
            except BrokenPipeError as e:
                last_exc = e
                self.close()
                self.open()
        raise OperationalError(
            f'Firebird query failed after {_FIREBIRDSQL_RETRIES} '
            f'retries: {last_exc}'
        ) from last_exc

    def _query_firebird_driver(self, query_string, max_rows):
        """Run query via firebird-driver with enrichment of error messages.

        Includes a retry loop for transient connection-loss situations.
        """
        last_exc = None
        for attempt in range(_FIREBIRD_DRIVER_RETRIES):
            try:
                if self.opened is None:
                    self.open()
                return self._execute_query(query_string, max_rows)

            except (Error, ConnectionError) as e:
                if not _is_firebird_driver_connection_lost(e):
                    # SQL / logic error: enrich and re-raise so the
                    # user sees the offending SQL plus driver context
                    # (GDS codes, SQLSTATE, SQLCODE) in the ZMI Test
                    # tab. The original exception is chained via
                    # __cause__. SQL snippet is only included for
                    # Manager-level callers — see _caller_is_manager.
                    msg = _format_firebird_driver_error(
                        e, query_string,
                        include_sql=_caller_is_manager())
                    raise OperationalError(msg) from e
                last_exc = e
                self.close()
                if attempt < _FIREBIRD_DRIVER_RETRIES - 1:
                    time.sleep(_FIREBIRD_DRIVER_RETRY_DELAY)

        # All retries exhausted: enrich the last connection error too,
        # so the user gets the same informative diagnosis instead of a
        # generic "server not available".
        msg = ('Connection to Firebird lost; reconnect attempts '
               'exhausted.\n\n' +
               _format_firebird_driver_error(
                   last_exc, query_string,
                   include_sql=_caller_is_manager()))
        raise OperationalError(msg) from last_exc
