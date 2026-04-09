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
import os
import re
import time
import Shared.DC.ZRDB.THUNK
from DateTime import DateTime

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

    # Eigene OperationalError-Klasse, die NICHT von firebird.base.types.Error
    # erbt. firebird.base.types.Error definiert __getattr__ so, dass jedes
    # nicht gesetzte Attribut None zurueckgibt — inklusive __call__. Das
    # bringt Zopes DocumentTemplate zum Absturz: dessen safe_callable() prueft
    # per hasattr(e, '__call__') (was True liefert), und ruft dann e() auf
    # die Exception-Instanz auf. Da e.__call__ aber None ist, crasht das
    # Rendern von <dtml-var error_value> im ZMI-Test-Tab mit
    # "TypeError: 'NoneType' object is not callable" — ohne dass die
    # eigentliche Firebird-Fehlermeldung je beim User ankommt.
    # Die Original-firebird-driver-Exception haengt als __cause__ dran.
    class OperationalError(Exception):
        """FirebirdDA operational error for the firebird-driver backend."""
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
_FIREBIRD_DRIVER_RETRIES = 2
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
    # BrokenPipeError is a subclass of ConnectionError in Python 3.
    if isinstance(exc, (ConnectionError, InterfaceError)):
        return True
    codes = getattr(exc, 'gds_codes', None) or ()
    if any(c in RECONNECT_GDS_CODES for c in codes):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _RECONNECT_MARKERS)


def _caller_may_see_sql():
    """True if the current Zope user is a Manager — only then is it
    safe to include the offending SQL snippet in error messages.
    Anonymous / low-privilege callers (e.g. a public page that
    triggers a ZSQL Method which then errors) get a sanitised
    message without the query text. See
    reference/security-2026-04-09-03-error-sql-snippet-leak.md.

    Implemented via has_role(('Manager',)) rather than
    checkPermission, because checkPermission needs an Acquisition-
    wrapped context object — which the DB instance does not have."""
    try:
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser().has_role(('Manager',))
    except Exception:
        # Outside of a Zope request (e.g. unit test, startup) be
        # conservative: no SQL in errors.
        return False


def _format_firebird_driver_error(exc, query_string, include_sql=False):
    """Build an informative multi-line message from a firebird-driver
    exception, including the original driver message, GDS codes with
    symbolic names, and SQLSTATE/SQLCODE. The offending SQL is only
    appended when include_sql=True (i.e. caller is a Manager) — for
    everyone else a placeholder is emitted instead, so that an error
    bubbling into a public-facing page does not leak the query text
    (which may contain concatenated user input). The decision is made
    at the call site via _caller_may_see_sql()."""
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
            formatted.append(
                '%d (%s)' % (c, name) if name else str(c))
        parts.append('')
        parts.append('GDS codes: ' + ', '.join(formatted))

    sqlstate = getattr(exc, 'sqlstate', None)
    if sqlstate:
        if isinstance(sqlstate, bytes):
            sqlstate = sqlstate.decode('ascii', 'replace')
        parts.append('SQLSTATE: ' + str(sqlstate))

    sqlcode = getattr(exc, 'sqlcode', None)
    if sqlcode is not None:
        parts.append('SQLCODE: %d' % sqlcode)

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

# ISQL-Meta-Kommandos, die isql nativ unterstuetzt, Firebird-SQL aber nicht.
# Im ZMI-Test-Tab werden sie in echte System-Queries uebersetzt, damit sie
# genauso funktionieren wie in isql. Exakte Treffer: _ISQL_META_COMMANDS.
# Parametrisierte Varianten (show table NAME): _translate_isql_meta().
_ISQL_META_COMMANDS = {
    'show tables': (
        "SELECT TRIM(RDB$RELATION_NAME) AS TABLE_NAME "
        "FROM RDB$RELATIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL "
        "ORDER BY RDB$RELATION_NAME"
    ),
    'show views': (
        "SELECT TRIM(RDB$RELATION_NAME) AS VIEW_NAME "
        "FROM RDB$RELATIONS "
        "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NOT NULL "
        "ORDER BY RDB$RELATION_NAME"
    ),
    'show version': (
        "SELECT rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS VERSION "
        "FROM RDB$DATABASE"
    ),
    'show database': (
        "SELECT "
        "rdb$get_context('SYSTEM', 'DB_NAME') AS DATABASE_NAME, "
        "rdb$get_context('SYSTEM', 'ENGINE_VERSION') AS ENGINE_VERSION, "
        "rdb$get_context('SYSTEM', 'CURRENT_USER') AS CURRENT_USER "
        "FROM RDB$DATABASE"
    ),
}


