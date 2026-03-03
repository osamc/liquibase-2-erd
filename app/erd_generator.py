"""
Generate draw.io (mxGraph) XML from PostgreSQL schema introspection.
Output is editable in draw.io / diagrams.net.
"""

import re
import uuid
from collections import defaultdict
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


# Liquibase internal tables to omit from the ERD
LIQUIBASE_TABLES = {"databasechangelog", "databasechangeloglock"}


def _sanitize_id(s: str) -> str:
    """Create a valid mxCell id from a string."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:50]


def get_schema(connection_params: dict) -> tuple[list[dict], list[dict]]:
    """
    Introspect PostgreSQL schema. Returns (tables, relationships).
    connection_params: dict with keys host, port, dbname, user, password.
    """
    conn = psycopg2.connect(**connection_params, cursor_factory=RealDictCursor)
    try:
        # Tables and columns (public schema only by default)
        tables_sql = """
            SELECT
                c.table_schema,
                c.table_name,
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                a.attnotnull AS is_not_null,
                COALESCE(
                    (SELECT 'PRIMARY KEY'
                     FROM pg_index i
                     JOIN pg_attribute ai ON ai.attrelid = i.indrelid AND ai.attnum = ANY(i.indkey)
                     WHERE i.indrelid = c.table_name::regclass AND i.indisprimary AND ai.attnum > 0 AND NOT ai.attisdropped
                     LIMIT 1),
                    (SELECT 'FOREIGN KEY'
                     FROM information_schema.key_column_usage kcu
                     WHERE kcu.table_schema = c.table_schema
                       AND kcu.table_name = c.table_name
                       AND kcu.column_name = a.attname
                     LIMIT 1)
                ) AS key_type
            FROM information_schema.columns c
            JOIN pg_catalog.pg_attribute a ON a.attrelid = (c.table_schema || '.' || c.table_name)::regclass
                 AND a.attname = c.column_name
                 AND a.attnum > 0
                 AND NOT a.attisdropped
            WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY c.table_schema, c.table_name, c.ordinal_position;
        """
        # Simpler query that works on all PG versions
        tables_sql = """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name, ordinal_position;
        """
        cur = conn.cursor()
        cur.execute(tables_sql)
        rows = cur.fetchall()

        # Group by table (exclude Liquibase internal tables)
        table_columns: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in rows:
            if r["table_name"].lower() in LIQUIBASE_TABLES:
                continue
            key = (r["table_schema"], r["table_name"])
            table_columns[key].append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
            })

        # Primary keys (information_schema for compatibility)
        cur.execute("""
            SELECT tc.table_schema, tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY';
        """)
        pk_set: set[tuple[str, str, str]] = set()
        for r in cur.fetchall():
            pk_set.add((r["table_schema"], r["table_name"], r["column_name"]))

        # Foreign keys
        cur.execute("""
            SELECT
                tc.table_schema AS from_schema,
                tc.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_schema AS to_schema,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema NOT IN ('pg_catalog', 'information_schema');
        """)
        fks = cur.fetchall()

        tables = []
        for (schema, table_name), cols in sorted(table_columns.items()):
            col_list = []
            for c in cols:
                pk = (schema, table_name, c["name"]) in pk_set
                col_list.append({
                    **c,
                    "primary_key": pk,
                })
            tables.append({
                "schema": schema,
                "name": table_name,
                "columns": col_list,
            })

        relationships = [
            {
                "from_schema": r["from_schema"],
                "from_table": r["from_table"],
                "from_column": r["from_column"],
                "to_schema": r["to_schema"],
                "to_table": r["to_table"],
                "to_column": r["to_column"],
            }
            for r in fks
            if r["from_table"].lower() not in LIQUIBASE_TABLES and r["to_table"].lower() not in LIQUIBASE_TABLES
        ]
        return tables, relationships
    finally:
        conn.close()


def _escape_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "&#10;")
    )


def generate_drawio_xml(tables: list[dict], relationships: list[dict]) -> str:
    """
    Generate draw.io (mxfile) XML from tables and relationships.
    Uses mxGraph structure so the file opens in draw.io and is editable.
    """
    cell_id = 2  # 0 and 1 are root/parent
    table_ids: dict[tuple[str, str], str] = {}

    # Layout: simple grid
    col_width = 220
    row_height = 320
    cols_per_row = 4
    table_positions: dict[tuple[str, str], tuple[int, int]] = {}
    for i, t in enumerate(tables):
        row, col = divmod(i, cols_per_row)
        table_positions[(t["schema"], t["name"])] = (
            40 + col * (col_width + 60),
            40 + row * (row_height + 40),
        )

    def next_id() -> str:
        nonlocal cell_id
        cell_id += 1
        return f"edge_{cell_id}"

    # Build table label (header + columns)
    def table_label(t: dict) -> str:
        lines = [f"**{t['name']}**", "", ""]
        for c in t["columns"]:
            prefix = "(PK) " if c.get("primary_key") else ""
            lines.append(f"{prefix}{c['name']}: {c['type']}")
        return "\n".join(lines)

    cells: list[str] = []
    parent_id = "1"

    # Draw.io Entity Relation shapes: shape=table for entities, crow's foot for relationships
    entity_style = (
        "shape=table;startSize=28;container=1;collapsible=0;childLayout=tableLayout;"
        "fillColor=#dae8fc;strokeColor=#6c8ebf;align=left;verticalAlign=top;"
        "spacingLeft=4;spacingRight=4;fontStyle=1;whiteSpace=wrap;html=1;"
    )
    for t in tables:
        key = (t["schema"], t["name"])
        tid = f"table_{_sanitize_id(t['schema'])}_{_sanitize_id(t['name'])}"
        table_ids[key] = tid
        x, y = table_positions[key]
        w = col_width
        h = 48 + len(t["columns"]) * 22
        value = _escape_xml(table_label(t))
        cells.append(
            f'<mxCell id="{tid}" value="{value}" style="{entity_style}" vertex="1" parent="{parent_id}">'
        )
        cells.append(f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />')
        cells.append("</mxCell>")

    for rel in relationships:
        from_key = (rel["from_schema"], rel["from_table"])
        to_key = (rel["to_schema"], rel["to_table"])
        if from_key not in table_ids or to_key not in table_ids:
            continue
        from_id = table_ids[from_key]
        to_id = table_ids[to_key]
        edge_id = next_id()
        # Crow's foot notation: many (from) -> one (to)
        edge_style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            "exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;"
            "startArrow=ERmany;startFill=0;endArrow=ERone;endFill=0;"
        )
        cells.append(
            f'<mxCell id="{edge_id}" style="{edge_style}" edge="1" parent="{parent_id}" source="{from_id}" target="{to_id}">'
        )
        cells.append('<mxGeometry relative="1" as="geometry" />')
        cells.append("</mxCell>")

    diagram_id = str(uuid.uuid4()).replace("-", "")[:20]
    cells_xml = "\n        ".join(cells)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<mxfile host="app.diagrams.net" modified="" agent="Liquibase-ERD" etag="" version="21.0.0" type="device">
  <diagram name="ERD" id="{diagram_id}">
    <mxGraphModel dx="946" dy="469" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1100" pageHeight="850" background="#ffffff" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        {cells_xml}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>'''
