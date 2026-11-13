"""Migrationen: Original-DB (v1), v2 und Neuanlage – inkl. Rollback bei Fehlern."""

import glob
import os
import sqlite3

import pytest

import database

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def v1_schema():
    with open(os.path.join(ROOT, "tests", "fixtures", "schema_v1.sql"), encoding="utf-8") as f:
        return f.read()


def make_v1(path):
    c = sqlite3.connect(path)
    c.executescript(v1_schema())
    c.executescript("""
        INSERT INTO KARTEN (beschreibung) VALUES ('Rot 1'), ('Blau 2'), (NULL);
        INSERT INTO PRODUKTE (name, beschreibung, preis, pfand) VALUES
            ('Flammkuchen', 'Speck', 7.5, 0), ('Glühwein', 'heiß', 3.3, 2.0), ('Weg', '', 1, 0), (NULL, NULL, NULL, NULL);
        INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, zeitpunkt_fertig, zeitpunkt_abgeholt, status, karte, preis) VALUES
            ('2025-12-06 16:01:00', '2025-12-06 16:09:00', '2025-12-06 16:10:00', 'abgeholt', 1, 10.8),
            ('2025-12-06 16:30:00', '2025-12-06 16:39:00', NULL, 'abholbereit', 2, 7.5),
            ('2025-12-06 17:00:00', NULL, NULL, 'in bearbeitung', -1, 0),
            ('2025-12-06 17:05:00', NULL, NULL, 'in bearbeitung', 99, 1),
            ('2025-12-06 17:06:00', NULL, '2025-12-06 17:20:00', 'abgeholt', NULL, 0.1 + 0.2);
        -- Spalten: anzahl, produkt_id, bestellung_id; Duplikate, gelöschte und unbekannte Produkte, anzahl 0
        INSERT INTO BESTELLUNGSINHALT VALUES (1,1,1),(1,2,1),(1,2,1),(1,1,2),(1,3,3),(1,77,4),(0,1,5),(2,1,5);
        DELETE FROM PRODUKTE WHERE id = 3;
    """)
    c.commit()
    c.close()


def test_neue_db(db):
    c = sqlite3.connect(db)
    assert c.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    assert {"KARTEN", "PRODUKTE", "BESTELLUNGEN", "BESTELLUNGSINHALT", "EINSTELLUNGEN"} <= database._tables(c)
    assert not glob.glob(db + ".*.bak"), "Neue DB braucht kein Backup"


def test_v1_migration(tmp_path, monkeypatch):
    path = str(tmp_path / "data.db")
    make_v1(path)
    monkeypatch.setattr(database, "DB_PATH", path)
    database.setup_db()
    database.setup_db()  # idempotent

    c = sqlite3.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert len(glob.glob(path + ".v1-*.bak")) == 1

    s = database.get_state()
    produkte = {p["id"]: p for p in s["produkte"]}
    assert produkte[1]["preis_cent"] == 750 and produkte[2]["pfand_cent"] == 200
    assert produkte[3]["name"].startswith("Gelöschtes Produkt") and not produkte[3]["aktiv"]
    assert produkte[77]["name"].startswith("Gelöschtes Produkt")
    assert produkte[4]["name"] == "Produkt 4"  # NULL-Name

    b = {x["id"]: x for x in s["bestellungen"]}
    # Duplikate zusammengeführt, Pfand rekonstruiert
    assert sorted((p["id"], p["anzahl"]) for p in b[1]["produkte"]) == [(1, 1), (2, 2)]
    assert b[1]["pfand_cent"] == 400 and b[1]["preis_cent"] == 1080
    # Status: abholbereit -> bereit, mit Fertig-Zeitpunkt
    assert b[2]["status"] == "bereit" and b[2]["zeitpunkt_bereit"] == "2025-12-06T16:39:00Z"
    assert b[1]["zeitpunkt_bereit"] == "2025-12-06T16:09:00Z"
    assert b[3]["status"] == "bestellt" and b[3]["karte"] is None and b[3]["eigenbedarf"]
    assert b[4]["karte"] is None  # Karte 99 existiert nicht
    assert b[5]["preis_cent"] == 30  # 0.1+0.2 Float-Fehler sauber gerundet
    assert [(p["id"], p["anzahl"]) for p in b[5]["produkte"]] == [(1, 2)]  # anzahl 0 verworfen
    assert not any(t.endswith("_OLD") or t.startswith("_V1") for t in database._tables(c))


def test_v2_migration(tmp_path, monkeypatch):
    """Eine DB im Zwischenstand v2 (wie gerade im Einsatz) wird auf v3 gehoben."""
    path = str(tmp_path / "data.db")
    c = sqlite3.connect(path)
    c.executescript(database.SCHEMA_V2)
    c.executescript("""
        INSERT INTO PRODUKTE (name, preis_cent, pfand_cent) VALUES ('A', 500, 0), ('B', 300, 200);
        INSERT INTO KARTEN (beschreibung) VALUES ('K1');
        INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, status, karte, eigenbedarf, preis_cent, pfand_cent, client_ref)
            VALUES ('2026-11-12 20:00:00', 'bestellt', 1, 0, 800, 200, 'abcdefgh12'),
                   ('2026-11-12 20:01:00', 'abgeholt', NULL, 1, 0, 0, NULL);
        INSERT INTO BESTELLUNGSINHALT VALUES (1, 1, 1, 500), (1, 2, 1, 300), (2, 2, 3, 300);
        PRAGMA user_version = 2;
    """)
    c.close()
    monkeypatch.setattr(database, "DB_PATH", path)
    database.setup_db()

    s = database.get_state()
    b = {x["id"]: x for x in s["bestellungen"]}
    assert {p["id"]: p["einzelpfand_cent"] for p in b[1]["produkte"]} == {1: 0, 2: 200}
    assert all(p["einzelpfand_cent"] == 0 for p in b[2]["produkte"])  # Eigenbedarf
    assert s["karten"][0]["inUse"] is True
    assert len(glob.glob(path + ".v2-*.bak")) == 1
    # client_ref-Eindeutigkeit und Autoincrement überleben den Tabellen-Umbau
    pruef = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        pruef.execute("INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, client_ref) VALUES ('x', 'abcdefgh12')")
    pruef.rollback()
    pruef.close()
    neu = database.add_bestellung({"produkte": [{"id": 1, "anzahl": 1}]})
    assert neu["id"] == 3


def test_migration_rollback(tmp_path, monkeypatch):
    """Scheitert die Migration, bleibt die DB exakt wie vorher (eine Transaktion)."""
    path = str(tmp_path / "data.db")
    make_v1(path)
    c = sqlite3.connect(path)
    c.execute("ALTER TABLE PRODUKTE RENAME COLUMN pfand TO kaputt")  # Migration muss scheitern
    c.commit()
    vorher = c.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    c.close()

    monkeypatch.setattr(database, "DB_PATH", path)
    with pytest.raises(sqlite3.OperationalError):
        database.setup_db()

    c = sqlite3.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    assert c.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == vorher
    assert c.execute("SELECT count(*) FROM BESTELLUNGEN").fetchone()[0] == 5