# Firebird RDB$FIELDS.RDB$FIELD_TYPE -> lesbarer SQL-Typname.
# Deckt die gaengigen Spaltentypen ab; unbekannte Typen werden als
# numerischer Code ausgegeben.
_FB_FIELD_TYPE_CASE = """
  CASE f.RDB$FIELD_TYPE
    WHEN 7 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'SMALLINT'
      END
    WHEN 8 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'INTEGER'
      END
    WHEN 10 THEN 'FLOAT'
    WHEN 12 THEN 'DATE'
    WHEN 13 THEN 'TIME'
    WHEN 14 THEN 'CHAR(' || f.RDB$CHARACTER_LENGTH || ')'
    WHEN 16 THEN
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 1 THEN 'NUMERIC(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        WHEN 2 THEN 'DECIMAL(' || f.RDB$FIELD_PRECISION || ',' ||
                    (-f.RDB$FIELD_SCALE) || ')'
        ELSE 'BIGINT'
      END
    WHEN 27 THEN 'DOUBLE PRECISION'
    WHEN 35 THEN 'TIMESTAMP'
    WHEN 37 THEN 'VARCHAR(' || f.RDB$CHARACTER_LENGTH || ')'
    WHEN 261 THEN
      'BLOB SUB_TYPE ' ||
      CASE f.RDB$FIELD_SUB_TYPE
        WHEN 0 THEN 'BINARY'
        WHEN 1 THEN 'TEXT'
        ELSE CAST(f.RDB$FIELD_SUB_TYPE AS VARCHAR(10))
      END
    ELSE 'TYPE_' || CAST(f.RDB$FIELD_TYPE AS VARCHAR(10))
  END
"""

# Query fuer "show table NAME": Spaltenliste mit Typ, Laenge, Nullability,
# Default. {name} wird vom Translator mit dem geprueften Tabellennamen
# befuellt (immer schon validiert, daher kein SQL-Injection-Risiko).
_SHOW_TABLE_SQL = (
    "SELECT "
    "TRIM(rf.RDB$FIELD_NAME) AS FIELD_NAME, "
    + _FB_FIELD_TYPE_CASE.strip() + " AS FIELD_TYPE, "
    "CASE WHEN COALESCE(rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG) = 1 "
    "THEN 'NOT NULL' ELSE '' END AS NULLABLE, "
    "COALESCE(rf.RDB$DEFAULT_SOURCE, f.RDB$DEFAULT_SOURCE) AS DEFAULT_VALUE "
    "FROM RDB$RELATION_FIELDS rf "
    "JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME "
    "WHERE rf.RDB$RELATION_NAME = '{name}' "
    "ORDER BY rf.RDB$FIELD_POSITION"
)

# Gueltige unquoted Firebird-Identifier (Buchstaben, Ziffern, Underscore,
# Dollar; muss mit Buchstabe beginnen). Quoted Identifier ("FooBar") werden
# separat behandelt und case-preserving eingesetzt.
_IDENT_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_$]*$')
_SHOW_TABLE_RE = re.compile(
    r'^show\s+table\s+(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_$]*))\s*;?\s*$',
    re.IGNORECASE,
)


def _translate_isql_meta(query_string):
    """Wenn query_string einem bekannten ISQL-Meta-Kommando entspricht
    (case-insensitive, whitespace normalisiert, optional trailing ';'),
    liefere die entsprechende Firebird-SQL-Query. Sonst None."""
    stripped = query_string.strip()
    # 1) Exakte Treffer (show tables / show version / ...)
    key = ' '.join(stripped.rstrip(';').strip().lower().split())
    sql = _ISQL_META_COMMANDS.get(key)
    if sql is not None:
        return sql
    # 2) show table NAME  /  show table "Name"
    m = _SHOW_TABLE_RE.match(stripped)
    if m:
        quoted, unquoted = m.group(1), m.group(2)
        # Firebird speichert unquoted Identifier in Uppercase in den
        # System-Tabellen. Quoted Identifier behalten ihre Schreibweise.
        name = quoted if quoted is not None else unquoted.upper()
        # Sicherheitsnetz gegen SQL-Injection: nur erlaubte Zeichen im
        # Namen zulassen. Quoted Identifier duerfen Leerzeichen etc.
        # enthalten, daher hier nur das Apostroph als Terminator blocken.
        if "'" in name:
            return None
        return _SHOW_TABLE_SQL.format(name=name)
    return None


