"""HTTP-API + WebSocket + Auslieferung des gebauten Frontends.

Änderungen laufen über REST (POST/PUT/DELETE mit JSON-Body).
Nach jeder Änderung wird der komplette Zustand per WebSocket (/ws) an alle
verbundenen Geräte gepusht – kein Polling mehr.
"""

import csv
import io
import json
import os
import threading

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_sock import Sock
from simple_websocket import ConnectionClosed

import database
import printer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.environ.get("KASSE_DIST", os.path.join(BASE_DIR, "frontend", "dist"))

HEARTBEAT_SECONDS = 15

app = Flask(__name__, static_folder=None)
app.json.ensure_ascii = False
sock = Sock(app)
# Der Drucker liest seine Einstellungen bei jedem Druck frisch aus der Datenbank
printer.configure(database.get_einstellungen, database.get_logo)
app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024  # Logo-Upload


# --------------------------------------------------------------------------
# WebSocket-Hub
# --------------------------------------------------------------------------

class _Client:
    """Pro Verbindung wird nur der jeweils neueste Zustand vorgehalten:
    ein langsamer Client bekommt keine veralteten Zwischenstände."""

    def __init__(self):
        self.pending = None
        self.event = threading.Event()


_clients = set()
_clients_lock = threading.Lock()


def _state_message():
    return json.dumps({"type": "state", "data": database.get_state()}, ensure_ascii=False)


def broadcast():
    message = _state_message()
    with _clients_lock:
        for c in _clients:
            c.pending = message
            c.event.set()


@sock.route("/ws")
def ws_handler(ws):
    client = _Client()
    client.pending = _state_message()
    client.event.set()
    with _clients_lock:
        _clients.add(client)
    try:
        while ws.connected:
            if client.event.wait(HEARTBEAT_SECONDS):
                client.event.clear()
                msg, client.pending = client.pending, None
                if msg is not None:
                    ws.send(msg)
            else:
                ws.send('{"type":"ping"}')
    except ConnectionClosed:
        pass
    finally:
        with _clients_lock:
            _clients.discard(client)


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

@app.errorhandler(database.DBError)
def _db_error(e):
    return jsonify({"error": e.message}), e.status


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise database.DBError("JSON-Objekt im Body erwartet")
    return data


def _changed(payload=None, status=200):
    broadcast()
    return jsonify(payload or {"ok": True}), status


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@app.get("/api/state")
def api_state():
    return jsonify(database.get_state())


@app.get("/api/drucker")
def api_drucker():
    return jsonify(printer.status())


@app.post("/api/drucker/test")
def api_drucker_test():
    return jsonify({"gedruckt": printer.print_test()})


@app.post("/api/produkte")
def api_produkt_neu():
    return _changed(database.create_produkt(request.get_json(silent=True) or {}), 201)


@app.put("/api/produkte/<int:id>")
def api_produkt_update(id):
    return _changed(database.update_produkt(id, _body()))


@app.delete("/api/produkte/<int:id>")
def api_produkt_delete(id):
    return _changed({"ok": True, "ergebnis": database.delete_produkt(id)})


@app.post("/api/karten")
def api_karte_neu():
    return _changed(database.create_karte(request.get_json(silent=True) or {}), 201)


@app.put("/api/karten/<int:id>")
def api_karte_update(id):
    database.update_karte(id, _body())
    return _changed()


@app.delete("/api/karten/<int:id>")
def api_karte_delete(id):
    database.delete_karte(id)
    return _changed()


@app.post("/api/bestellungen")
def api_bestellung_neu():
    result = database.add_bestellung(_body())
    if result["wiederholt"]:
        result["gedruckt"] = None  # Bon wurde beim ersten Versuch schon gedruckt
        return jsonify(result), 200
    # Erst allen Geräten Bescheid geben, dann drucken (Drucken dauert ~1 s)
    broadcast()
    # Reine Pfandrückgabe: nichts abzuholen, also kein Bon
    result["gedruckt"] = None if result["nur_pfand"] else printer.print_receipt(database.get_bestellung(result["id"]))
    return jsonify(result), 201


@app.put("/api/bestellungen/<int:id>/status")
def api_bestellung_status(id):
    database.set_status(id, _body().get("status"))
    return _changed()


@app.delete("/api/bestellungen/<int:id>")
def api_bestellung_storno(id):
    database.storno(id)
    return _changed()


@app.post("/api/bestellungen/<int:id>/bon")
def api_bon_nachdruck(id):
    if database.get_bestellung(id)["nur_pfand"]:
        raise database.DBError("Reine Pfandrückgabe – kein Bon", 409)
    return jsonify({"gedruckt": printer.print_receipt(database.get_bestellung(id))})


