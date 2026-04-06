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
    from firebird.driver import OperationalError, DatabaseError as Error
    from firebird.driver import tpb as _make_tpb
    from firebird.driver.types import Isolation as _Isolation
elif _DRIVER == 'firebirdsql':
    import firebirdsql
    from firebirdsql import OperationalError
    _connect = firebirdsql.connect
    Error = firebirdsql.Error

with_system_flag=0

# Number of retries in the firebirdsql query loop.
# Covers brief outages during a Firebird server restart.
_FIREBIRDSQL_RETRIES = 5

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
        c = self.conn.cursor()
        try:
            queries=filter(None, [q.strip() for q in query_string.split('\0')])
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
        for i in range(_FIREBIRDSQL_RETRIES):
            # if necessary: retries for broken pipe,
            # invalid db handle or recv() packets problem
            # which can occur when the firebird server is restarted
            try:
                return self._execute_query(query_string, max_rows)

            except OperationalError as e:
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
            except BrokenPipeError:
                self.close()
                self.open()

    def _query_firebird_driver(self, query_string, max_rows):
        for attempt in range(2):
            try:
                if self.opened is None:
                    self.open()
                return self._execute_query(query_string, max_rows)

            except (Error, ConnectionError) as e:
                self.close()
                if attempt > 0:
                    raise Exception(
                        'Firebird server is not available: %s' % e)