def fetchallmap(c):
    desc = c.description
    r = []
    for row in c.fetchall():
        d = {}
        for i in range(len(desc)):
            key = str(desc[i][0])
            try: d[key] = row[i].strip()
            except: d[key] = row[i]
        r.append(d)
    return r

def _convert_dsn(dsn):
    """Convert firebirdsql DSN format to firebird-driver format.

    firebirdsql:      host:port/path  host:/path  host/path
    firebird-driver:  host/port:path  host:/path  host:path
    """
    import re
    # host:port/path -> host/port:path
    m = re.match(r'^([^:/]+):(\d+)/(.+)$', dsn)
    if m:
        return '%s/%s:%s' % (m.group(1), m.group(2), m.group(3))
    # host:/path
    m = re.match(r'^([^:/]+):/(.+)$', dsn)
    if m:
        path = m.group(2)
        if '/' not in path:
            # single component like host:/alias -> host:alias
            return '%s:%s' % (m.group(1), path)
        return dsn
    # host/path -> host:path
    m = re.match(r'^([^:/]+)/(.+)$', dsn)
    if m:
        return '%s:%s' % (m.group(1), m.group(2))
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
        try:
            conn.close()
        except Exception:
            pass

    def __init__(self,connection):
        conn_args = {}
        for s in connection.split():
            k,v = s.split('=', 1)
            conn_args[k] = v
        if _DRIVER == 'firebird-driver' and 'dsn' in conn_args:
            conn_args['database'] = _convert_dsn(conn_args.pop('dsn'))
        self.conn_args = conn_args
        self.db_conn = []
        self.open()

    def _execute_query(self, query_string, max_rows):
        """Fuehrt die Query auf self.conn aus. Setzt voraus, dass die
        Verbindung offen ist. Der Cursor wird garantiert geschlossen.
        Fuer firebird-driver wird nach der Query committet, damit die
        naechste Query einen frischen READ_COMMITTED-Snapshot bekommt
        (fuer firebirdsql nicht noetig, dort ist Autocommit aktiv)."""
        # ISQL-Meta-Commands (show tables, show version, ...) in echte
        # Firebird-System-Queries uebersetzen, damit sie im Zope-Test-Tab
        # genauso funktionieren wie in isql.
        translated = _translate_isql_meta(query_string)
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
                if d is None: continue
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
            try:
                c.close()
            except Exception:
                pass

        if _DRIVER == 'firebird-driver':
            self.conn.commit()

        if desc is None:
            return (), ()

        items=[]
        for name, type, width, ds, p, scale, null_ok in desc:
            if type=='NUMBER':
                if scale==0: type='i'
                else: type='n'
            elif type=='DATE':
                type='d'
            else: type='s'
            items.append({
                'name': name,
                'type': type,
                'width': width,
                'null': null_ok,
                })

        return items, result

    def query(self, query_string, max_rows=9999999):
        if _DRIVER == 'firebirdsql':
            return self._query_firebirdsql(query_string, max_rows)
        return self._query_firebird_driver(query_string, max_rows)

    def _query_firebirdsql(self, query_string, max_rows):
        last_exc = None
        for i in range(_FIREBIRDSQL_RETRIES):
            # if necessary: retries for broken pipe,
            # invalid db handle or recv() packets problem
            # which can occur when the firebird server is restarted
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
                    raise OperationalError(str(e))
            except BrokenPipeError as e:
                last_exc = e
                self.close()
                self.open()
        raise OperationalError(
            'Firebird query failed after %d retries: %s'
            % (_FIREBIRDSQL_RETRIES, last_exc)
        ) from last_exc

    def _query_firebird_driver(self, query_string, max_rows):
        # Defensive: range(0) would skip the loop entirely and leave
        # last_exc as None, which would lead to a confusing
        # "raise ... from None". Treat misconfiguration as error.
        if _FIREBIRD_DRIVER_RETRIES < 1:
            raise OperationalError(
                '_FIREBIRD_DRIVER_RETRIES must be >= 1')
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
                    # Manager-level callers — see _caller_may_see_sql.
                    msg = _format_firebird_driver_error(
                        e, query_string,
                        include_sql=_caller_may_see_sql())
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
                   include_sql=_caller_may_see_sql()))
        raise OperationalError(msg) from last_exc