@app.post("/api/bestellungen/<int:id>/nummer")
def api_nummer_drucken(id):
    database.get_bestellung(id)  # 404 wenn unbekannt
    return jsonify({"gedruckt": printer.print_number(id)})


@app.post("/api/drucker/letzte-nummer")
def api_letzte_nummer():
    last = database.get_last_bestellung_id()
    if last is None:
        raise database.DBError("Noch keine Bestellung vorhanden", 404)
    return jsonify({"id": last, "gedruckt": printer.print_number(last)})


@app.put("/api/einstellungen")
def api_einstellungen():
    return _changed(database.set_einstellungen(_body()))


@app.put("/api/drucker/logo")
def api_logo_hochladen():
    info = database.set_logo(request.get_data())
    return _changed({"ok": True, **info})


@app.get("/api/drucker/logo.png")
def api_logo():
    roh = database.get_logo()
    if roh is None:
        return jsonify({"error": "Kein Logo hochgeladen"}), 404
    return Response(roh, mimetype="image/png", headers={"Cache-Control": "no-cache"})


@app.delete("/api/drucker/logo")
def api_logo_loeschen():
    database.delete_logo()
    return _changed()


@app.get("/api/sicherungen")
def api_sicherungen():
    return jsonify({"letzte": database.letzte_sicherung, "ordner": database.BACKUP_DIR,
                    "dateien": database.sicherungen_auflisten()[:20]})


@app.post("/api/sicherungen")
def api_sicherung_jetzt():
    ziel = database.sicherung_erstellen("manuell")
    if not ziel:
        raise database.DBError(f"Sicherung fehlgeschlagen: {database.letzte_sicherung['fehler']}", 500)
    return jsonify({"ok": True, "datei": os.path.basename(ziel)})


@app.get("/api/sicherungen/download")
def api_sicherung_download():
    """Aktuellen Stand als Datei herunterladen (z.B. aufs Handy als zusätzliche Kopie)"""
    ziel = database.sicherung_erstellen("download")
    if not ziel:
        raise database.DBError("Sicherung fehlgeschlagen", 500)
    return send_from_directory(os.path.dirname(ziel), os.path.basename(ziel), as_attachment=True)


@app.post("/api/reset")
def api_reset():
    if _body().get("bestaetigung") != "RESET":
        raise database.DBError('Bitte mit "RESET" bestätigen')
    backup = database.hard_reset()
    return _changed({"ok": True, "backup": os.path.basename(backup) if backup else None})


def _csv_text(v):
    """Schutz vor CSV-Injection: Excel würde "=…", "+…", "-…", "@…" als Formel ausführen."""
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@app.get("/api/export.csv")
def api_export():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    eur = lambda c: f"{c / 100:.2f}".replace(".", ",")
    w.writerow(["bestellung", "angenommen", "abgeholt", "status", "karte", "eigenbedarf", "produkt", "typ",
                "anzahl", "einzelpreis_eur", "einzelpfand_eur", "bestellung_preis_eur", "bestellung_pfand_eur"])
    for r in database.export_rows():
        w.writerow([
            r["id"], r["zeitpunkt_annahme"], r["zeitpunkt_abgeholt"] or "", r["status"], _csv_text(r["karte"] or ""),
            "ja" if r["eigenbedarf"] else "nein", _csv_text(r["produkt"]), r["typ"], r["anzahl"],
            eur(r["einzelpreis_cent"]), eur(r["einzelpfand_cent"]), eur(r["preis_cent"]), eur(r["pfand_cent"]),
        ])
    # BOM, damit Excel die Umlaute richtig erkennt
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=bestellungen.csv"})


@app.route("/api/<path:_>", methods=["GET", "POST", "PUT", "DELETE"])
def api_not_found(_):
    return jsonify({"error": "Unbekannter API-Pfad"}), 404


# --------------------------------------------------------------------------
# Frontend (gebaut mit `npm run build` nach frontend/dist)
# --------------------------------------------------------------------------

@app.get("/")
@app.get("/<path:path>")
def frontend(path="index.html"):
    if not os.path.isdir(DIST_DIR):
        return Response("Frontend nicht gebaut: cd frontend && npm install && npm run build",
                        status=503, mimetype="text/plain")
    full = os.path.join(DIST_DIR, path)
    if path != "index.html" and os.path.isfile(full):
        resp = send_from_directory(DIST_DIR, path)
        if path.startswith("assets/"):  # Dateinamen enthalten Hash
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp
    resp = send_from_directory(DIST_DIR, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp
