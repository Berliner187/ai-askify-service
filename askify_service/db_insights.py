"""
Сбор аналитики по PostgreSQL для админки.

Всё берётся из системных каталогов и статистики Postgres (pg_class, pg_stats,
pg_stat_user_tables, pg_stat_user_indexes, pg_stat_database, pg_stat_activity,
pg_stat_statements). Таблицы данных не сканируются: полный снимок занимает
десятки миллисекунд даже на большой базе.

Точный COUNT(*) делается только по кнопке для одной таблицы и с таймаутом.
"""
import time

from django.apps import apps
from django.db import connection, transaction


def _rows(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(sql, params=None):
    rows = _rows(sql, params)
    return rows[0] if rows else {}


def _iso(v):
    return v.isoformat() if v else None


# --------------------------------------------------------------------------
# Сервер и база целиком
# --------------------------------------------------------------------------

def collect_overview():
    ov = _one("""
        SELECT current_database()                        AS db_name,
               pg_database_size(current_database())      AS db_size,
               version()                                 AS version,
               now() - pg_postmaster_start_time()        AS uptime,
               pg_postmaster_start_time()                AS started_at,
               current_setting('max_connections')::int   AS max_connections,
               current_setting('shared_buffers')         AS shared_buffers,
               current_setting('work_mem')               AS work_mem,
               current_setting('effective_cache_size')   AS effective_cache_size,
               current_setting('maintenance_work_mem')   AS maintenance_work_mem,
               current_setting('random_page_cost')       AS random_page_cost,
               current_setting('autovacuum')             AS autovacuum
    """)
    st = _one("""
        SELECT numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
               tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted,
               conflicts, temp_files, temp_bytes, deadlocks, stats_reset
        FROM pg_stat_database WHERE datname = current_database()
    """)
    hit = (st.get("blks_hit") or 0)
    read = (st.get("blks_read") or 0)
    commits = st.get("xact_commit") or 0
    rollbacks = st.get("xact_rollback") or 0

    other_dbs = _rows("""
        SELECT datname, pg_database_size(datname) AS size
        FROM pg_database WHERE NOT datistemplate ORDER BY 2 DESC
    """)

    return {
        "db_name": ov["db_name"],
        "db_size": ov["db_size"],
        "version": ov["version"].split(" on ")[0],
        "uptime_sec": int(ov["uptime"].total_seconds()) if ov.get("uptime") else None,
        "started_at": _iso(ov.get("started_at")),
        "settings": {k: ov[k] for k in (
            "max_connections", "shared_buffers", "work_mem", "effective_cache_size",
            "maintenance_work_mem", "random_page_cost", "autovacuum")},
        "cache_hit_ratio": round(hit / (hit + read) * 100, 2) if hit + read else None,
        "rollback_ratio": round(rollbacks / (commits + rollbacks) * 100, 3) if commits + rollbacks else 0,
        "stats": {k: (int(v) if isinstance(v, (int, float)) else _iso(v)) for k, v in st.items()},
        "databases": other_dbs,
    }


# --------------------------------------------------------------------------
# Таблицы
# --------------------------------------------------------------------------

def _django_table_map():
    """db_table -> 'app.Model' для всех моделей проекта (включая auto M2M)."""
    m = {}
    for model in apps.get_models(include_auto_created=True):
        m[model._meta.db_table] = f"{model._meta.app_label}.{model.__name__}"
    return m


def collect_tables():
    rows = _rows("""
        SELECT n.nspname                              AS schema,
               c.relname                              AS name,
               c.oid                                  AS oid,
               GREATEST(c.reltuples, 0)::bigint       AS est_rows,
               pg_total_relation_size(c.oid)          AS total_bytes,
               pg_relation_size(c.oid)                AS heap_bytes,
               pg_indexes_size(c.oid)                 AS index_bytes,
               COALESCE(pg_total_relation_size(c.reltoastrelid), 0) AS toast_bytes,
               s.seq_scan, s.seq_tup_read, s.idx_scan, s.idx_tup_fetch,
               s.n_tup_ins, s.n_tup_upd, s.n_tup_del, s.n_tup_hot_upd,
               s.n_live_tup, s.n_dead_tup, s.n_mod_since_analyze,
               s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze,
               s.vacuum_count, s.autovacuum_count,
               io.heap_blks_read, io.heap_blks_hit, io.idx_blks_read, io.idx_blks_hit,
               (SELECT count(*) FROM pg_attribute a
                 WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS column_count
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables  s  ON s.relid  = c.oid
        LEFT JOIN pg_statio_user_tables io ON io.relid = c.oid
        WHERE c.relkind IN ('r', 'p')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%%'
        ORDER BY total_bytes DESC
    """)
    model_map = _django_table_map()
    total_db = sum(r["total_bytes"] for r in rows) or 1
    out = []
    for r in rows:
        live, dead = r["n_live_tup"] or 0, r["n_dead_tup"] or 0
        seq, idx = r["seq_scan"] or 0, r["idx_scan"] or 0
        hh, hr = r["heap_blks_hit"] or 0, r["heap_blks_read"] or 0
        upd, hot = r["n_tup_upd"] or 0, r["n_tup_hot_upd"] or 0
        writes = (r["n_tup_ins"] or 0) + upd + (r["n_tup_del"] or 0)
        reads = (r["seq_tup_read"] or 0) + (r["idx_tup_fetch"] or 0)
        model = model_map.get(r["name"])
        rows_est = max(r["est_rows"], live)
        flags = []
        if not model:
            flags.append("orphan")          # таблицы нет в моделях Django
        if rows_est == 0:
            flags.append("empty")
        if seq + idx == 0:
            flags.append("never_read")
        if live and dead / (live + dead) > 0.2 and dead > 1000:
            flags.append("bloated")
        if seq > 1000 and rows_est > 10000 and seq > idx:
            flags.append("seq_heavy")       # часто читается полным сканом
        if r["index_bytes"] > r["heap_bytes"] * 2 and r["heap_bytes"] > 1024 * 1024:
            flags.append("index_heavy")
        out.append({
            "schema": r["schema"],
            "name": r["name"],
            "model": model,
            "rows": rows_est,
            "columns": r["column_count"],
            "total_bytes": r["total_bytes"],
            "heap_bytes": r["heap_bytes"],
            "index_bytes": r["index_bytes"],
            "toast_bytes": r["toast_bytes"],
            "share_pct": round(r["total_bytes"] / total_db * 100, 2),
            "bytes_per_row": round(r["heap_bytes"] / rows_est) if rows_est else None,
            "seq_scan": seq, "idx_scan": idx,
            "seq_tup_read": r["seq_tup_read"] or 0,
            "idx_usage_pct": round(idx / (seq + idx) * 100, 1) if seq + idx else None,
            "ins": r["n_tup_ins"] or 0, "upd": upd, "del": r["n_tup_del"] or 0,
            "hot_upd_pct": round(hot / upd * 100, 1) if upd else None,
            "reads": reads, "writes": writes,
            "live": live, "dead": dead,
            "dead_pct": round(dead / (live + dead) * 100, 1) if live + dead else 0,
            "mod_since_analyze": r["n_mod_since_analyze"] or 0,
            "cache_hit_pct": round(hh / (hh + hr) * 100, 1) if hh + hr else None,
            "last_vacuum": _iso(max(filter(None, [r["last_vacuum"], r["last_autovacuum"]]), default=None)),
            "last_analyze": _iso(max(filter(None, [r["last_analyze"], r["last_autoanalyze"]]), default=None)),
            "vacuum_count": (r["vacuum_count"] or 0) + (r["autovacuum_count"] or 0),
            "flags": flags,
        })
    return out


# --------------------------------------------------------------------------
# Колонки
# --------------------------------------------------------------------------

def collect_columns():
    rows = _rows("""
        SELECT c.relname                         AS table_name,
               a.attname                         AS column_name,
               a.attnum                          AS position,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               NOT a.attnotnull                  AS nullable,
               pg_get_expr(d.adbin, d.adrelid)   AS default_value,
               a.attstorage                      AS storage,
               s.avg_width, s.null_frac, s.n_distinct, s.correlation,
               GREATEST(c.reltuples, 0)::bigint  AS est_rows,
               col_description(c.oid, a.attnum)  AS comment
        FROM pg_attribute a
        JOIN pg_class c      ON c.oid = a.attrelid
        JOIN pg_namespace n  ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        LEFT JOIN pg_stats s ON s.schemaname = n.nspname AND s.tablename = c.relname
                            AND s.attname = a.attname
        WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%%'
        ORDER BY c.relname, a.attnum
    """)
    out = []
    for r in rows:
        n_rows = r["est_rows"] or 0
        nd = r["n_distinct"]
        # n_distinct < 0 означает долю от числа строк
        distinct = None
        if nd is not None:
            distinct = int(-nd * n_rows) if nd < 0 else int(nd)
        width = r["avg_width"]
        nf = r["null_frac"]
        flags = []
        if r["avg_width"] is None and n_rows > 0:
            flags.append("no_stats")
        if nf is not None and nf >= 0.99 and n_rows > 100:
            flags.append("always_null")
        if distinct == 1 and n_rows > 100 and (nf or 0) < 0.99:
            flags.append("constant")
        if width and width > 1024:
            flags.append("wide")
        out.append({
            "table": r["table_name"],
            "column": r["column_name"],
            "position": r["position"],
            "type": r["data_type"],
            "nullable": r["nullable"],
            "default": r["default_value"],
            "storage": r["storage"],
            "avg_width": width,
            "null_pct": round(nf * 100, 1) if nf is not None else None,
            "distinct": distinct,
            "correlation": round(r["correlation"], 3) if r["correlation"] is not None else None,
            "approx_bytes": int(width * n_rows * (1 - (nf or 0))) if width else None,
            "comment": r["comment"],
            "flags": flags,
        })
    return out


# --------------------------------------------------------------------------
# Индексы
# --------------------------------------------------------------------------

def collect_indexes():
    rows = _rows("""
        SELECT t.relname                          AS table_name,
               i.relname                          AS index_name,
               pg_relation_size(i.oid)            AS bytes,
               COALESCE(s.idx_scan, 0)            AS scans,
               COALESCE(s.idx_tup_read, 0)        AS tup_read,
               COALESCE(s.idx_tup_fetch, 0)       AS tup_fetch,
               x.indisunique                      AS is_unique,
               x.indisprimary                     AS is_primary,
               x.indisvalid                       AS is_valid,
               x.indkey::text                     AS indkey,
               pg_get_indexdef(i.oid)             AS definition,
               am.amname                          AS method
        FROM pg_index x
        JOIN pg_class i      ON i.oid = x.indexrelid
        JOIN pg_class t      ON t.oid = x.indrelid
        JOIN pg_namespace n  ON n.oid = t.relnamespace
        JOIN pg_am am        ON am.oid = i.relam
        LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = i.oid
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspname NOT LIKE 'pg_toast%%'
        ORDER BY bytes DESC
    """)
    # дубликаты: одинаковый набор колонок на одной таблице
    seen = {}
    for r in rows:
        seen.setdefault((r["table_name"], r["indkey"]), []).append(r["index_name"])
    # префиксы: индекс (a) покрыт индексом (a, b)
    by_table = {}
    for r in rows:
        by_table.setdefault(r["table_name"], []).append(r["indkey"].split())
    out = []
    for r in rows:
        flags = []
        if r["scans"] == 0 and not r["is_primary"] and not r["is_unique"]:
            flags.append("unused")
        if len(seen[(r["table_name"], r["indkey"])]) > 1:
            flags.append("duplicate")
        cols = r["indkey"].split()
        if not r["is_unique"] and not r["is_primary"] and any(
            len(o) > len(cols) and o[:len(cols)] == cols for o in by_table[r["table_name"]]
        ):
            flags.append("covered_by_prefix")
        if not r["is_valid"]:
            flags.append("invalid")
        out.append({
            "table": r["table_name"], "name": r["index_name"], "bytes": r["bytes"],
            "scans": r["scans"], "tup_read": r["tup_read"], "tup_fetch": r["tup_fetch"],
            "unique": r["is_unique"], "primary": r["is_primary"], "method": r["method"],
            "definition": r["definition"], "flags": flags,
        })
    return out


# --------------------------------------------------------------------------
# Связи (FK) и FK без индекса
# --------------------------------------------------------------------------

def collect_relations():
    rows = _rows("""
        SELECT con.conname                         AS name,
               src.relname                         AS source,
               dst.relname                         AS target,
               array_agg(sa.attname ORDER BY k.ord) AS source_cols,
               array_agg(da.attname ORDER BY k.ord) AS target_cols,
               con.confdeltype                     AS on_delete,
               EXISTS (
                   SELECT 1 FROM pg_index ix
                   WHERE ix.indrelid = con.conrelid
                     AND (ix.indkey::int2[])[0:cardinality(con.conkey) - 1] = con.conkey
               ) AS has_index
        FROM pg_constraint con
        JOIN pg_class src ON src.oid = con.conrelid
        JOIN pg_class dst ON dst.oid = con.confrelid
        JOIN pg_namespace n ON n.oid = src.relnamespace
        CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS k(sk, dk, ord)
        JOIN pg_attribute sa ON sa.attrelid = con.conrelid  AND sa.attnum = k.sk
        JOIN pg_attribute da ON da.attrelid = con.confrelid AND da.attnum = k.dk
        WHERE con.contype = 'f' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        GROUP BY con.oid, con.conname, src.relname, dst.relname, con.confdeltype,
                 con.conrelid, con.conkey
        ORDER BY src.relname
    """)
    actions = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}
    return [{
        "name": r["name"], "source": r["source"], "target": r["target"],
        "source_cols": list(r["source_cols"]), "target_cols": list(r["target_cols"]),
        "on_delete": actions.get(r["on_delete"], r["on_delete"]),
        "has_index": r["has_index"],
    } for r in rows]


