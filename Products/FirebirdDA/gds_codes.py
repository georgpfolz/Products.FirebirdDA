from __future__ import annotations

from enum import IntEnum


class GDSCode(IntEnum):
    """Firebird GDS/ISC error codes as symbolic constants.

    Extracted from the official Firebird headers (iberror.h / ISCConstants.java).
    Contains only the most commonly used codes – perfect for everyday use with firebird-driver.

    Usage:
        if GDSCode.UNIQUE_KEY_VIOLATION in error.gds_codes:
            ...
    """

    # Arithmetic / Conversion
    ARITH_EXCEPT = 335544321
    CONVERT_ERROR = 335544334

    # Concurrency & Locking
    DEADLOCK = 335544345
    LOCK_CONFLICT = 335544332
    UPDATE_CONFLICT = 335544451

    # Constraint violations (most frequently needed)
    UNIQUE_KEY_VIOLATION = 335544665
    FOREIGN_KEY_VIOLATION = 335544466
    CHECK_CONSTRAINT = 335544558
    NOT_NULL_VIOLATION = 335544531
    PRIMARY_KEY_EXISTS = 335544548

    # Read-only issues
    READ_ONLY_FIELD = 335544359
    READ_ONLY_RELATION = 335544360
    READ_ONLY_TRANSACTION = 335544361
    READ_ONLY_VIEW = 335544362
    READ_ONLY_DATABASE = 335544765

    # Other common errors
    IO_ERROR = 335544344
    EXCEPTION = 335544517
    UDF_EXCEPTION = 335544740
    NO_UPDATE_PERMISSION = 335544840
    NO_DELETE_PERMISSION = 335544673
    NO_REFERENCES_PERMISSION = 335544674
    NO_INSERT_PERMISSION = 335544672

    # Additional useful codes
    BAD_DB_HANDLE = 335544324
    BAD_DSQL_HANDLE = 335544325
    INVALID_TRANSACTION_HANDLE = 335544327
    LOGIN_ERROR = 335545106

    # Network / Connection loss
    CONN_LOST = 335544648              # conn_lost (pipe server)
    NETWORK_ERROR = 335544721          # network_error
    NET_CONNECT_ERR = 335544722        # net_connect_err
    NET_READ_ERR = 335544726           # net_read_err
    NET_WRITE_ERR = 335544727          # net_write_err
    LOST_DB_CONNECTION = 335544741     # lost_db_connection
    TOO_MANY_HANDLES = 335544761       # too_many_handles
    ATT_SHUTDOWN = 335544856           # att_shutdown


# Set of GDS codes that indicate a lost or unusable Firebird
# connection where a reconnect + retry is appropriate. Used by
# the firebird-driver query loop in db.py.
RECONNECT_GDS_CODES: frozenset[int] = frozenset({
    GDSCode.CONN_LOST,
    GDSCode.NETWORK_ERROR,
    GDSCode.NET_CONNECT_ERR,
    GDSCode.NET_READ_ERR,
    GDSCode.NET_WRITE_ERR,
    GDSCode.LOST_DB_CONNECTION,
    GDSCode.TOO_MANY_HANDLES,
    GDSCode.ATT_SHUTDOWN,
})


# Helper dict for quick lookup
GDS_CODE_TO_NAME = {
    member.value: member.name for member in GDSCode
}


def gds_name(code: int) -> str | None:
    """Return the symbolic name for a numeric GDS code.

    Args:
        code: Numeric GDS code from exception.gds_codes

    Returns:
        Symbolic name or None if unknown
    """
    return GDS_CODE_TO_NAME.get(code)


# ─── Example / Self-test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"GDSCode.UNIQUE_KEY_VIOLATION = {GDSCode.UNIQUE_KEY_VIOLATION}")
    print(f"Name for 335544665: {gds_name(335544665)}")
    print(f"Deadlock code: {GDSCode.DEADLOCK}")
