"""Gemeinsame Test-Fixtures: jede Testfunktion bekommt eine eigene, leere Datenbank."""

import json
import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import database  # noqa: E402
import flaskserver  # noqa: E402
import printer  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "data.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    # Drucker standardmäßig "nicht angeschlossen"
    monkeypatch.setattr(printer, "PRINTER_DEV_FILE", str(tmp_path / "kein_drucker"))
    monkeypatch.setattr(printer, "_printer", None)
    database.setup_db()
    return path


@pytest.fixture
def client(db):
    flaskserver.app.config["TESTING"] = True
    with flaskserver.app.test_client() as c:
        yield c


class Api:
    """Kleine Hilfe: c.post('/api/x', {...}) -> (status, json)"""

    def __init__(self, c):
        self.c = c

    def _do(self, method, path, body=None, raw=None, headers=None):
        kw = {}
        if raw is not None:
            kw["data"] = raw
            kw["headers"] = headers or {"Content-Type": "application/json"}
        elif body is not None:
            kw["json"] = body
        r = getattr(self.c, method)(path, **kw)
        try:
            data = r.get_json()
        except Exception:
            data = None
        return r.status_code, data

    def get(self, p):
        return self._do("get", p)

    def post(self, p, b=None, **kw):
        return self._do("post", p, b, **kw)

    def put(self, p, b=None, **kw):
        return self._do("put", p, b, **kw)

    def delete(self, p):
        return self._do("delete", p)

    def state(self):
        return self.get("/api/state")[1]

    # Abkürzungen
    def produkt(self, name="Flammkuchen", preis=750, pfand=0, typ="normal"):
        s, d = self.post("/api/produkte", {"name": name, "preis_cent": preis, "pfand_cent": pfand, "typ": typ})
        assert s == 201, d
        return d["id"]

    def karte(self, name="Rot 1"):
        s, d = self.post("/api/karten", {"beschreibung": name})
        assert s == 201, d
        return d["id"]

    def bestellen(self, positionen, **extra):
        body = {"produkte": [{"id": i, "anzahl": n} for i, n in positionen], **extra}
        return self.post("/api/bestellungen", body)


@pytest.fixture
def api(client):
    return Api(client)


@pytest.fixture
def live_server(db, monkeypatch):
    """Echter Server in einem Thread (für WebSocket- und Nebenläufigkeitstests)."""
    from werkzeug.serving import make_server

    monkeypatch.setattr(flaskserver, "HEARTBEAT_SECONDS", 1)
    srv = make_server("127.0.0.1", 0, flaskserver.app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"127.0.0.1:{srv.server_port}"
    srv.shutdown()


def http(base, method, path, body=None, timeout=10):
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"http://{base}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


@pytest.fixture(autouse=True)
def backup_ordner(tmp_path, monkeypatch):
    """Sicherungen in jedem Test in einen eigenen Ordner"""
    monkeypatch.setattr(database, "BACKUP_DIR", str(tmp_path / "backups"))