def collect_soft_links():
    """
    Неявные связи через UUID-поля (id_staff, survey_id, staff_id) — в этом проекте
    их много, а FK на них нет. Находим колонки, совпадающие по имени с
    уникальными колонками других таблиц.
    """
    rows = _rows("""
        WITH uniq AS (
            SELECT t.relname AS tbl, a.attname AS col, a.atttypid AS typ
            FROM pg_index x
            JOIN pg_class t ON t.oid = x.indrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.indkey[0]
            WHERE x.indisunique AND x.indnatts = 1 AND NOT x.indisprimary
              AND n.nspname = 'public'
        ),
        cols AS (
            SELECT c.relname AS tbl, a.attname AS col, a.atttypid AS typ, c.oid AS relid, a.attnum
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
              AND n.nspname = 'public'
        )
        SELECT cols.tbl AS source, cols.col AS column, uniq.tbl AS target
        FROM cols JOIN uniq ON uniq.col = cols.col AND uniq.typ = cols.typ AND uniq.tbl <> cols.tbl
        WHERE cols.col NOT IN ('id', 'name', 'slug', 'code', 'token', 'email', 'username')
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint f
              WHERE f.contype = 'f' AND f.conrelid = cols.relid AND cols.attnum = ANY (f.conkey)
          )
    """)
    return rows


# --------------------------------------------------------------------------
# Тяжёлые запросы (pg_stat_statements), если расширение включено
# --------------------------------------------------------------------------

def statements_available():
    return bool(_one("SELECT 1 AS ok FROM pg_extension WHERE extname = 'pg_stat_statements'"))


def collect_statements(limit=40):
    if not statements_available():
        return {"available": False, "items": []}
    # PG13+: total_exec_time; до 13: total_time
    for time_col, mean_col in (("total_exec_time", "mean_exec_time"), ("total_time", "mean_time")):
        try:
            with transaction.atomic():
                rows = _rows(f"""
                    SELECT queryid::text AS id, calls, rows,
                           round({time_col}::numeric, 1)  AS total_ms,
                           round({mean_col}::numeric, 2)  AS mean_ms,
                           shared_blks_hit, shared_blks_read, temp_blks_written,
                           left(regexp_replace(query, '\\s+', ' ', 'g'), 600) AS query
                    FROM pg_stat_statements
                    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                    ORDER BY {time_col} DESC
                    LIMIT %s
                """, [limit])
            break
        except Exception:
            rows = None
    if rows is None:
        return {"available": True, "error": "Нет доступа к pg_stat_statements", "items": []}
    grand = sum(float(r["total_ms"]) for r in rows) or 1
    for r in rows:
        hit, read = r.pop("shared_blks_hit") or 0, r.pop("shared_blks_read") or 0
        r["cache_hit_pct"] = round(hit / (hit + read) * 100, 1) if hit + read else None
        r["total_ms"] = float(r["total_ms"])
        r["mean_ms"] = float(r["mean_ms"])
        r["share_pct"] = round(r["total_ms"] / grand * 100, 1)
    return {"available": True, "items": rows}


