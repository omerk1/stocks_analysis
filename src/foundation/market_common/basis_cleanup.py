"""python -m src.foundation.market_common.basis_cleanup [--apply]

Removes stored level rows computed on a price basis other than their
module's current one (`price_basis.MODULE_PRICE_BASIS`).

After a module's basis changes, rerunning it refreshes every row it finds
again -- but for most modules a rerun only inserts or updates, so rows only
the old prices produced (a pivot, a swing or a pattern that doesn't occur on
the new series) stay behind, still on the old basis and mixed in with the
new ones. Every stored row links to its run, and every run records its
config, basis included, so those rows are identifiable exactly: a run with
no recorded basis predates the setting and was `total_return`.

Default is a dry run that prints per-table counts; `--apply` deletes them
(child rows -- S/R line events, Fibonacci levels -- go with their parents).
Run it **after** the reruns: before them, every row is on the old basis.
"""

from __future__ import annotations

import argparse
import sqlite3

from src.foundation.market_common import derived_db
from src.foundation.market_common.price_basis import MODULE_PRICE_BASIS
from src.foundation.utils.config_loader import load_config

# module -> its stored table (every one has a `run_id`)
LEVEL_TABLES: dict[str, str] = {
    "gaps": "gaps",
    "avwap": "avwap_anchors",
    "volume_profile": "volume_profiles",
    "sr_lines": "sr_lines",
    "fibonacci": "fib_sets",
    "patterns": "pattern_matches",
    "market_structure": "market_structure_events",
    "divergences": "divergences",
}

_RUN_BASIS = "COALESCE(json_extract(r.config_json, '$.price_basis'), 'total_return')"


def _stale_ids_sql(table: str) -> str:
    return (
        f"SELECT t.rowid FROM {table} t LEFT JOIN runs r ON r.run_id = t.run_id "
        f"WHERE r.run_id IS NULL OR {_RUN_BASIS} != ?"
    )


def _existing(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def stale_counts(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """table -> (rows on another basis than the module's, total rows)."""
    have = _existing(conn)
    out = {}
    for module, table in LEVEL_TABLES.items():
        if table not in have:
            continue
        basis = MODULE_PRICE_BASIS[module].value
        stale = conn.execute(f"SELECT COUNT(*) FROM ({_stale_ids_sql(table)})", (basis,)).fetchone()[0]
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        out[table] = (stale, total)
    return out


def delete_stale(conn: sqlite3.Connection) -> dict[str, int]:
    """Deletes the rows `stale_counts` reports, plus their orphaned child
    rows, in one transaction. Returns rows deleted per table."""
    have = _existing(conn)
    deleted = {}
    with conn:
        for module, table in LEVEL_TABLES.items():
            if table not in have:
                continue
            basis = MODULE_PRICE_BASIS[module].value
            cur = conn.execute(f"DELETE FROM {table} WHERE rowid IN ({_stale_ids_sql(table)})", (basis,))
            deleted[table] = cur.rowcount
        if "sr_line_events" in have:
            deleted["sr_line_events"] = conn.execute(
                "DELETE FROM sr_line_events WHERE line_id NOT IN (SELECT id FROM sr_lines)"
            ).rowcount
        if "fib_levels" in have:
            deleted["fib_levels"] = conn.execute(
                "DELETE FROM fib_levels WHERE fib_set_id NOT IN (SELECT id FROM fib_sets)"
            ).rowcount
    return deleted


def main():
    parser = argparse.ArgumentParser(description="Remove stored level rows computed on a stale price basis")
    parser.add_argument("--apply", action="store_true", help="Delete (default: dry run, counts only)")
    args = parser.parse_args()

    config = load_config()
    conn = derived_db.get_connection(derived_db.default_derived_db_path(config.data_paths.derived))
    for table, (stale, total) in stale_counts(conn).items():
        print(f"{table:<26} {stale:>9,} of {total:>9,} rows on another basis")
    if args.apply:
        for table, n in delete_stale(conn).items():
            print(f"deleted {n:,} from {table}")
    else:
        print("dry run -- pass --apply to delete")
    conn.close()


if __name__ == "__main__":
    main()
