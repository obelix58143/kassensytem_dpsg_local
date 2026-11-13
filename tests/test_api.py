"""REST-API: Validierung, Bestellungen, Status-Ablauf, Pfand, Karten, Einstellungen, Export, Reset."""

import glob
import time

import pytest

import database


# ---------------------------------------------------------------- Produkte

@pytest.mark.parametrize("body,fehler", [
    ({"preis_cent": -1}, "Preis"),
    ({"preis_cent": 7.5}, "Preis"),
    ({"preis_cent": "750"}, "Preis"),
    ({"preis_cent": True}, "Preis"),
    ({"pfand_cent": 10**9}, "Pfand"),
    ({"name": 123}, "Name"),
    ({"name": "x" * 201}, "lang"),
    ({"typ": "gratis"}, "Produkttyp"),
    ({"typ": "pfand", "preis_cent": 100}, "keinen Preis"),
])
def test_produkt_validierung(api, body, fehler):
    s, d = api.post("/api/produkte", body)
    assert s == 400 and fehler in d["error"]


def test_produkt_crud(api):
    NAME = 'Glühwein „heiß" – <b>groß</b> 🍷 50% %{y}'
    pid = api.produkt(NAME, 350, 200)
    p = next(x for x in api.state()["produkte"] if x["id"] == pid)
    assert p["name"] == NAME and p["typ"] == "normal"

    assert api.put(f"/api/produkte/{pid}", {"name": "  "})[0] == 400
    assert api.put(f"/api/produkte/{pid}", {})[0] == 400
    assert api.put("/api/produkte/9999", {"name": "x"})[0] == 404
    s, d = api.put(f"/api/produkte/{pid}", {"preis_cent": 400, "aktiv": False, "sortierung": 5})
    assert s == 200 and d["preis_cent"] == 400 and d["aktiv"] is False

    # unverkauft -> wirklich gelöscht
    assert api.delete(f"/api/produkte/{pid}")[1]["ergebnis"] == "geloescht"
    assert api.delete(f"/api/produkte/{pid}")[0] == 404


def test_produkt_mit_verkauf_wird_nur_deaktiviert(api):
    pid = api.produkt()
    api.bestellen([(pid, 1)])
    assert api.delete(f"/api/produkte/{pid}")[1]["ergebnis"] == "deaktiviert"
    p = api.state()["produkte"][0]
    assert p["aktiv"] is False
    # deaktiviertes Produkt kann nicht mehr bestellt werden
    s, d = api.bestellen([(pid, 1)])
    assert s == 409


def test_pfandprodukt_preis_nicht_aenderbar(api):
    rid = api.produkt("Tasse zurück", 0, 200, "pfand")
    assert api.put(f"/api/produkte/{rid}", {"preis_cent": 100})[0] == 400
    assert api.put(f"/api/produkte/{rid}", {"pfand_cent": 250})[0] == 200


# ---------------------------------------------------------------- Bestellungen

@pytest.mark.parametrize("pos", [
    [], None, "x", [{"id": 1}], [{"id": 1, "anzahl": 0}], [{"id": 1, "anzahl": -2}],
    [{"id": 1, "anzahl": 1000}], [{"id": 1, "anzahl": True}], [{"id": 1, "anzahl": "2"}],
    [{"id": "1", "anzahl": 1}], [{"id": 1.0, "anzahl": 1}],
])
def test_bestellung_ungueltig(api, pos):
    api.produkt()
    s, d = api.post("/api/bestellungen", {"produkte": pos})
    assert s == 400, d
    assert api.state()["bestellungen"] == []


def test_bestellung_body_kaputt(api):
    assert api.post("/api/bestellungen", raw="{kein json")[0] == 400
    assert api.post("/api/bestellungen", raw="[1,2]")[0] == 400
    assert api.post("/api/bestellungen", raw="null")[0] == 400
    assert api.post("/api/bestellungen", raw='{"produkte":[]}', headers={"Content-Type": "text/plain"})[0] == 400


def test_preis_wird_serverseitig_berechnet(api):
    a, b = api.produkt("A", 750), api.produkt("B", 330, 200)
    s, d = api.bestellen([(a, 2), (b, 1), (a, 1)], preis_cent=1, pfand_cent=0)  # Client-Preis ignoriert
    assert s == 201 and d["preis_cent"] == 3 * 750 + 330 and d["pfand_cent"] == 200
    best = api.state()["bestellungen"][0]
    assert {p["id"]: p["anzahl"] for p in best["produkte"]} == {a: 3, b: 1}  # Duplikate zusammengefasst

    # Preisänderung danach verändert alte Bestellung nicht
    api.put(f"/api/produkte/{a}", {"preis_cent": 900})
    best = api.state()["bestellungen"][0]
    assert best["preis_cent"] == 2580
    assert next(p for p in best["produkte"] if p["id"] == a)["einzelpreis_cent"] == 750


