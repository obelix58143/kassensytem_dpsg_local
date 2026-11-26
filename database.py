"""SQLite-Zugriff für das Kassensystem.

- Beträge werden als ganze Cent gespeichert (keine Float-Rundungsfehler).
- Zeitstempel werden in UTC gespeichert ("YYYY-MM-DD HH:MM:SS") und als ISO-8601
  mit "Z" ausgeliefert; das Frontend rechnet in Lokalzeit um.
- Status gibt es nur noch zwei: "bestellt" und "abgeholt".
- Eine alte Datenbank (Schema v1) wird beim Start automatisch migriert,
  vorher wird eine Sicherungskopie angelegt.
"""

import json
import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("KASSE_DB", os.path.join(BASE_DIR, "data.db"))

SCHEMA_VERSION = 4
TYPEN = ("normal", "pfand")  # pfand = Pfandrückgabe-Produkt
STATUS = ("bestellt", "bereit", "abgeholt")

# SQLite verträgt nur einen Schreiber gleichzeitig. Das Lock verhindert
# "database is locked", wenn zwei Kassen exakt gleichzeitig buchen.
_write_lock = threading.Lock()


class DBError(Exception):
    """Fachlicher Fehler, wird als HTTP-Fehler an den Client gegeben."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    # FULL: jede bestätigte Buchung ist auf der Platte, bevor die Kasse "OK" bekommt –
    # auch bei Stromausfall (soweit die Hardware fsync ehrlich umsetzt)
    con.execute("PRAGMA synchronous = FULL")
    return con


# Zähler für Änderungen – die automatische Sicherung läuft nur, wenn sich etwas getan hat
aenderungen = 0


@contextmanager
def _read():
    con = _connect()
    try:
        yield con
    finally:
        con.close()


@contextmanager
def _write():
    with _write_lock:
        con = _connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
            global aenderungen
            aenderungen += 1
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()


def _iso(ts):
    """SQLite-UTC-Zeitstempel -> ISO-8601 mit Z (oder None)."""
    if ts is None:
        return None
    return ts.replace(" ", "T") + "Z"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --------------------------------------------------------------------------
# Schema & Migration
# --------------------------------------------------------------------------

SCHEMA_V2 = """
CREATE TABLE KARTEN(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beschreibung TEXT NOT NULL DEFAULT ''
);

