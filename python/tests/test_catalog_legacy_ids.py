"""The import must preserve links with the production SQLite FK setting."""

import sqlite3

import pytest

from PiFinder.catalog_imports.legacy_object_ids import preserve_legacy_ids


@pytest.mark.unit
def test_legacy_id_swap_and_merge_keep_all_foreign_keys(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE objects(id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE catalog_objects(catalog_code TEXT, sequence INTEGER,
                                     object_id INTEGER REFERENCES objects(id));
        CREATE TABLE names(object_id INTEGER REFERENCES objects(id));
        CREATE TABLE object_images(object_id INTEGER REFERENCES objects(id));
        INSERT INTO objects VALUES (1), (2), (3);
        INSERT INTO catalog_objects VALUES ('M', 31, 1), ('NGC', 224, 1),
                                          ('NGC', 231, 2), ('Nam', 91262, 3);
        INSERT INTO names VALUES (1);
        INSERT INTO object_images VALUES (2);
        """
    )
    (tmp_path / "mfnavis_legacy_object_ids.csv").write_text(
        "first_id,last_id,catalog_code,first_sequence\n"
        "1,1,NGC,231\n2,2,M,31\n3,3,NGC,224\n4,4,SaM,149\n"
    )
    preserve_legacy_ids(conn, tmp_path)
    assert list(conn.execute("SELECT id FROM objects ORDER BY id")) == [
        (1,),
        (2,),
        (5,),
    ]
    assert list(conn.execute("SELECT * FROM legacy_object_aliases")) == [(3, 2)]
    assert list(conn.execute("SELECT * FROM names")) == [(2,)]
    assert list(conn.execute("SELECT * FROM object_images")) == [(1,)]
    assert not list(conn.execute("PRAGMA foreign_key_check"))
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
    conn.close()
