"""Kassierer:in und Ausgabe-Person je Bestellung, Produkte auf dem Kundendisplay ausblenden,
Adressen für die Startseite."""

import pytest


def test_kassierer_wird_gespeichert(api):
    pid = api.produkt()
    s, d = api.bestellen([(pid, 1)], kassierer="  Anna ")
    assert s == 201
    b = api.state()["bestellungen"][0]
    assert b["kassierer"] == "Anna" and b["ausgabe"] is None


@pytest.mark.parametrize("name", [None, "", "   "])
def test_kassierer_optional(api, name):
    pid = api.produkt()
    assert api.bestellen([(pid, 1)], kassierer=name)[0] == 201
    assert api.state()["bestellungen"][0]["kassierer"] is None


@pytest.mark.parametrize("name", [5, ["x"], "x" * 41])
def test_kassierer_ungueltig(api, name):
    pid = api.produkt()
    assert api.bestellen([(pid, 1)], kassierer=name)[0] == 400
    assert api.state()["bestellungen"] == []


def test_pfandrueckgabe_merkt_kassierer(api):
    rid = api.produkt("Pfand zurück", preis=0, pfand=200, typ="pfand")
    assert api.bestellen([(rid, 1)], kassierer="Ben")[0] == 201
    assert api.state()["bestellungen"][0]["kassierer"] == "Ben"


def _status(api, bid, status, person=None):
    body = {"status": status}
    if person is not None:
        body["person"] = person
    s, d = api.put(f"/api/bestellungen/{bid}/status", body)
    assert s == 200, d
    return api.state()["bestellungen"][0]


def test_ausgabe_ohne_bereit_schritt(api):
    pid = api.produkt()
    bid = api.bestellen([(pid, 1)])[1]["id"]
    assert _status(api, bid, "abgeholt", "Clara")["ausgabe"] == "Clara"


def test_ausgabe_zaehlt_wer_fertig_meldet(api):
    """Mit Bereit-Schritt: wer „Fertig" drückt (Bäcker:in), nicht wer später „Abgeholt" drückt."""
    pid = api.produkt()
    bid = api.bestellen([(pid, 1)])[1]["id"]
    assert _status(api, bid, "bereit", "Dora")["ausgabe"] == "Dora"
    assert _status(api, bid, "abgeholt", "Emil")["ausgabe"] == "Dora"
    assert _status(api, bid, "bereit")["ausgabe"] == "Dora"  # Rückgängig von abgeholt


def test_zurueck_in_zubereitung_loescht_ausgabe(api):
    pid = api.produkt()
    bid = api.bestellen([(pid, 1)])[1]["id"]
    _status(api, bid, "bereit", "Dora")
    assert _status(api, bid, "bestellt")["ausgabe"] is None
    assert _status(api, bid, "bereit", "Emil")["ausgabe"] == "Emil"


def test_ausgabe_person_ungueltig(api):
    pid = api.produkt()
    bid = api.bestellen([(pid, 1)])[1]["id"]
    s, _ = api.put(f"/api/bestellungen/{bid}/status", {"status": "abgeholt", "person": 3})
    assert s == 400
    assert api.state()["bestellungen"][0]["status"] == "bestellt"


def test_produkt_auf_display_ausblenden(api):
    pid = api.produkt()
    assert api.state()["produkte"][0]["auf_display"] is True
    s, d = api.put(f"/api/produkte/{pid}", {"auf_display": False})
    assert s == 200 and d["auf_display"] is False
    p = api.state()["produkte"][0]
    assert p["auf_display"] is False and p["aktiv"] is True  # an der Kasse weiter verkaufbar
    s, d = api.post("/api/produkte", {"name": "Geheim", "auf_display": False})
    assert s == 201 and d["auf_display"] is False


def test_csv_enthaelt_personen(api, client):
    pid = api.produkt()
    bid = api.bestellen([(pid, 1)], kassierer="Anna")[1]["id"]
    api.put(f"/api/bestellungen/{bid}/status", {"status": "abgeholt", "person": "Clara"})
    text = client.get("/api/export.csv").get_data(as_text=True)
    kopf, zeile = text.strip().splitlines()[:2]
    assert kopf.endswith("kassierer;ausgabe") and zeile.endswith("Anna;Clara")


def test_csv_person_injection(api, client):
    pid = api.produkt()
    api.bestellen([(pid, 1)], kassierer="=HYPERLINK(1)")
    assert "'=HYPERLINK(1)" in client.get("/api/export.csv").get_data(as_text=True)


def test_system_liefert_adressen(api):
    s, d = api.get("/api/system")
    assert s == 200
    assert isinstance(d["adressen"], list) and all(isinstance(x, str) for x in d["adressen"])
    assert "127.0.0.1" not in d["adressen"]
    assert "akku" in d and "hostname" in d