# --------------------------------------------------------------------------
# Живое состояние: соединения, долгие запросы, блокировки
# --------------------------------------------------------------------------

def collect_activity():
    states = _rows("""
        SELECT COALESCE(state, 'background') AS state, count(*) AS n
        FROM pg_stat_activity WHERE datname = current_database()
        GROUP BY 1 ORDER BY 2 DESC
    """)
    long_running = _rows("""
        SELECT pid, usename, application_name, state,
               EXTRACT(EPOCH FROM (now() - query_start))::numeric(10,1) AS seconds,
               wait_event_type, wait_event,
               left(regexp_replace(query, '\\s+', ' ', 'g'), 300) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid()
          AND state <> 'idle' AND query_start IS NOT NULL
        ORDER BY query_start ASC LIMIT 15
    """)
    idle_tx = _one("""
        SELECT count(*) AS n,
               COALESCE(max(EXTRACT(EPOCH FROM (now() - xact_start))), 0)::int AS max_sec
        FROM pg_stat_activity
        WHERE datname = current_database() AND state LIKE 'idle in transaction%%'
    """)
    blocked = _one("""
        SELECT count(*) AS n FROM pg_stat_activity
        WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0
    """)
    db = _one("""
        SELECT xact_commit, xact_rollback, blks_hit, blks_read,
               tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted
        FROM pg_stat_database WHERE datname = current_database()
    """)
    for r in long_running:
        r["seconds"] = float(r["seconds"] or 0)
    return {
        "ts": time.time(),
        "states": states,
        "total_connections": sum(s["n"] for s in states),
        "long_running": long_running,
        "idle_in_tx": idle_tx,
        "blocked": blocked.get("n", 0),
        "counters": {k: int(v or 0) for k, v in db.items()},
    }


