"""Nebenläufigkeit (mehrere Kassen), WebSocket-Live-Updates, Drucker-Ausfälle, Performance."""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import database
import flaskserver
import printer
from conftest import http

websocket = pytest.importorskip("websocket")


def test_parallele_kassen(live_server):
    base = live_server
    a = http(base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    b = http(base, "POST", "/api/produkte", {"name": "B", "preis_cent": 100, "pfand_cent": 50})[1]["id"]

    def kasse(n):
        ergebnisse = []
        for i in range(40):
            ergebnisse.append(http(base, "POST", "/api/bestellungen",
                                   {"produkte": [{"id": a, "anzahl": 1}, {"id": b, "anzahl": 2}],
                                    "client_ref": f"kasse{n}-bestellung{i:03d}"}))
        return ergebnisse

    with ThreadPoolExecutor(8) as ex:
        alle = [r for liste in ex.map(kasse, range(8)) for r in liste]
    assert all(s == 201 for s, _ in alle), {s for s, _ in alle}
    ids = [d["id"] for _, d in alle]
    assert len(set(ids)) == 320
    st = http(base, "GET", "/api/state")[1]
    assert len(st["bestellungen"]) == 320
    assert sum(x["preis_cent"] for x in st["bestellungen"]) == 320 * 450
    assert sum(x["pfand_cent"] for x in st["bestellungen"]) == 320 * 100


def test_rennen_um_dieselbe_karte(live_server):
    base = live_server
    a = http(base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    k = http(base, "POST", "/api/karten", {"beschreibung": "Rot"})[1]["id"]
    start = threading.Barrier(12)

    def versuch(i):
        start.wait()
        return http(base, "POST", "/api/bestellungen", {"produkte": [{"id": a, "anzahl": 1}], "karte": k})[0]

    with ThreadPoolExecutor(12) as ex:
        status = list(ex.map(versuch, range(12)))
    assert status.count(201) == 1 and status.count(409) == 11


def test_doppelter_request_gleichzeitig(live_server):
    """Kasse schickt dieselbe Bestellung zweimal fast gleichzeitig (Doppelklick + Retry)."""
    base = live_server
    a = http(base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    start = threading.Barrier(6)

    def senden(_):
        start.wait()
        return http(base, "POST", "/api/bestellungen", {"produkte": [{"id": a, "anzahl": 1}], "client_ref": "gleich-123456"})

    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(senden, range(6)))
    assert len({d["id"] for _, d in res}) == 1
    assert len(http(base, "GET", "/api/state")[1]["bestellungen"]) == 1


def _ws(base):
    ws = websocket.create_connection(f"ws://{base}/ws", timeout=5)
    first = json.loads(ws.recv())
    assert first["type"] == "state"
    return ws, first


def test_websocket_push_und_heartbeat(live_server):
    base = live_server
    clients = [_ws(base)[0] for _ in range(25)]
    t0 = time.time()
    http(base, "POST", "/api/produkte", {"name": "Neu", "preis_cent": 100})
    for ws in clients:
        msg = json.loads(ws.recv())
        assert msg["type"] == "state" and msg["data"]["produkte"][0]["name"] == "Neu"
    assert time.time() - t0 < 2, "Alle 25 Geräte müssen das Update sofort bekommen"
    # Heartbeat (im Test auf 1 s gesetzt)
    msg = json.loads(clients[0].recv())
    assert msg["type"] == "ping"
    for ws in clients:
        ws.close()
    time.sleep(2.5)  # Handler bemerken das Schließen spätestens beim nächsten Heartbeat
    assert len(flaskserver._clients) == 0, "Getrennte Clients müssen aufgeräumt werden"


def test_client_der_nicht_liest_bekommt_korrekten_endstand(live_server):
    base = live_server
    ws, _ = _ws(base)
    for i in range(30):  # 30 Änderungen, während der Client nicht liest
        http(base, "POST", "/api/karten", {"beschreibung": f"K{i}"})
    time.sleep(0.3)
    msgs = []
    ws.settimeout(0.5)
    try:
        while True:
            m = json.loads(ws.recv())
            if m["type"] == "state":
                msgs.append(m)
    except Exception:
        pass
    assert msgs and len(msgs[-1]["data"]["karten"]) == 30, "Letzter Stand muss vollständig sein"
    anzahl = [len(m["data"]["karten"]) for m in msgs]
    assert anzahl == sorted(anzahl), "Stände dürfen nie in falscher Reihenfolge ankommen"


def test_reset_waehrend_gelesen_wird(live_server):
    base = live_server
    a = http(base, "POST", "/api/produkte", {"name": "A", "preis_cent": 250})[1]["id"]
    for _ in range(20):
        http(base, "POST", "/api/bestellungen", {"produkte": [{"id": a, "anzahl": 1}]})
    stop = threading.Event()
    fehler = []

    def leser():
        while not stop.is_set():
            s, _ = http(base, "GET", "/api/state")
            if s != 200:
                fehler.append(s)

    threads = [threading.Thread(target=leser) for _ in range(4)]
    for t in threads:
        t.start()
    for _ in range(5):
        assert http(base, "POST", "/api/reset", {"bestaetigung": "RESET"})[0] == 200
    stop.set()
    for t in threads:
        t.join()
    assert fehler == []


# ---------------------------------------------------------------- Drucker

def test_drucker_schreibt_bon(api, tmp_path, monkeypatch):
    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(dev))
    gw = api.produkt("Glühwein", 350, 200)
    tasse = api.produkt("Tasse zurück", 0, 200, "pfand")
    k = api.karte("Rot 1")
    s, d = api.bestellen([(gw, 2), (tasse, 1)], karte=k)
    assert d["gedruckt"] is True
    data = dev.read_bytes()
    assert b"2x Gl\x81hwein" in data and b"Karte: Rot 1" in data  # CP437-Umlaut
    assert b"Tasse" not in data, "Pfandrückgabe gehört nicht auf den Bon"
    groesse = len(data)
    s, d = api.bestellen([(tasse, 1)])  # reine Rückgabe -> kein Druck
    assert d["gedruckt"] is None and len(dev.read_bytes()) == groesse


def test_drucker_fehler_bricht_nichts(api, tmp_path, monkeypatch):
    a = api.produkt()
    # 1. Kein Drucker
    s, d = api.bestellen([(a, 1)])
    assert s == 201 and d["gedruckt"] is False
    # 2. Gerät existiert, ist aber kaputt (Verzeichnis statt Gerät)
    kaputt = tmp_path / "kaputt"
    kaputt.mkdir()
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(kaputt))
    monkeypatch.setattr(printer, "_printer", None)
    s, d = api.bestellen([(a, 1)])
    assert s == 201 and d["gedruckt"] is False
    # 3. Drucker wieder da -> druckt wieder (Reconnect)
    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(dev))
    s, d = api.bestellen([(a, 1)])
    assert d["gedruckt"] is True and dev.stat().st_size > 0
    assert len(api.state()["bestellungen"]) == 3


