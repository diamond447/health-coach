"""Static checks for query_sql. Defense in depth: the query also runs as coach_ro in a
read-only transaction with a statement timeout, so the database enforces the same rules."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

MAX_SQL_LENGTH = 10_000

# Statement shapes allowed at the root.
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

# Nodes that must not appear anywhere (data-modifying CTEs, SELECT INTO, row locks, ...).
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Into,
    exp.Lock,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

# Function names (lowercase) that are never needed for analysis. Anything starting with
# `pg_` is blocked except for a few harmless helpers.
_FORBIDDEN_FUNCTIONS = {
    "dblink",
    "lo_import",
    "lo_export",
    "lo_get",
    "lo_open",
    "set_config",
    "current_setting",
    "nextval",
    "setval",
    "query_to_xml",
    "query_to_xml_and_xmlschema",
    "table_to_xml",
    "cursor_to_xml",
    "database_to_xml",
    "schema_to_xml",
    "txid_current",
    "version",
    # Run SQL given as a string, which the static checks cannot see.
    "ts_stat",
    "ts_rewrite",
    "currval",
    "lastval",
    # Build huge values from tiny inputs (memory exhaustion).
    "repeat",
    "lpad",
    "rpad",
    "pad",  # sqlglot's name for lpad/rpad
}
_FORBIDDEN_PREFIXES = (
    "pg_",
    "dblink",
    "lo_",
    "xpath",
    "query_to",
    "cursor_to",
    "table_to",
    "schema_to",
    "database_to",
)
_FORBIDDEN_SUBSTRINGS = ("xml",)
_ALLOWED_PG_FUNCTIONS = {"pg_typeof"}

# Tables the coach_ro role cannot read anyway; reject early with a clear message.
_FORBIDDEN_TABLES = {"oauth_tokens", "raw_payloads", "mcp_audit"}
_FORBIDDEN_SCHEMAS = {"pg_catalog", "information_schema"}


class SqlRejected(ValueError):
    pass


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_sql(sql: str) -> str:
    """Return the normalised single statement, or raise SqlRejected with the reason."""
    if len(sql) > MAX_SQL_LENGTH:
        raise SqlRejected(f"query is longer than {MAX_SQL_LENGTH} characters")
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except ParseError as exc:
        raise SqlRejected(f"could not parse SQL: {exc}") from exc
    if len(statements) != 1:
        raise SqlRejected("exactly one statement is allowed")
    root = statements[0]
    if not isinstance(root, _ALLOWED_ROOTS):
        raise SqlRejected("only SELECT or WITH ... SELECT queries are allowed")

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlRejected(f"{node.key.upper()} is not allowed")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if (
                name in _FORBIDDEN_FUNCTIONS
                or any(part in name for part in _FORBIDDEN_SUBSTRINGS)
                or (name.startswith(_FORBIDDEN_PREFIXES) and name not in _ALLOWED_PG_FUNCTIONS)
            ):
                raise SqlRejected(f"function {name} is not allowed")
        if isinstance(node, exp.Table):
            if node.name.lower() in _FORBIDDEN_TABLES:
                raise SqlRejected(f"table {node.name} is not available")
            if node.db and node.db.lower() in _FORBIDDEN_SCHEMAS:
                raise SqlRejected(f"schema {node.db} is not available")
            if node.name.lower().startswith("pg_"):
                raise SqlRejected(f"table {node.name} is not available")

    return root.sql(dialect="postgres")
