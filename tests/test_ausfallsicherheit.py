"""Ausfallsicherheit: harter Absturz mitten im Betrieb, automatische Sicherungen,
fester Datenbank-Pfad, Logo und Sprüche."""

import io
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

import database
import printer
from conftest import http

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """Echter Server-Prozess (main.py), den man hart abschießen kann"""

    def __init__(self, tmp_path, **env):
        self.port = freier_port()
        self.base = f"127.0.0.1:{self.port}"
        self.env = dict(os.environ, KASSE_DB=str(tmp_path / "data.db"), PORT=str(self.port),
                        PRINTER_DEV=str(tmp_path / "kein_drucker"),
                        KASSE_BACKUP_DIR=str(tmp_path / "backups"), **env)
        self.p = None

    def start(self):
        self.p = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:
                if http(self.base, "GET", "/api/state", timeout=1)[0] == 200:
                    return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Server startet nicht")

    def kill(self, sig=signal.SIGKILL):
        self.p.send_signal(sig)
        self.p.wait(timeout=10)


def test_harter_absturz_verliert_keine_bestaetigte_bestellung(tmp_path):
    srv = Server(tmp_path)
    srv.start()
    pid = http(srv.base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    bestaetigt = set()
    lock = threading.Lock()

    for runde in range(3):
        stop = threading.Event()

        def kasse(n):
            i = 0
            while not stop.is_set():
                try:
                    s, d = http(srv.base, "POST", "/api/bestellungen",
                                {"produkte": [{"id": pid, "anzahl": 1}], "client_ref": f"r{runde}k{n}i{i:05d}"},
                                timeout=2)
                    if s == 201:
                        with lock:
                            bestaetigt.add(d["id"])
                except Exception:
                    pass  # Verbindung bricht beim Abschuss ab – das ist gewollt
                i += 1

        threads = [threading.Thread(target=kasse, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        time.sleep(1.5)
        srv.kill()  # kill -9 mitten im Schreiben – kein Aufräumen möglich
        stop.set()
        for t in threads:
            t.join()
        srv.start()

    st = http(srv.base, "GET", "/api/state")[1]
    vorhanden = {b["id"] for b in st["bestellungen"]}
    srv.kill(signal.SIGTERM)
    assert len(bestaetigt) > 50, "Test hat zu wenig Last erzeugt"
    fehlend = bestaetigt - vorhanden
    assert not fehlend, f"{len(fehlend)} bestätigte Bestellungen verloren"
    c = sqlite3.connect(str(tmp_path / "data.db"))
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print(f"\n  {len(bestaetigt)} bestätigte Bestellungen, 3× kill -9, nichts verloren")


def test_automatische_sicherungen(tmp_path):
    srv = Server(tmp_path, KASSE_BACKUP_MINUTEN="0.02", KASSE_BACKUP_BEHALTEN="4")  # alle ~1,2 s
    srv.start()
    pid = http(srv.base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    for _ in range(5):
        http(srv.base, "POST", "/api/bestellungen", {"produkte": [{"id": pid, "anzahl": 1}]})
        time.sleep(1.4)
    info = http(srv.base, "GET", "/api/sicherungen")[1]
    assert info["letzte"]["zeit"] and info["letzte"]["fehler"] is None
    srv.kill(signal.SIGTERM)  # sauberes Beenden -> Sicherung "ende"

    dateien = sorted(os.listdir(tmp_path / "backups"))
    assert len(dateien) <= 4, f"Alte Sicherungen müssen aufgeräumt werden: {dateien}"
    assert any(f.endswith("-ende.db") for f in dateien)
    assert not any(f.endswith(".tmp") for f in dateien)
    neueste = sqlite3.connect(str(tmp_path / "backups" / dateien[-1]))
    assert neueste.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert neueste.execute("SELECT count(*) FROM BESTELLUNGEN").fetchone()[0] == 5


def test_ohne_aenderung_keine_neue_sicherung(tmp_path):
    srv = Server(tmp_path, KASSE_BACKUP_MINUTEN="0.01")
    srv.start()
    time.sleep(2)
    srv.kill()
    # nur die Start-Sicherung, keine leeren Wiederholungen
    assert len(os.listdir(tmp_path / "backups")) == 1


def test_datenbankpfad_unabhaengig_vom_startordner(tmp_path):
    """Früher: Start aus einem anderen Ordner -> neue leere data.db -> 'alle Daten weg'."""
    env = {k: v for k, v in os.environ.items() if k != "KASSE_DB"}
    env["PYTHONPATH"] = os.pathsep.join([ROOT] + sys.path)
    out = subprocess.check_output([sys.executable, "-c", "import database; print(database.DB_PATH)"],
                                  cwd=str(tmp_path), env=env, text=True).strip()
    assert out == os.path.join(ROOT, "data.db")


def test_sicherung_api(api):
    a = api.produkt()
    api.bestellen([(a, 1)])
    s, d = api.post("/api/sicherungen")
    assert s == 200
    pfad = os.path.join(database.BACKUP_DIR, d["datei"])
    assert sqlite3.connect(pfad).execute("SELECT count(*) FROM BESTELLUNGEN").fetchone()[0] == 1
    r = api.c.get("/api/sicherungen/download")
    assert r.status_code == 200 and r.data[:16] == b"SQLite format 3\x00"


# ---------------------------------------------------------------- Logo & Sprüche

def png(breite, hoehe, mode="RGBA"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (breite, hoehe), (200, 30, 30, 255) if mode == "RGBA" else 128).save(buf, "PNG")
    return buf.getvalue()


def test_logo_hochladen_und_drucken(api, client, tmp_path, monkeypatch):
    r = client.put("/api/drucker/logo", data=png(1200, 400), content_type="image/png")
    assert r.status_code == 200 and r.get_json()["breite"] == 576
    st = api.state()["einstellungen"]
    assert st["bon_logo_vorhanden"] is True and "bon_logo_png" not in st
    assert len(json.dumps(api.state())) < 20000, "Logo darf nicht im Live-Zustand stecken"
    r = client.get("/api/drucker/logo.png")
    from PIL import Image
    img = Image.open(io.BytesIO(r.data))
    assert r.status_code == 200 and img.mode == "L" and img.width == 576

    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(dev))
    api.put("/api/einstellungen", {"bon_logo": True})
    a = api.produkt()
    assert api.bestellen([(a, 1)])[1]["gedruckt"] is True
    data = dev.read_bytes()
    assert b"\x1dv0" in data or b"\x1b*" in data, "Logo muss als Rasterbild gedruckt werden"

    assert client.delete("/api/drucker/logo").status_code == 200
    assert client.get("/api/drucker/logo.png").status_code == 404
    assert api.state()["einstellungen"]["bon_logo_vorhanden"] is False


@pytest.mark.parametrize("daten,status", [
    (b"", 400), (b"kein bild", 400), (b"\x89PNG\r\n\x1a\nkaputt", 400), (b"x" * (3 * 1024 * 1024 + 1), 413),
])
def test_logo_ungueltig(client, daten, status):
    assert client.put("/api/drucker/logo", data=daten, content_type="image/png").status_code == status


def test_sprueche_einstellbar(api, tmp_path, monkeypatch):
    assert len(api.state()["einstellungen"]["bon_sprueche_liste"]) > 5  # Standard aus Datei
    assert api.put("/api/einstellungen", {"bon_sprueche_liste": "nein"})[0] == 400
    assert api.put("/api/einstellungen", {"bon_sprueche_liste": [1, 2]})[0] == 400
    assert api.put("/api/einstellungen", {"bon_sprueche_liste": ["x" * 301]})[0] == 400
    assert api.put("/api/einstellungen", {"bon_sprueche_liste": ["Nur dieser\nSpruch", "  ", ""]})[0] == 200
    assert api.state()["einstellungen"]["bon_sprueche_liste"] == ["Nur dieser\nSpruch"]
    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(dev))
    a = api.produkt()
    api.bestellen([(a, 1)])
    assert b"Nur dieser\nSpruch" in dev.read_bytes()


def test_reset_behaelt_logo_und_einstellungen(api, client):
    client.put("/api/drucker/logo", data=png(100, 50), content_type="image/png")
    api.put("/api/einstellungen", {"titel": "Sommerfest", "bon_kopf": "Hallo"})
    api.produkt()
    assert api.post("/api/reset", {"bestaetigung": "RESET"})[0] == 200
    st = api.state()
    assert st["produkte"] == [] and st["einstellungen"]["titel"] == "Sommerfest"
    assert st["einstellungen"]["bon_logo_vorhanden"] is True


# ---------- Start nach Stromausfall: kaputte Datenbank wird automatisch ersetzt ----------

@pytest.fixture
def mit_sicherung(api, tmp_path, monkeypatch):
    monkeypatch.setattr(database, "BACKUP_DIR", str(tmp_path / "backups"))
    pid = api.post("/api/produkte", {"name": "Wurst", "preis_cent": 300})[1]["id"]
    assert api.bestellen([(pid, 2)])[0] == 201
    assert database.sicherung_erstellen("auto")
    return database.DB_PATH


def _anzahl_bestellungen(pfad):
    con = sqlite3.connect(pfad)
    try:
        return con.execute("SELECT COUNT(*) FROM BESTELLUNGEN").fetchone()[0]
    finally:
        con.close()


def test_startpruefung_intakte_db_bleibt(mit_sicherung):
    vorher = os.path.getmtime(mit_sicherung)
    assert database.startpruefung() is None
    assert os.path.getmtime(mit_sicherung) == vorher


def test_startpruefung_ohne_db_nichts_zu_tun(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "neu.db"))
    assert database.startpruefung() is None
    assert not os.path.exists(tmp_path / "neu.db")


@pytest.mark.parametrize("schaden", ["muell", "leer", "abgeschnitten"])
def test_startpruefung_kaputte_db_wird_aus_sicherung_ersetzt(mit_sicherung, schaden):
    pfad = mit_sicherung
    inhalt = open(pfad, "rb").read()
    with open(pfad, "wb") as f:
        if schaden == "muell":
            f.write(b"\x00kaputt" * 5000)
        elif schaden == "abgeschnitten":
            f.write(inhalt[: len(inhalt) // 2])
    meldung = database.startpruefung()
    assert meldung and "eingespielt" in meldung
    assert _anzahl_bestellungen(pfad) == 1
    assert any(".kaputt-" in f for f in os.listdir(os.path.dirname(pfad)))  # Beweisstück bleibt
    database.setup_db()  # danach startet der Server ganz normal
    assert database.startpruefung() is None


def test_startpruefung_ueberspringt_kaputte_sicherung(mit_sicherung):
    neueste = os.path.join(database.BACKUP_DIR, "kasse-99991231-235959-auto.db")
    with open(neueste, "wb") as f:
        f.write(b"kaputt")
    with open(mit_sicherung, "wb") as f:
        f.write(b"kaputt")
    assert "eingespielt" in database.startpruefung()
    assert _anzahl_bestellungen(mit_sicherung) == 1


def test_startpruefung_ohne_sicherung_neue_db(db, tmp_path, monkeypatch):
    monkeypatch.setattr(database, "BACKUP_DIR", str(tmp_path / "gibtsnicht"))
    with open(db, "wb") as f:
        f.write(b"kaputt" * 100)
    assert "keine Sicherung" in database.startpruefung()
    database.setup_db()
    assert _anzahl_bestellungen(db) == 0


def test_server_startet_trotz_kaputter_db(tmp_path):
    srv = Server(tmp_path)
    srv.start()
    pid = http(srv.base, "POST", "/api/produkte", {"name": "Brot", "preis_cent": 100})[1]["id"]
    assert http(srv.base, "POST", "/api/bestellungen", {"produkte": [{"id": pid, "anzahl": 1}]})[0] == 201
    srv.kill(signal.SIGTERM)  # schreibt Sicherung "ende"
    with open(tmp_path / "data.db", "r+b") as f:
        f.seek(0)
        f.write(b"\xff" * 4096)
    srv.start()
    try:
        assert http(srv.base, "GET", "/api/state")[0] == 200
        assert _anzahl_bestellungen(str(tmp_path / "data.db")) == 1
    finally:
        srv.kill()
