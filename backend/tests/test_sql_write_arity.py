"""Static checks for handwritten SQL write arity."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SqlViolation:
    path: Path
    lineno: int
    kind: str
    detail: str
    sql: str


def _iter_python_files() -> list[Path]:
    return sorted(
        path
        for path in BACKEND_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _get_literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _find_matching_paren(text: str, start: int) -> int:
    depth = 0
    in_quote: str | None = None
    escaped = False

    for index in range(start, len(text)):
        char = text[index]
        if in_quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_quote:
                in_quote = None
            continue

        if char in {"'", '"'}:
            in_quote = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return index

    return -1


def _split_top_level_csv(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote: str | None = None
    escaped = False

    for char in text:
        if in_quote is not None:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_quote:
                in_quote = None
            continue

        if char in {"'", '"'}:
            in_quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
            current.append(char)
            continue
        if char == ")":
            depth -= 1
            current.append(char)
            continue
        if char == "," and depth == 0:
            value = "".join(current).strip()
            if value:
                parts.append(value)
            current = []
            continue

        current.append(char)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _analyze_insert_statement(sql: str) -> tuple[int, list[int]] | None:
    upper = sql.upper()
    if "INSERT" not in upper or "VALUES" not in upper:
        return None

    into_index = upper.find("INTO")
    if into_index < 0:
        return None

    column_start = sql.find("(", into_index)
    if column_start < 0:
        return None
    column_end = _find_matching_paren(sql, column_start)
    if column_end < 0:
        return None

    column_count = len(_split_top_level_csv(sql[column_start + 1 : column_end]))

    values_index = upper.find("VALUES", column_end)
    if values_index < 0:
        return None

    row_start = sql.find("(", values_index)
    if row_start < 0:
        return None

    row_counts: list[int] = []
    cursor = row_start
    while cursor < len(sql) and sql[cursor] == "(":
        row_end = _find_matching_paren(sql, cursor)
        if row_end < 0:
            return None
        row_counts.append(len(_split_top_level_csv(sql[cursor + 1 : row_end])))

        cursor = row_end + 1
        while cursor < len(sql) and sql[cursor].isspace():
            cursor += 1
        if cursor < len(sql) and sql[cursor] == ",":
            cursor += 1
            while cursor < len(sql) and sql[cursor].isspace():
                cursor += 1
            continue
        break

    return column_count, row_counts


def _count_qmark_placeholders(sql: str) -> int:
    count = 0
    in_quote: str | None = None
    escaped = False

    for char in sql:
        if in_quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_quote:
                in_quote = None
            continue

        if char in {"'", '"'}:
            in_quote = char
        elif char == "?":
            count += 1

    return count


def _literal_row_lengths(node: ast.AST | None) -> list[int] | None:
    if isinstance(node, (ast.Tuple, ast.List)):
        if all(not isinstance(item, (ast.Tuple, ast.List)) for item in node.elts):
            return [len(node.elts)]
        if all(isinstance(item, (ast.Tuple, ast.List)) for item in node.elts):
            return [len(item.elts) for item in node.elts]
    return None


def _iter_sql_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue

        func = node.func
        if isinstance(func, ast.Attribute):
            call_name = func.attr
        elif isinstance(func, ast.Name):
            call_name = func.id
        else:
            continue

        if call_name not in {"execute", "executemany"}:
            continue
        yield node


def _scan_sql_write_arity() -> list[SqlViolation]:
    violations: list[SqlViolation] = []

    for path in _iter_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for call in _iter_sql_calls(tree):
            sql = _get_literal_string(call.args[0])
            if not sql:
                continue

            compact_sql = " ".join(sql.split())
            insert_info = _analyze_insert_statement(sql)
            if insert_info is not None:
                column_count, row_counts = insert_info
                bad_rows = [row_count for row_count in row_counts if row_count != column_count]
                if bad_rows:
                    violations.append(
                        SqlViolation(
                            path=path,
                            lineno=call.lineno,
                            kind="insert-value-arity",
                            detail=f"columns={column_count}, row_values={row_counts}",
                            sql=compact_sql,
                        )
                    )

            if len(call.args) < 2:
                continue

            row_lengths = _literal_row_lengths(call.args[1])
            if row_lengths is None:
                continue

            placeholder_count = _count_qmark_placeholders(sql)
            if any(row_length != placeholder_count for row_length in row_lengths):
                violations.append(
                    SqlViolation(
                        path=path,
                        lineno=call.lineno,
                        kind="placeholder-arg-arity",
                        detail=f"placeholders={placeholder_count}, arg_rows={row_lengths}",
                        sql=compact_sql,
                    )
                )

    return violations


def test_handwritten_sql_write_arity_is_consistent():
    violations = _scan_sql_write_arity()

    assert not violations, "\n".join(
        f"{item.kind} {item.path.relative_to(BACKEND_DIR.parent)}:{item.lineno} "
        f"{item.detail}\n  SQL: {item.sql}"
        for item in violations
    )