# --------------------------------------------------------------------------
# Полный снимок + точный COUNT по требованию
# --------------------------------------------------------------------------

def collect_snapshot():
    t0 = time.monotonic()
    tables = collect_tables()
    columns = collect_columns()
    indexes = collect_indexes()
    relations = collect_relations()
    model_map = _django_table_map()
    existing = {t["name"] for t in tables}
    snap = {
        "overview": collect_overview(),
        "tables": tables,
        "columns": columns,
        "indexes": indexes,
        "relations": relations,
        "soft_links": collect_soft_links(),
        "statements": collect_statements(),
        "models_without_table": sorted(
            label for tbl, label in model_map.items() if tbl not in existing
        ),
    }
    snap["summary"] = {
        "tables": len(tables),
        "columns": len(columns),
        "indexes": len(indexes),
        "relations": len(relations),
        "rows": sum(t["rows"] for t in tables),
        "data_bytes": sum(t["heap_bytes"] + t["toast_bytes"] for t in tables),
        "index_bytes": sum(t["index_bytes"] for t in tables),
        "unused_index_bytes": sum(i["bytes"] for i in indexes if "unused" in i["flags"]),
        "unused_indexes": sum(1 for i in indexes if "unused" in i["flags"]),
        "orphan_tables": sum(1 for t in tables if "orphan" in t["flags"]),
        "empty_tables": sum(1 for t in tables if "empty" in t["flags"]),
        "dead_rows": sum(t["dead"] for t in tables),
        "fk_without_index": sum(1 for r in relations if not r["has_index"]),
    }
    snap["collect_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return snap


def exact_count(table_name, timeout_ms=5000):
    """Точный COUNT(*) по одной таблице. Имя сверяется с каталогом."""
    ok = _one("""
        SELECT n.nspname AS schema, c.relname AS name FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r','p') AND c.relname = %s
          AND n.nspname NOT IN ('pg_catalog','information_schema')
    """, [table_name])
    if not ok:
        raise ValueError("Нет такой таблицы")
    q = connection.ops.quote_name
    t0 = time.monotonic()
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = %s", [int(timeout_ms)])
        cur.execute(f"SELECT count(*) FROM {q(ok['schema'])}.{q(ok['name'])}")
        n = cur.fetchone()[0]
    return {"table": table_name, "count": n, "ms": round((time.monotonic() - t0) * 1000, 1)}


def reset_statements():
    if statements_available():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_stat_statements_reset()")
        return True
    return False