# ---------------------------------------------------------------- Performance

def test_performance_grosser_abend(db):
    """5000 Bestellungen (ein sehr langes Wochenende): Zustand muss schnell bleiben."""
    import sqlite3
    a = database.create_produkt({"name": "A", "preis_cent": 750})["id"]
    b = database.create_produkt({"name": "B", "preis_cent": 350, "pfand_cent": 200})["id"]
    c = sqlite3.connect(db)
    for i in range(5000):
        cur = c.execute("INSERT INTO BESTELLUNGEN (zeitpunkt_annahme, zeitpunkt_abgeholt, status, preis_cent, pfand_cent) "
                        "VALUES (datetime('now'), datetime('now'), 'abgeholt', 1100, 200)")
        c.execute("INSERT INTO BESTELLUNGSINHALT VALUES (?, ?, 1, 750, 0)", (cur.lastrowid, a))
        c.execute("INSERT INTO BESTELLUNGSINHALT VALUES (?, ?, 1, 350, 200)", (cur.lastrowid, b))
    c.commit()
    t0 = time.perf_counter()
    msg = flaskserver._state_message()
    dauer = time.perf_counter() - t0
    print(f"\n  5000 Bestellungen: state in {dauer * 1000:.0f} ms, {len(msg) / 1024:.0f} KB")
    assert dauer < 1.0


def test_druckereinstellungen(api, client, tmp_path, monkeypatch):
    dev = tmp_path / "lp0"
    dev.write_bytes(b"")
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(dev))
    a = api.produkt("Flammkuchen", 750)

    # Ausgeschaltet: nichts wird gedruckt, Bestellung klappt trotzdem
    assert api.put("/api/einstellungen", {"drucker_aktiv": False})[0] == 200
    s, d = api.bestellen([(a, 1)])
    assert s == 201 and d["gedruckt"] is None and dev.stat().st_size == 0
    assert api.get("/api/drucker")[1]["aktiv"] is False

    # Eingeschaltet mit eigenem Kopf/Fuß, ohne Positionen, Gewinn jede 2. Bestellung
    assert api.put("/api/einstellungen", {
        "drucker_aktiv": True, "bon_kopf": "Hallo Markt!", "bon_fuss": "www.example.org",
        "bon_positionen": False, "bon_sprueche": False, "bon_gewinn_alle": 2,
        "bon_gewinn_text": "Gewonnen: Nr. {n}", "bon_breite_mm": 80,
    })[0] == 200
    s, d = api.bestellen([(a, 1)])  # Bestellung Nr. 2
    data = dev.read_bytes()
    assert d["gedruckt"] is True
    assert b"Hallo Markt!" in data and b"www.example.org" in data and b"Gewonnen: Nr. 2" in data
    assert b"Flammkuchen" not in data
    assert printer._printer.profile.profile_data["media"]["width"]["pixels"] == 576

    # Testdruck
    vorher = dev.stat().st_size
    assert api.post("/api/drucker/test")[1]["gedruckt"] is True and dev.stat().st_size > vorher


@pytest.mark.parametrize("body", [
    {"drucker_geraet": "/etc/passwd"},
    {"drucker_geraet": "/dev/usb/lp0/../../etc/x"},
    {"drucker_geraet": "/home/user/datei"},
    {"drucker_verbindung": "bluetooth"},
    {"drucker_host": "a b;rm -rf"},
    {"drucker_port": 0},
    {"bon_breite_mm": 57},
    {"bon_gewinn_alle": -1},
    {"bon_kopf": "x" * 301},
    {"titel": "   "},
    {"drucker_aktiv": "ja"},
])
def test_druckereinstellungen_ungueltig(api, body):
    assert api.put("/api/einstellungen", body)[0] == 400


def test_netzwerkdrucker_nicht_erreichbar(api, monkeypatch):
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", None)
    a = api.produkt()
    api.put("/api/einstellungen", {"drucker_verbindung": "netzwerk", "drucker_host": "127.0.0.1", "drucker_port": 9})
    t0 = time.time()
    s, d = api.bestellen([(a, 1)])
    assert s == 201 and d["gedruckt"] is False and time.time() - t0 < 5
    st = api.get("/api/drucker")[1]
    assert st["verbunden"] is False and st["ziel"] == "127.0.0.1:9" and st["fehler"]
