"""Retain MFNavis public object IDs through the 2.6.4 catalog rebuild.

The CSV freezes the listing previously displayed by each m3.0.2 web URL.
Each run represents consecutive IDs and consecutive sequences of one catalog.
When old objects merge, reserve all their IDs and use aliases for the extras.
A split follows the old page's primary designation. A removed listing stays
unavailable instead of recycling its URL for an unrelated object.
"""

import csv
from collections import defaultdict
from pathlib import Path
import sqlite3


def preserve_legacy_ids(conn: sqlite3.Connection, catalog_dir: Path) -> None:
    listings = {
        (code, sequence): object_id
        for code, sequence, object_id in conn.execute(
            "SELECT catalog_code, sequence, object_id FROM catalog_objects"
        )
    }
    previous_ids: dict[int, list[int]] = defaultdict(list)
    reserved = 0
    with (catalog_dir / "mfnavis_legacy_object_ids.csv").open(newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            first, last = int(row["first_id"]), int(row["last_id"])
            reserved = max(reserved, last)
            for legacy_id in range(first, last + 1):
                sequence = int(row["first_sequence"]) + legacy_id - first
                object_id = listings.get((row["catalog_code"], sequence))
                if object_id is not None:
                    previous_ids[object_id].append(legacy_id)

    mapping = []
    aliases: list[tuple[int, int]] = []
    next_id = reserved + 1
    for (object_id,) in conn.execute("SELECT id FROM objects ORDER BY id"):
        legacy = previous_ids.get(object_id)
        if legacy:
            public_id = legacy[0]
            aliases.extend((old, public_id) for old in legacy[1:])
        else:
            public_id = next_id
            next_id += 1
        mapping.append((object_id, public_id))

    with conn:
        # SQLite clears deferred constraints after *any* implicit commit,
        # including autocommitted DDL. Open the transaction before creating
        # the staging index or touching either end of the foreign keys.
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute("PRAGMA defer_foreign_keys = ON")
        # Keep SQLite FK checks indexed while swapping every parent key.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS legacy_image_fk ON object_images(object_id)"
        )
        conn.execute(
            "CREATE TEMP TABLE remap (old INTEGER PRIMARY KEY, new INTEGER UNIQUE)"
        )
        conn.executemany("INSERT INTO remap VALUES (?, ?)", mapping)
        # The disjoint negative IDs avoid collisions during the primary key swap.
        conn.execute("UPDATE objects SET id = -id")
        conn.execute(
            "UPDATE objects SET id = (SELECT new FROM remap WHERE old = -objects.id)"
        )
        for table in ("names", "object_images", "catalog_objects"):
            conn.execute(
                f"UPDATE {table} SET object_id = "
                f"(SELECT new FROM remap WHERE old = {table}.object_id) "
                "WHERE object_id IS NOT NULL"
            )
        conn.execute(
            "UPDATE sqlite_sequence SET seq = (SELECT max(id) FROM objects) WHERE name = 'objects'"
        )
        conn.execute("DROP TABLE IF EXISTS legacy_object_aliases")
        conn.execute(
            "CREATE TABLE legacy_object_aliases (legacy_id INTEGER PRIMARY KEY, object_id INTEGER NOT NULL REFERENCES objects(id))"
        )
        conn.executemany("INSERT INTO legacy_object_aliases VALUES (?, ?)", aliases)
        conn.execute("DROP TABLE remap")
        conn.execute("DROP INDEX legacy_image_fk")
        if conn.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Catalog rebuild left an invalid object reference")
