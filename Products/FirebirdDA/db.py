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
    from firebird.driver.core import TPB
elif _DRIVER == 'firebirdsql':
    import firebirdsql
    from firebirdsql import OperationalError
    _connect = firebirdsql.connect
    Error = firebirdsql.Error

with_system_flag=0

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

    def open(self):
        self.conn = _connect(**self.conn_args)
        if _DRIVER == 'firebirdsql':
            self.conn.set_autocommit(True)
        else:
            tpb = TPB(auto_commit=True)
            self.conn.default_tpb = tpb.get_buffer()
        self.opened=DateTime()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.opened = None

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

    def query(self,query_string, max_rows=9999999):
        for attempt in range(2):
            try:
                if self.opened is None:
                    self.open()
                c = self.conn.cursor()

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

            except (Error, ConnectionError) as e:
                self.close()
                if attempt > 0:
                    raise Exception(
                        'Firebird server is not available: %s' % e)
