import re


SAFE_SQLITE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_sqlite_identifier(identifier):
    name = str(identifier or "")
    if not SAFE_SQLITE_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"unsafe SQLite identifier: {name!r}")
    return f'"{name}"'


def table_columns(conn, table_name):
    quoted = quote_sqlite_identifier(table_name)
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({quoted})").fetchall()}
