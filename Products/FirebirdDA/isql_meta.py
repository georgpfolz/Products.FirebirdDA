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
"""ISQL meta command translation.

isql supports a handful of meta commands (``show tables``,
``show table NAME``, ``show version``, ...) that plain Firebird SQL
does not understand. In the ZMI Test tab of the FirebirdDA Connection
we translate them into real system-table queries so they work the same
way as in isql. Exact matches live in ``ISQL_META_COMMANDS``;
parameterised variants (``show table NAME``) are handled by
``translate_isql_meta()`` via ``SHOW_TABLE_RE`` and ``SHOW_TABLE_SQL``.
"""
import re


# ISQL meta commands that isql supports natively but Firebird SQL does
# not. Exact matches go here; parameterised variants (show table NAME)
# are handled in translate_isql_meta().
ISQL_META_COMMANDS = {
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


# Firebird RDB$FIELDS.RDB$FIELD_TYPE -> readable SQL type name.
# Covers the common column types; unknown types are emitted as a
# numeric code.
FB_FIELD_TYPE_CASE = """
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

# Query for "show table NAME": column list with type, length, nullability,
# default. {name} is filled in by the translator with the validated table
# name (always pre-validated, so no SQL-injection risk).
SHOW_TABLE_SQL = (
    "SELECT "
    "TRIM(rf.RDB$FIELD_NAME) AS FIELD_NAME, "
    + FB_FIELD_TYPE_CASE.strip() + " AS FIELD_TYPE, "
    "CASE WHEN COALESCE(rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG) = 1 "
    "THEN 'NOT NULL' ELSE '' END AS NULLABLE, "
    "COALESCE(rf.RDB$DEFAULT_SOURCE, f.RDB$DEFAULT_SOURCE) AS DEFAULT_VALUE "
    "FROM RDB$RELATION_FIELDS rf "
    "JOIN RDB$FIELDS f ON rf.RDB$FIELD_SOURCE = f.RDB$FIELD_NAME "
    "WHERE rf.RDB$RELATION_NAME = '{name}' "
    "ORDER BY rf.RDB$FIELD_POSITION"
)

SHOW_TABLE_RE = re.compile(
    r'^show\s+table\s+(?:"([^"]+)"|([A-Za-z][A-Za-z0-9_$]*))\s*;?\s*$',
    re.IGNORECASE,
)


def translate_isql_meta(query_string):
    """Translate an ISQL meta command to a Firebird SQL query.

    If query_string matches a known ISQL meta command
    (case-insensitive, whitespace normalised, optional trailing ';'),
    return the corresponding Firebird SQL query.  Otherwise return
    None.
    """
    stripped = query_string.strip()
    # 1) Exact matches (show tables / show version / ...)
    key = ' '.join(stripped.rstrip(';').strip().lower().split())
    sql = ISQL_META_COMMANDS.get(key)
    if sql is not None:
        return sql
    # 2) show table NAME  /  show table "Name"
    m = SHOW_TABLE_RE.match(stripped)
    if m:
        quoted, unquoted = m.group(1), m.group(2)
        # Firebird stores unquoted identifiers in uppercase in the
        # system tables. Quoted identifiers keep their case.
        name = quoted if quoted is not None else unquoted.upper()
        # SQL-injection safety net: only allow safe characters in the
        # name. Quoted identifiers may contain spaces etc., so here we
        # only block the apostrophe as a string terminator.
        if "'" in name:
            return None
        return SHOW_TABLE_SQL.format(name=name)
    return None