CREATE TABLE PRODUKTE(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    beschreibung TEXT NOT NULL DEFAULT '',
    preis_cent INTEGER NOT NULL DEFAULT 0 CHECK (preis_cent >= 0),
    pfand_cent INTEGER NOT NULL DEFAULT 0 CHECK (pfand_cent >= 0),
    aktiv INTEGER NOT NULL DEFAULT 1,
    sortierung INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE BESTELLUNGEN(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitpunkt_annahme TEXT NOT NULL,
    zeitpunkt_abgeholt TEXT,
    status TEXT NOT NULL DEFAULT 'bestellt' CHECK (status IN ('bestellt', 'abgeholt')),
    karte INTEGER REFERENCES KARTEN(id) ON DELETE SET NULL,
    eigenbedarf INTEGER NOT NULL DEFAULT 0,
    preis_cent INTEGER NOT NULL DEFAULT 0,
    pfand_cent INTEGER NOT NULL DEFAULT 0,
    client_ref TEXT
);

CREATE TABLE BESTELLUNGSINHALT(
    bestellung_id INTEGER NOT NULL REFERENCES BESTELLUNGEN(id) ON DELETE CASCADE,
    produkt_id INTEGER NOT NULL REFERENCES PRODUKTE(id),
    anzahl INTEGER NOT NULL CHECK (anzahl > 0),
    einzelpreis_cent INTEGER NOT NULL,
    PRIMARY KEY (bestellung_id, produkt_id)
);

CREATE INDEX idx_bestellungen_status ON BESTELLUNGEN(status);
CREATE UNIQUE INDEX idx_bestellungen_client_ref ON BESTELLUNGEN(client_ref);
CREATE INDEX idx_inhalt_produkt ON BESTELLUNGSINHALT(produkt_id);
"""


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _backup(reason):
    if not os.path.exists(DB_PATH):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{DB_PATH}.{reason}-{stamp}.bak"
    # Über die SQLite-Backup-API, damit auch ein WAL-Inhalt mitkommt.
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _sql_v1_to_v2():
    """Altes Schema (Euro-Floats, 3 Status, Karte -1) -> v2.
    Status/Fertig-Zeitpunkt werden in _V1_STATUS gerettet und in v3 wieder eingespielt."""
    return """
        ALTER TABLE KARTEN RENAME TO KARTEN_OLD;
        ALTER TABLE PRODUKTE RENAME TO PRODUKTE_OLD;
        ALTER TABLE BESTELLUNGEN RENAME TO BESTELLUNGEN_OLD;
        ALTER TABLE BESTELLUNGSINHALT RENAME TO BESTELLUNGSINHALT_OLD;
    """ + SCHEMA_V2 + """
        INSERT INTO KARTEN (id, beschreibung)
            SELECT id, COALESCE(beschreibung, '') FROM KARTEN_OLD;

        INSERT INTO PRODUKTE (id, name, beschreibung, preis_cent, pfand_cent, aktiv, sortierung)
            SELECT id, COALESCE(name, 'Produkt ' || id), COALESCE(beschreibung, ''),
                   CAST(ROUND(COALESCE(preis, 0) * 100) AS INTEGER),
                   CAST(ROUND(COALESCE(pfand, 0) * 100) AS INTEGER),
                   1, id
            FROM PRODUKTE_OLD;

        -- Produkte, die gelöscht wurden, aber noch in Bestellungen stecken
        INSERT INTO PRODUKTE (id, name, beschreibung, preis_cent, pfand_cent, aktiv, sortierung)
            SELECT DISTINCT bi.produkt_id, 'Gelöschtes Produkt #' || bi.produkt_id, '', 0, 0, 0, bi.produkt_id
            FROM BESTELLUNGSINHALT_OLD bi
            WHERE bi.produkt_id IS NOT NULL
              AND bi.produkt_id NOT IN (SELECT id FROM PRODUKTE_OLD);

        INSERT INTO BESTELLUNGEN (id, zeitpunkt_annahme, zeitpunkt_abgeholt, status, karte,
                                  eigenbedarf, preis_cent, pfand_cent)
            SELECT b.id, b.zeitpunkt_annahme,
                   CASE WHEN b.status = 'abgeholt'
                        THEN COALESCE(b.zeitpunkt_abgeholt, b.zeitpunkt_fertig, b.zeitpunkt_annahme) END,
                   CASE WHEN b.status = 'abgeholt' THEN 'abgeholt' ELSE 'bestellt' END,
                   CASE WHEN b.karte IN (SELECT id FROM KARTEN_OLD) THEN b.karte END,
                   CASE WHEN COALESCE(b.preis, 0) = 0 THEN 1 ELSE 0 END,
                   CAST(ROUND(COALESCE(b.preis, 0) * 100) AS INTEGER),
                   0
            FROM BESTELLUNGEN_OLD b
            WHERE b.zeitpunkt_annahme IS NOT NULL;

        CREATE TABLE _V1_STATUS AS
            SELECT id, status, zeitpunkt_fertig FROM BESTELLUNGEN_OLD WHERE zeitpunkt_annahme IS NOT NULL;

        INSERT INTO BESTELLUNGSINHALT (bestellung_id, produkt_id, anzahl, einzelpreis_cent)
            SELECT bi.bestellung_id, bi.produkt_id, SUM(bi.anzahl), COALESCE(p.preis_cent, 0)
            FROM BESTELLUNGSINHALT_OLD bi
            JOIN BESTELLUNGEN b ON b.id = bi.bestellung_id
            LEFT JOIN PRODUKTE p ON p.id = bi.produkt_id
            WHERE bi.anzahl > 0
            GROUP BY bi.bestellung_id, bi.produkt_id;

        -- Pfand wurde früher nicht gespeichert: aus aktuellem Produkt-Pfand rekonstruieren
        UPDATE BESTELLUNGEN SET pfand_cent = (
            SELECT COALESCE(SUM(bi.anzahl * p.pfand_cent), 0)
            FROM BESTELLUNGSINHALT bi JOIN PRODUKTE p ON p.id = bi.produkt_id
            WHERE bi.bestellung_id = BESTELLUNGEN.id
        ) WHERE eigenbedarf = 0;

        DROP TABLE BESTELLUNGSINHALT_OLD;
        DROP TABLE BESTELLUNGEN_OLD;
        DROP TABLE PRODUKTE_OLD;
        DROP TABLE KARTEN_OLD;
    """


def _sql_v2_to_v3(aus_v1):
    """v3: Status 'bereit' (optional), Pfandrückgabe-Produkte, Pfand je Position,
    Einstellungen. BESTELLUNGEN muss neu angelegt werden – SQLite kann CHECKs nicht ändern."""
    sql = """
        CREATE TABLE BESTELLUNGEN_NEU(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zeitpunkt_annahme TEXT NOT NULL,
            zeitpunkt_bereit TEXT,
            zeitpunkt_abgeholt TEXT,
            status TEXT NOT NULL DEFAULT 'bestellt' CHECK (status IN ('bestellt', 'bereit', 'abgeholt')),
            karte INTEGER REFERENCES KARTEN(id) ON DELETE SET NULL,
            eigenbedarf INTEGER NOT NULL DEFAULT 0,
            preis_cent INTEGER NOT NULL DEFAULT 0,
            pfand_cent INTEGER NOT NULL DEFAULT 0,
            nur_pfand INTEGER NOT NULL DEFAULT 0,
            client_ref TEXT
        );
        INSERT INTO BESTELLUNGEN_NEU (id, zeitpunkt_annahme, zeitpunkt_abgeholt, status, karte,
                                      eigenbedarf, preis_cent, pfand_cent, client_ref)
            SELECT id, zeitpunkt_annahme, zeitpunkt_abgeholt, status, karte,
                   eigenbedarf, preis_cent, pfand_cent, client_ref FROM BESTELLUNGEN;
        DROP TABLE BESTELLUNGEN;
        ALTER TABLE BESTELLUNGEN_NEU RENAME TO BESTELLUNGEN;
        CREATE INDEX idx_bestellungen_status ON BESTELLUNGEN(status);
        CREATE UNIQUE INDEX idx_bestellungen_client_ref ON BESTELLUNGEN(client_ref);

        ALTER TABLE PRODUKTE ADD COLUMN typ TEXT NOT NULL DEFAULT 'normal' CHECK (typ IN ('normal', 'pfand'));
        ALTER TABLE BESTELLUNGSINHALT ADD COLUMN einzelpfand_cent INTEGER NOT NULL DEFAULT 0;

        -- Pfand je Position war bisher nicht gespeichert: aus aktuellem Produkt-Pfand ableiten
        UPDATE BESTELLUNGSINHALT SET einzelpfand_cent = COALESCE(
            (SELECT p.pfand_cent FROM PRODUKTE p WHERE p.id = BESTELLUNGSINHALT.produkt_id), 0)
        WHERE bestellung_id IN (SELECT id FROM BESTELLUNGEN WHERE eigenbedarf = 0);

        CREATE TABLE EINSTELLUNGEN(
            schluessel TEXT PRIMARY KEY,
            wert TEXT NOT NULL
        );
    """
    if aus_v1:
        # Original-Daten: "abholbereit" und Fertig-Zeitpunkt (= Zubereitungszeit) übernehmen
        sql += """
        UPDATE BESTELLUNGEN SET
            zeitpunkt_bereit = (SELECT v.zeitpunkt_fertig FROM _V1_STATUS v WHERE v.id = BESTELLUNGEN.id),
            status = CASE WHEN status = 'bestellt'
                           AND (SELECT v.status FROM _V1_STATUS v WHERE v.id = BESTELLUNGEN.id) = 'abholbereit'
                          THEN 'bereit' ELSE status END;
        DROP TABLE _V1_STATUS;
        """
    return sql


def _sql_v3_to_v4():
    """v4: wer kassiert / wer ausgegeben hat (Ranking in der Statistik),
    Produkte auf dem Kundendisplay ausblendbar."""
    return """
        ALTER TABLE BESTELLUNGEN ADD COLUMN kassierer TEXT;
        ALTER TABLE BESTELLUNGEN ADD COLUMN ausgabe TEXT;
        ALTER TABLE PRODUKTE ADD COLUMN display INTEGER NOT NULL DEFAULT 1;
    """


def _tables_sql_check(con):
    return con.execute("PRAGMA foreign_key_check").fetchall()


def setup_db():
    """Legt die DB an bzw. migriert sie schrittweise (v1 -> v2 -> v3). Idempotent.
    Die Migration läuft in EINER Transaktion: bei einem Fehler bleibt die DB unverändert."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    # isolation_level=None: Python startet/committet keine Transaktionen heimlich
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode = WAL")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        tables = _tables(con)
        if version >= SCHEMA_VERSION:
            return

        if not tables:
            script = SCHEMA_V2 + _sql_v2_to_v3(aus_v1=False) + _sql_v3_to_v4()
            print(f"[db] neue Datenbank angelegt: {DB_PATH}")
        else:
            von = max(version, 1)
            backup = _backup(f"v{von}")
            print(f"[db] migriere Schema v{von} -> v{SCHEMA_VERSION}, Sicherung: {backup}")
            script = ((_sql_v1_to_v2() if von < 2 else "")
                      + (_sql_v2_to_v3(aus_v1=von < 2) if von < 3 else "")
                      + _sql_v3_to_v4())

        con.execute("PRAGMA foreign_keys = OFF")  # wirkt nur außerhalb einer Transaktion
        try:
            con.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        problems = _tables_sql_check(con)
        if problems:
            print(f"[db] WARNUNG: Fremdschlüssel-Probleme nach Migration: {problems}")
    finally:
        con.close()


def hard_reset():
    """Sichert die aktuelle DB und leert dann alle Tabellen – in einer Transaktion,
    damit parallel lesende Geräte nie eine halb gelöschte Datenbank sehen."""
    backup = _backup("reset")
    with _write() as con:
        con.execute("DELETE FROM BESTELLUNGSINHALT")
        con.execute("DELETE FROM BESTELLUNGEN")
        con.execute("DELETE FROM PRODUKTE")
        con.execute("DELETE FROM KARTEN")
        # Einstellungen (Name, Drucker, Logo, Sprüche) bleiben erhalten
        con.execute("DELETE FROM sqlite_sequence")  # IDs starten wieder bei 1
    return backup


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------

def _produkt_dict(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "beschreibung": r["beschreibung"],
        "preis_cent": r["preis_cent"],
        "pfand_cent": r["pfand_cent"],
        "aktiv": bool(r["aktiv"]),
        "sortierung": r["sortierung"],
        "typ": r["typ"],
        "auf_display": bool(r["display"]),
    }


def get_produkte(con):
    rows = con.execute("SELECT * FROM PRODUKTE ORDER BY sortierung, id").fetchall()
    return [_produkt_dict(r) for r in rows]


def get_karten(con):
    rows = con.execute(
        """
        SELECT k.id, k.beschreibung,
               EXISTS(SELECT 1 FROM BESTELLUNGEN b WHERE b.karte = k.id AND b.status != 'abgeholt') AS in_use
        FROM KARTEN k ORDER BY k.id
        """
    ).fetchall()
    return [{"id": r["id"], "beschreibung": r["beschreibung"], "inUse": bool(r["in_use"])} for r in rows]


def get_bestellungen(con):
    inhalt = {}
    for r in con.execute("SELECT bestellung_id, produkt_id, anzahl, einzelpreis_cent, einzelpfand_cent FROM BESTELLUNGSINHALT"):
        inhalt.setdefault(r["bestellung_id"], []).append(
            {"id": r["produkt_id"], "anzahl": r["anzahl"], "einzelpreis_cent": r["einzelpreis_cent"],
             "einzelpfand_cent": r["einzelpfand_cent"]}
        )
    rows = con.execute("SELECT * FROM BESTELLUNGEN ORDER BY id DESC").fetchall()
    return [
        {
            "id": r["id"],
            "zeitpunkt_annahme": _iso(r["zeitpunkt_annahme"]),
            "zeitpunkt_bereit": _iso(r["zeitpunkt_bereit"]),
            "zeitpunkt_abgeholt": _iso(r["zeitpunkt_abgeholt"]),
            "status": r["status"],
            "karte": r["karte"],
            "eigenbedarf": bool(r["eigenbedarf"]),
            "preis_cent": r["preis_cent"],
            "pfand_cent": r["pfand_cent"],
            "nur_pfand": bool(r["nur_pfand"]),
            "kassierer": r["kassierer"],
            "ausgabe": r["ausgabe"],
            "produkte": inhalt.get(r["id"], []),
        }
        for r in rows
    ]


def get_state():
    """Kompletter Zustand – wird per WebSocket an alle Clients gepusht."""
    with _read() as con:
        return {
            "produkte": get_produkte(con),
            "karten": get_karten(con),
            "bestellungen": get_bestellungen(con),
            "einstellungen": get_einstellungen(con),
            "server_time": now_iso(),
        }


def _standard_sprueche():
    try:
        with open(os.path.join(BASE_DIR, "printer_files", "sprueche.json"), encoding="utf-8") as f:
            return [x for x in json.load(f) if isinstance(x, str) and x.strip()][:200]
    except (OSError, ValueError):
        return []


EINSTELLUNGEN_STANDARD = {
    "titel": "Kasse",                 # Name in Kopfzeile, Kundendisplay, Browser-Tab
    "bereit_aktiv": False,            # Zwischenschritt "Bereit zur Abholung" verwenden
    "name_kasse": True,               # Kasse fragt nach dem Namen (Ranking in der Statistik)
    "name_ausgabe": True,             # Ausgabe fragt nach dem Namen (Ranking in der Statistik)
    # --- Bondrucker (ESC/POS) ---
    "drucker_aktiv": True,            # aus = es wird nie gedruckt
    "drucker_verbindung": "usb",      # "usb" (Gerätedatei) oder "netzwerk" (RAW, Port 9100)
    "drucker_geraet": "/dev/usb/lp0",
    "drucker_host": "",
    "drucker_port": 9100,
    "bon_breite_mm": 58,              # 58 oder 80
    "bon_kopf": "Vielen Dank für deine Bestellung!",
    "bon_fuss": "",
    "bon_logo": False,                # druckt printer_files/logo.png, falls vorhanden
    "bon_positionen": True,
    "bon_karte": True,
    "bon_sprueche": True,             # zufälliger Spruch aus bon_sprueche_liste
    "bon_sprueche_liste": _standard_sprueche(),
    "bon_gewinn_alle": 0,             # jede N-te Bestellung bekommt den Gewinn-Text (0 = aus)
    "bon_gewinn_text": "Glückwunsch! Du bist unsere {n}. Bestellung.",
}

_TEXT_MAX = {"titel": 60, "bon_kopf": 300, "bon_fuss": 300, "bon_gewinn_text": 200,
             "drucker_geraet": 64, "drucker_host": 253}
# Nur echte Druckergeräte – sonst könnte man über die Weboberfläche beliebige Dateien beschreiben
_GERAET = re.compile(r"^/dev/(usb/lp\d{1,2}|lp\d{1,2}|ttyUSB\d{1,2}|ttyACM\d{1,2}|rfcomm\d{1,2})$")
_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")


def _pruefe_einstellung(key, value):
    if key not in EINSTELLUNGEN_STANDARD:
        raise DBError(f"Unbekannte Einstellung: {key}")
    if type(value) is not type(EINSTELLUNGEN_STANDARD[key]):
        raise DBError(f"Falscher Typ für {key}")
    if isinstance(value, str):
        value = value.strip() if key not in ("bon_kopf", "bon_fuss") else value.strip("\n ")
        if len(value) > _TEXT_MAX.get(key, 200):
            raise DBError(f"{key} ist zu lang")
    if key == "titel" and not value:
        raise DBError("Der Name darf nicht leer sein")
    if key == "drucker_verbindung" and value not in ("usb", "netzwerk"):
        raise DBError("Verbindung muss 'usb' oder 'netzwerk' sein")
    if key == "drucker_geraet" and not _GERAET.match(value):
        raise DBError("Ungültiges Druckergerät (erlaubt z.B. /dev/usb/lp0, /dev/ttyUSB0)")
    if key == "drucker_host" and value and not _HOST.match(value):
        raise DBError("Ungültige Drucker-Adresse")
    if key == "drucker_port" and not 1 <= value <= 65535:
        raise DBError("Ungültiger Port")
    if key == "bon_breite_mm" and value not in (58, 80):
        raise DBError("Papierbreite muss 58 oder 80 mm sein")
    if key == "bon_sprueche_liste":
        if len(value) > 200 or not all(isinstance(x, str) for x in value):
            raise DBError("Sprüche: Liste von höchstens 200 Texten erwartet")
        value = [x.strip("\n ") for x in value if x.strip()]
        if any(len(x) > 300 for x in value):
            raise DBError("Ein Spruch ist zu lang (max. 300 Zeichen)")
    if key == "bon_gewinn_alle" and not 0 <= value <= 100000:
        raise DBError("Ungültiger Wert für 'jede N-te Bestellung'")
    return value


def get_einstellungen(con=None):
    if con is None:
        with _read() as c:
            return get_einstellungen(c)
    out = dict(EINSTELLUNGEN_STANDARD)
    # Das Logo selbst (bis ~100 kB) nicht bei jedem Live-Update mitschicken
    out["bon_logo_vorhanden"] = con.execute(
        "SELECT 1 FROM EINSTELLUNGEN WHERE schluessel = 'bon_logo_png'").fetchone() is not None
    for r in con.execute("SELECT schluessel, wert FROM EINSTELLUNGEN"):
        if r["schluessel"] in out and r["schluessel"] != "bon_logo_vorhanden":
            try:
                out[r["schluessel"]] = json.loads(r["wert"])
            except ValueError:
                pass
    return out


def set_einstellungen(data):
    if not data:
        raise DBError("Keine Einstellungen übergeben")
    clean = {k: _pruefe_einstellung(k, v) for k, v in data.items()}
    with _write() as con:
        con.executemany(
            "INSERT INTO EINSTELLUNGEN (schluessel, wert) VALUES (?, ?) "
            "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            [(k, json.dumps(v)) for k, v in clean.items()],
        )
        return get_einstellungen(con)


# ---------- Bon-Logo (in der DB, damit es in jeder Sicherung steckt) ----------

LOGO_MAX_BYTES = 2_000_000


def set_logo(roh):
    """roh: Bilddatei (PNG/JPEG/GIF/BMP). Wird geprüft, auf max. 576 px Breite verkleinert,
    in Graustufen umgewandelt und ohne Metadaten als PNG gespeichert."""
    import base64
    import io
    from PIL import Image, UnidentifiedImageError

    if not roh or len(roh) > LOGO_MAX_BYTES:
        raise DBError("Logo fehlt oder ist zu groß (max. 2 MB)")
    try:
        img = Image.open(io.BytesIO(roh))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise DBError("Das ist keine gültige Bilddatei")
    if img.width * img.height > 25_000_000:
        raise DBError("Bild hat zu viele Pixel")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        weiss = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(weiss, img)
    img = img.convert("L")
    if img.width > 576:
        img = img.resize((576, max(1, round(img.height * 576 / img.width))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    with _write() as con:
        con.execute(
            "INSERT INTO EINSTELLUNGEN (schluessel, wert) VALUES ('bon_logo_png', ?) "
            "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (json.dumps(base64.b64encode(buf.getvalue()).decode()),),
        )
    return {"breite": img.width, "hoehe": img.height}


def get_logo():
    """PNG-Bytes des Logos oder None"""
    import base64
    with _read() as con:
        r = con.execute("SELECT wert FROM EINSTELLUNGEN WHERE schluessel = 'bon_logo_png'").fetchone()
    return base64.b64decode(json.loads(r["wert"])) if r else None


def delete_logo():
    with _write() as con:
        con.execute("DELETE FROM EINSTELLUNGEN WHERE schluessel = 'bon_logo_png'")


# ---------- Automatische Sicherungen ----------

BACKUP_DIR = os.environ.get("KASSE_BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
BACKUP_BEHALTEN = int(os.environ.get("KASSE_BACKUP_BEHALTEN", "72"))
_backup_lock = threading.Lock()
letzte_sicherung = {"zeit": None, "datei": None, "fehler": None}


def sicherung_erstellen(grund="auto"):
    """Konsistente Kopie der laufenden DB (SQLite-Backup-API, auch während gebucht wird)."""
    with _backup_lock:
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            ziel = os.path.join(BACKUP_DIR, f"kasse-{stamp}-{grund}.db")
            tmp = ziel + ".tmp"
            src = sqlite3.connect(DB_PATH, timeout=10)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
                ok = dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                dst.close()
                src.close()
            if not ok:
                os.remove(tmp)
                raise RuntimeError("Sicherung fehlerhaft")
            os.replace(tmp, ziel)  # erst nach erfolgreicher Prüfung sichtbar
            alte = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("kasse-") and f.endswith(".db"))
            for f in alte[:-BACKUP_BEHALTEN] if BACKUP_BEHALTEN > 0 else []:
                os.remove(os.path.join(BACKUP_DIR, f))
            letzte_sicherung.update(zeit=now_iso(), datei=os.path.basename(ziel), fehler=None)
            return ziel
        except Exception as e:  # noqa: BLE001 – Sicherung darf den Betrieb nie stören
            letzte_sicherung.update(fehler=str(e))
            print(f"[backup] Fehler: {e}")
            return None


def _db_ok(pfad):
    """True, wenn die Datei eine intakte Kassen-Datenbank ist."""
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True, timeout=10)
    try:
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            return False
        return "BESTELLUNGEN" in _tables(con)
    finally:
        con.close()


def startpruefung():
    """Beim Start: Ist die Datenbank nach einem Absturz/Stromausfall kaputt (oder leer
    überschrieben), wird sie beiseitegelegt und die neueste intakte Sicherung eingespielt.
    Gibt eine Meldung zurück, wenn etwas wiederhergestellt wurde, sonst None."""
    if not os.path.exists(DB_PATH):
        return None  # Erstinstallation
    try:
        if _db_ok(DB_PATH):
            return None
        grund = "Prüfung fehlgeschlagen"
    except sqlite3.DatabaseError as e:
        if "locked" in str(e) or "unable to open" in str(e):
            raise  # kein Defekt der Datei – nichts anfassen
        grund = str(e)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for endung in ("", "-wal", "-shm"):
        if os.path.exists(DB_PATH + endung):
            os.replace(DB_PATH + endung, f"{DB_PATH}.kaputt-{stamp}{endung}")
    for name in sicherungen_auflisten():
        quelle = os.path.join(BACKUP_DIR, name)
        try:
            if not _db_ok(quelle):
                continue
        except sqlite3.DatabaseError:
            continue
        tmp = DB_PATH + ".tmp"
        shutil.copyfile(quelle, tmp)
        with open(tmp, "rb") as f:
            os.fsync(f.fileno())
        os.replace(tmp, DB_PATH)
        meldung = f"Datenbank war beschädigt ({grund}) – Sicherung {name} eingespielt"
        print(f"[db] WARNUNG: {meldung}")
        return meldung
    meldung = f"Datenbank war beschädigt ({grund}) – keine Sicherung vorhanden, neue leere Datenbank"
    print(f"[db] WARNUNG: {meldung}")
    return meldung


def sicherungen_auflisten():
    try:
        namen = [f for f in os.listdir(BACKUP_DIR) if f.startswith("kasse-") and f.endswith(".db")]
        # neueste zuerst – nach Änderungszeit, weil "start" und "ende" in derselben Sekunde liegen können
        return sorted(namen, key=lambda f: (os.path.getmtime(os.path.join(BACKUP_DIR, f)), f), reverse=True)
    except OSError:
        return []


def get_bestellung(id):
    with _read() as con:
        r = con.execute("SELECT * FROM BESTELLUNGEN WHERE id = ?", (id,)).fetchone()
        if r is None:
            raise DBError("Bestellung nicht gefunden", 404)
        # Pfandrückgaben gehören nicht auf den Abhol-Bon
        produkte = con.execute(
            """SELECT p.name, bi.anzahl FROM BESTELLUNGSINHALT bi JOIN PRODUKTE p ON p.id = bi.produkt_id
               WHERE bi.bestellung_id = ? AND p.typ = 'normal' ORDER BY p.sortierung, p.id""",
            (id,),
        ).fetchall()
        karte = None
        if r["karte"] is not None:
            k = con.execute("SELECT beschreibung FROM KARTEN WHERE id = ?", (r["karte"],)).fetchone()
            karte = k["beschreibung"] if k else None
        return {
            "id": r["id"],
            "karte": karte,
            "nur_pfand": bool(r["nur_pfand"]),
            "produkte": [{"name": p["name"], "anzahl": p["anzahl"]} for p in produkte],
        }


def get_last_bestellung_id():
    with _read() as con:
        return con.execute("SELECT MAX(id) FROM BESTELLUNGEN").fetchone()[0]


def export_rows():
    with _read() as con:
        return con.execute(
            """
            SELECT b.id, datetime(b.zeitpunkt_annahme, 'localtime') AS zeitpunkt_annahme,
                   datetime(b.zeitpunkt_abgeholt, 'localtime') AS zeitpunkt_abgeholt, b.status,
                   k.beschreibung AS karte, b.eigenbedarf, p.name AS produkt,
                   p.typ, bi.anzahl, bi.einzelpreis_cent, bi.einzelpfand_cent, b.preis_cent, b.pfand_cent,
                   b.kassierer, b.ausgabe
            FROM BESTELLUNGEN b
            JOIN BESTELLUNGSINHALT bi ON bi.bestellung_id = b.id
            JOIN PRODUKTE p ON p.id = bi.produkt_id
            LEFT JOIN KARTEN k ON k.id = b.karte
            ORDER BY b.id, p.sortierung, p.id
            """
        ).fetchall()


# --------------------------------------------------------------------------
# Validierung
# --------------------------------------------------------------------------

def _cent(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 1_000_000:
        raise DBError(f"{field} muss eine ganze Zahl in Cent >= 0 sein")
    return value


def _person(value):
    """Name von Kassierer:in / Ausgabe – optional, leer = unbekannt."""
    if value is None:
        return None
    return _text(value, "Name", 40) or None


def _text(value, field, max_len=200):
    if not isinstance(value, str):
        raise DBError(f"{field} muss ein Text sein")
    value = value.strip()
    if len(value) > max_len:
        raise DBError(f"{field} ist zu lang (max. {max_len} Zeichen)")
    return value


# --------------------------------------------------------------------------
# Produkte
# --------------------------------------------------------------------------

def create_produkt(data):
    typ = data.get("typ", "normal")
    if typ not in TYPEN:
        raise DBError(f"Ungültiger Produkttyp, erlaubt: {', '.join(TYPEN)}")
    standard = "Pfand zurück" if typ == "pfand" else "Neues Produkt"
    name = _text(data.get("name", standard), "Name") or standard
    preis = _cent(data.get("preis_cent", 0), "Preis")
    pfand = _cent(data.get("pfand_cent", 0), "Pfand")
    if typ == "pfand" and preis:
        raise DBError("Eine Pfandrückgabe hat keinen Preis, nur einen Rückgabebetrag (pfand_cent)")
    with _write() as con:
        sort = con.execute("SELECT COALESCE(MAX(sortierung), 0) + 1 FROM PRODUKTE").fetchone()[0]
        cur = con.execute(
            "INSERT INTO PRODUKTE (name, beschreibung, preis_cent, pfand_cent, sortierung, typ, display) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, _text(data.get("beschreibung", ""), "Beschreibung", 1000), preis, pfand, sort, typ,
             0 if data.get("auf_display") is False else 1),
        )
        return _produkt_dict(con.execute("SELECT * FROM PRODUKTE WHERE id = ?", (cur.lastrowid,)).fetchone())


def update_produkt(id, data):
    fields = {}
    if "name" in data:
        fields["name"] = _text(data["name"], "Name")
        if not fields["name"]:
            raise DBError("Name darf nicht leer sein")
    if "beschreibung" in data:
        fields["beschreibung"] = _text(data["beschreibung"], "Beschreibung", 1000)
    if "preis_cent" in data:
        fields["preis_cent"] = _cent(data["preis_cent"], "Preis")
    if "pfand_cent" in data:
        fields["pfand_cent"] = _cent(data["pfand_cent"], "Pfand")
    if "aktiv" in data:
        fields["aktiv"] = 1 if data["aktiv"] else 0
    if "auf_display" in data:
        fields["display"] = 1 if data["auf_display"] else 0
    if "sortierung" in data:
        if not isinstance(data["sortierung"], int):
            raise DBError("Sortierung muss eine Zahl sein")
        fields["sortierung"] = data["sortierung"]
    if not fields:
        raise DBError("Keine Änderungen übergeben")

    with _write() as con:
        r = con.execute("SELECT typ FROM PRODUKTE WHERE id = ?", (id,)).fetchone()
        if r is None:
            raise DBError("Produkt nicht gefunden", 404)
        if r["typ"] == "pfand" and fields.get("preis_cent"):
            raise DBError("Eine Pfandrückgabe hat keinen Preis, nur einen Rückgabebetrag")
        sets = ", ".join(f"{k} = ?" for k in fields)
        cur = con.execute(f"UPDATE PRODUKTE SET {sets} WHERE id = ?", (*fields.values(), id))
        if cur.rowcount == 0:
            raise DBError("Produkt nicht gefunden", 404)
        return _produkt_dict(con.execute("SELECT * FROM PRODUKTE WHERE id = ?", (id,)).fetchone())


def delete_produkt(id):
    """Löscht ein Produkt. Wurde es schon verkauft, wird es nur deaktiviert,
    damit Statistik und alte Bestellungen korrekt bleiben."""
    with _write() as con:
        if con.execute("SELECT 1 FROM PRODUKTE WHERE id = ?", (id,)).fetchone() is None:
            raise DBError("Produkt nicht gefunden", 404)
        used = con.execute("SELECT 1 FROM BESTELLUNGSINHALT WHERE produkt_id = ? LIMIT 1", (id,)).fetchone()
        if used:
            con.execute("UPDATE PRODUKTE SET aktiv = 0 WHERE id = ?", (id,))
            return "deaktiviert"
        con.execute("DELETE FROM PRODUKTE WHERE id = ?", (id,))
        return "geloescht"


# --------------------------------------------------------------------------
# Karten
# --------------------------------------------------------------------------

def create_karte(data):
    with _write() as con:
        cur = con.execute(
            "INSERT INTO KARTEN (beschreibung) VALUES (?)",
            (_text(data.get("beschreibung", ""), "Beschreibung") or "Neue Karte",),
        )
        return {"id": cur.lastrowid}


def update_karte(id, data):
    beschreibung = _text(data.get("beschreibung", ""), "Beschreibung")
    if not beschreibung:
        raise DBError("Beschreibung darf nicht leer sein")
    with _write() as con:
        cur = con.execute("UPDATE KARTEN SET beschreibung = ? WHERE id = ?", (beschreibung, id))
        if cur.rowcount == 0:
            raise DBError("Karte nicht gefunden", 404)


def delete_karte(id):
    with _write() as con:
        if con.execute("SELECT 1 FROM KARTEN WHERE id = ?", (id,)).fetchone() is None:
            raise DBError("Karte nicht gefunden", 404)
        if con.execute("SELECT 1 FROM BESTELLUNGEN WHERE karte = ? AND status != 'abgeholt'", (id,)).fetchone():
            raise DBError("Karte ist gerade in Benutzung", 409)
        con.execute("DELETE FROM KARTEN WHERE id = ?", (id,))


# --------------------------------------------------------------------------
# Bestellungen
# --------------------------------------------------------------------------

def add_bestellung(data):
    """Legt eine Bestellung an. Preise werden serverseitig aus den Produkten
    berechnet (der Client kann nichts manipulieren und nichts falsch rechnen)."""
    positionen = data.get("produkte")
    if not isinstance(positionen, list) or not positionen:
        raise DBError("Bestellung enthält keine Produkte")

    mengen = {}
    for pos in positionen:
        pid, anzahl = pos.get("id"), pos.get("anzahl")
        if not isinstance(pid, int) or not isinstance(anzahl, int) or isinstance(anzahl, bool) or anzahl < 1 or anzahl > 999:
            raise DBError("Ungültige Position in der Bestellung")
        mengen[pid] = mengen.get(pid, 0) + anzahl

    karte = data.get("karte")
    if karte is not None and not isinstance(karte, int):
        raise DBError("Ungültige Karte")
    eigenbedarf = bool(data.get("eigenbedarf", False))
    client_ref = data.get("client_ref")
    if client_ref is not None and (not isinstance(client_ref, str) or not 8 <= len(client_ref) <= 64):
        raise DBError("Ungültige client_ref")
    kassierer = _person(data.get("kassierer"))

    with _write() as con:
        # Wiederholte Anfrage (z.B. Timeout im WLAN, Kasse drückt nochmal):
        # bestehende Bestellung zurückgeben statt eine doppelte anzulegen.
        if client_ref:
            r = con.execute("SELECT id, preis_cent, pfand_cent, nur_pfand FROM BESTELLUNGEN WHERE client_ref = ?",
                            (client_ref,)).fetchone()
            if r:
                return {"id": r["id"], "preis_cent": r["preis_cent"], "pfand_cent": r["pfand_cent"],
                        "nur_pfand": bool(r["nur_pfand"]), "wiederholt": True}

        produkte = {}
        for pid in mengen:
            r = con.execute("SELECT * FROM PRODUKTE WHERE id = ?", (pid,)).fetchone()
            if r is None or not r["aktiv"]:
                raise DBError(f"Produkt {pid} ist nicht (mehr) verfügbar", 409)
            produkte[pid] = r

        # Pfandrückgabe-Produkte zählen negativ (Geld geht an den Kunden zurück)
        def einzelpfand(p):
            if eigenbedarf:
                return 0
            return -produkte[p]["pfand_cent"] if produkte[p]["typ"] == "pfand" else produkte[p]["pfand_cent"]

        nur_pfand = all(produkte[p]["typ"] == "pfand" for p in mengen)
        preis = 0 if eigenbedarf else sum(produkte[p]["preis_cent"] * n for p, n in mengen.items())
        pfand = sum(einzelpfand(p) * n for p, n in mengen.items())

        if nur_pfand:
            # Reine Rückgabe: nichts abzuholen, gleich erledigt, keine Karte
            cur = con.execute(
                """INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, zeitpunkt_abgeholt, status, karte, eigenbedarf,
                                             preis_cent, pfand_cent, client_ref, nur_pfand, kassierer)
                   VALUES (datetime('now'), datetime('now'), 'abgeholt', NULL, ?, 0, ?, ?, 1, ?)""",
                (int(eigenbedarf), pfand, client_ref, kassierer),
            )
        else:
            if karte is not None:
                if con.execute("SELECT 1 FROM KARTEN WHERE id = ?", (karte,)).fetchone() is None:
                    raise DBError("Karte nicht gefunden", 404)
                if con.execute("SELECT 1 FROM BESTELLUNGEN WHERE karte = ? AND status != 'abgeholt'", (karte,)).fetchone():
                    raise DBError("Karte ist bereits vergeben", 409)
            cur = con.execute(
                """INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, status, karte, eigenbedarf, preis_cent, pfand_cent,
                                            client_ref, kassierer)
                   VALUES (datetime('now'), 'bestellt', ?, ?, ?, ?, ?, ?)""",
                (karte, int(eigenbedarf), preis, pfand, client_ref, kassierer),
            )
        bid = cur.lastrowid
        con.executemany(
            """INSERT INTO BESTELLUNGSINHALT (bestellung_id, produkt_id, anzahl, einzelpreis_cent, einzelpfand_cent)
               VALUES (?, ?, ?, ?, ?)""",
            [(bid, p, n, produkte[p]["preis_cent"], einzelpfand(p)) for p, n in mengen.items()],
        )
        return {"id": bid, "preis_cent": preis, "pfand_cent": pfand, "nur_pfand": nur_pfand, "wiederholt": False}


def set_status(id, status, person=None):
    """bestellt -> [bereit] -> abgeholt, auch rückwärts (Rückgängig).
    person: wer an der Ausgabe fertig gemeldet hat (für die Statistik). Gezählt wird, wer die
    Bestellung als Erstes fertig meldet – mit Bereit-Schritt also, wer „Fertig" drückt."""
    if status not in STATUS:
        raise DBError(f"Ungültiger Status, erlaubt: {', '.join(STATUS)}")
    person = _person(person)
    with _write() as con:
        r = con.execute("SELECT status, karte, nur_pfand FROM BESTELLUNGEN WHERE id = ?", (id,)).fetchone()
        if r is None:
            raise DBError("Bestellung nicht gefunden", 404)
        if r["status"] == status:
            return
        if r["nur_pfand"]:
            raise DBError("Reine Pfandrückgabe – da gibt es nichts abzuholen", 409)
        if r["status"] == "abgeholt" and r["karte"] is not None and con.execute(
            "SELECT 1 FROM BESTELLUNGEN WHERE karte = ? AND status != 'abgeholt' AND id != ?", (r["karte"], id)
        ).fetchone():
            # Rückgängig, aber die Karte wurde inzwischen neu vergeben
            raise DBError("Karte wurde schon neu vergeben – rückgängig nicht möglich", 409)
        if status == "abgeholt":
            con.execute("""UPDATE BESTELLUNGEN SET status = 'abgeholt', zeitpunkt_abgeholt = datetime('now'),
                           ausgabe = COALESCE(ausgabe, ?) WHERE id = ?""", (person, id))
        elif status == "bereit":
            con.execute(
                """UPDATE BESTELLUNGEN SET status = 'bereit', zeitpunkt_abgeholt = NULL,
                   zeitpunkt_bereit = COALESCE(zeitpunkt_bereit, datetime('now')),
                   ausgabe = COALESCE(ausgabe, ?) WHERE id = ?""", (person, id))
        else:
            con.execute(
                """UPDATE BESTELLUNGEN SET status = 'bestellt', zeitpunkt_bereit = NULL, zeitpunkt_abgeholt = NULL,
                   ausgabe = NULL WHERE id = ?""", (id,))


def storno(id):
    with _write() as con:
        cur = con.execute("DELETE FROM BESTELLUNGEN WHERE id = ?", (id,))
        if cur.rowcount == 0:
            raise DBError("Bestellung nicht gefunden", 404)