def test_eigenbedarf(api):
    a = api.produkt("A", 750, 200)
    s, d = api.bestellen([(a, 2)], eigenbedarf=True)
    assert d["preis_cent"] == 0 and d["pfand_cent"] == 0


def test_unbekanntes_produkt_und_karte(api):
    a = api.produkt()
    assert api.bestellen([(999, 1)])[0] == 409
    assert api.bestellen([(a, 1)], karte=42)[0] == 404
    assert api.bestellen([(a, 1)], karte="1")[0] == 400


def test_idempotenz(api):
    a = api.produkt()
    s1, d1 = api.bestellen([(a, 1)], client_ref="abcdef123456")
    s2, d2 = api.bestellen([(a, 5)], client_ref="abcdef123456")  # Wiederholung (z.B. nach Timeout)
    assert s1 == 201 and s2 == 200 and d1["id"] == d2["id"] and d2["wiederholt"] is True
    assert d2["gedruckt"] is None
    assert len(api.state()["bestellungen"]) == 1
    assert api.bestellen([(a, 1)], client_ref="kurz")[0] == 400
    assert api.bestellen([(a, 1)], client_ref=12345678)[0] == 400


# ---------------------------------------------------------------- Status & Karten

def test_status_ablauf_mit_bereit(api):
    a, k = api.produkt(), api.karte()
    bid = api.bestellen([(a, 1)], karte=k)[1]["id"]
    assert api.put(f"/api/bestellungen/{bid}/status", {"status": "fertig"})[0] == 400
    assert api.put("/api/bestellungen/999/status", {"status": "bereit"})[0] == 404

    api.put(f"/api/bestellungen/{bid}/status", {"status": "bereit"})
    b = api.state()["bestellungen"][0]
    assert b["status"] == "bereit" and b["zeitpunkt_bereit"] and b["zeitpunkt_abgeholt"] is None
    assert api.state()["karten"][0]["inUse"] is True  # bereit = Karte noch beim Kunden
    assert api.bestellen([(a, 1)], karte=k)[0] == 409

    erst_bereit = b["zeitpunkt_bereit"]
    time.sleep(1.1)
    api.put(f"/api/bestellungen/{bid}/status", {"status": "abgeholt"})
    api.put(f"/api/bestellungen/{bid}/status", {"status": "bereit"})  # rückgängig
    b = api.state()["bestellungen"][0]
    assert b["zeitpunkt_bereit"] == erst_bereit, "Bereit-Zeitpunkt darf beim Rückgängig nicht springen"
    assert b["zeitpunkt_abgeholt"] is None

    api.put(f"/api/bestellungen/{bid}/status", {"status": "bestellt"})
    b = api.state()["bestellungen"][0]
    assert b["zeitpunkt_bereit"] is None and b["status"] == "bestellt"


def test_rueckgaengig_wenn_karte_neu_vergeben(api):
    a, k = api.produkt(), api.karte()
    b1 = api.bestellen([(a, 1)], karte=k)[1]["id"]
    api.put(f"/api/bestellungen/{b1}/status", {"status": "abgeholt"})
    api.bestellen([(a, 1)], karte=k)  # Karte neu vergeben
    s, d = api.put(f"/api/bestellungen/{b1}/status", {"status": "bestellt"})
    assert s == 409 and "Karte" in d["error"]


def test_karten(api):
    a, k = api.produkt(), api.karte()
    assert api.put(f"/api/karten/{k}", {"beschreibung": ""})[0] == 400
    assert api.put("/api/karten/99", {"beschreibung": "x"})[0] == 404
    api.bestellen([(a, 1)], karte=k)
    assert api.delete(f"/api/karten/{k}")[0] == 409
    bid = api.state()["bestellungen"][0]["id"]
    api.put(f"/api/bestellungen/{bid}/status", {"status": "abgeholt"})
    assert api.delete(f"/api/karten/{k}")[0] == 200
    assert api.state()["bestellungen"][0]["karte"] is None  # ON DELETE SET NULL


def test_storno(api):
    a = api.produkt()
    bid = api.bestellen([(a, 2)])[1]["id"]
    assert api.delete(f"/api/bestellungen/{bid}")[0] == 200
    assert api.delete(f"/api/bestellungen/{bid}")[0] == 404
    import sqlite3
    c = sqlite3.connect(database.DB_PATH)
    assert c.execute("SELECT count(*) FROM BESTELLUNGSINHALT").fetchone()[0] == 0  # Kaskade


# ---------------------------------------------------------------- Pfandrückgabe

def test_nur_pfandrueckgabe(api):
    k = api.karte()
    tasse = api.produkt("Tasse zurück", 0, 200, "pfand")
    s, d = api.bestellen([(tasse, 3)], karte=k)
    assert s == 201 and d["nur_pfand"] is True and d["pfand_cent"] == -600 and d["preis_cent"] == 0
    assert d["gedruckt"] is None  # kein Bon
    b = api.state()["bestellungen"][0]
    assert b["status"] == "abgeholt" and b["karte"] is None and b["nur_pfand"]
    assert api.state()["karten"][0]["inUse"] is False
    assert api.put(f"/api/bestellungen/{b['id']}/status", {"status": "bestellt"})[0] == 409
    assert api.post(f"/api/bestellungen/{b['id']}/bon")[0] == 409


def test_gemischt_neu_und_rueckgabe(api):
    gw = api.produkt("Glühwein", 350, 200)
    tasse = api.produkt("Tasse zurück", 0, 200, "pfand")
    s, d = api.bestellen([(gw, 1), (tasse, 1)])
    assert d["preis_cent"] == 350 and d["pfand_cent"] == 0 and d["nur_pfand"] is False
    b = api.state()["bestellungen"][0]
    assert b["status"] == "bestellt"
    assert {p["id"]: p["einzelpfand_cent"] for p in b["produkte"]} == {gw: 200, tasse: -200}
    # mehr zurück als neu -> Auszahlung
    s, d = api.bestellen([(gw, 1), (tasse, 3)])
    assert d["preis_cent"] + d["pfand_cent"] == 350 + 200 - 600


def test_bon_ohne_pfandzeilen(api):
    gw = api.produkt("Glühwein", 350, 200)
    tasse = api.produkt("Tasse zurück", 0, 200, "pfand")
    bid = api.bestellen([(gw, 1), (tasse, 1)])[1]["id"]
    assert [p["name"] for p in database.get_bestellung(bid)["produkte"]] == ["Glühwein"]


# ---------------------------------------------------------------- Einstellungen, Export, Reset

def test_einstellungen(api):
    assert api.state()["einstellungen"] == {**database.EINSTELLUNGEN_STANDARD, "bon_logo_vorhanden": False}
    assert api.put("/api/einstellungen", {"bereit_aktiv": True})[0] == 200
    assert api.state()["einstellungen"]["bereit_aktiv"] is True
    assert api.put("/api/einstellungen", {"bereit_aktiv": "ja"})[0] == 400
    assert api.put("/api/einstellungen", {"gibtsnicht": 1})[0] == 400
    assert api.put("/api/einstellungen", {})[0] == 400


def test_export_csv(api, client):
    a = api.produkt("=HYPERLINK(\"http://böse\")", 750)
    api.produkt("Normal; mit Semikolon", 100)
    tasse = api.produkt("Tasse zurück", 0, 200, "pfand")
    api.bestellen([(a, 2), (tasse, 1)])
    r = client.get("/api/export.csv")
    text = r.data.decode("utf-8")
    assert r.status_code == 200 and text.startswith("﻿")
    assert "'=HYPERLINK" in text, "Formel muss entschärft sein"
    assert ";pfand;1;0,00;-2,00;15,00;-2,00" in text


def test_reset(api, db):
    a = api.produkt()
    api.bestellen([(a, 1)])
    api.put("/api/einstellungen", {"bereit_aktiv": True})
    assert api.post("/api/reset", {})[0] == 400
    assert api.post("/api/reset", {"bestaetigung": "reset"})[0] == 400
    s, d = api.post("/api/reset", {"bestaetigung": "RESET"})
    assert s == 200 and d["backup"]
    assert glob.glob(db + ".reset-*.bak")
    st = api.state()
    assert st["produkte"] == [] and st["bestellungen"] == []
    assert st["einstellungen"]["bereit_aktiv"] is True, "Einstellungen überleben den Reset"
    assert api.produkt() == 1, "IDs starten nach Reset wieder bei 1"


# ---------------------------------------------------------------- Routing

def test_routing(api, client, tmp_path, monkeypatch):
    assert api.get("/api/gibtsnicht")[0] == 404
    assert client.delete("/api/state").status_code in (404, 405)
    import flaskserver
    monkeypatch.setattr(flaskserver, "DIST_DIR", str(tmp_path / "fehlt"))
    assert client.get("/").status_code == 503
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "a-123.js").write_text("x")
    monkeypatch.setattr(flaskserver, "DIST_DIR", str(dist))
    r = client.get("/irgendwas/tief")  # SPA-Fallback
    assert r.status_code == 200 and b"app" in r.data and r.headers["Cache-Control"] == "no-cache"
    r = client.get("/assets/a-123.js")
    assert "immutable" in r.headers["Cache-Control"]
    assert client.get("/../database.py").status_code in (200, 404)
    assert b"sqlite" not in client.get("/../database.py").data, "Kein Zugriff außerhalb von dist"
