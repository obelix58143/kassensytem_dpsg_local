"""Bondrucker (ESC/POS) – per USB-Gerätedatei oder Netzwerk (RAW, Port 9100).

Alles wird über die Einstellungen in der Weboberfläche gesteuert (siehe
database.EINSTELLUNGEN_STANDARD, Schlüssel drucker_* und bon_*).

Alle Funktionen sind fehlertolerant: Ist der Drucker aus, abgezogen oder klemmt,
gibt es None (ausgeschaltet) bzw. False (Fehler) zurück statt einer Exception –
die Bestellung ist dann trotzdem gespeichert und kann nachgedruckt werden.
"""

import json
import os
import random
import socket
import sys
import threading

try:
    from escpos.printer import File, Network
except ImportError:  # Entwicklung ohne Drucker-Bibliothek
    File = Network = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(BASE_DIR, "printer_files")
LOGO = os.path.join(FILES_DIR, "logo.png")
# Optional: Gerätedatei fest vorgeben (überschreibt die Einstellung, z.B. für Tests)
PRINTER_DEV_FILE = os.environ.get("PRINTER_DEV")

_lock = threading.Lock()
_printer = None
_printer_key = None
_sprueche = []
_letzter_fehler = None


def _standard_config():
    import database
    return dict(database.EINSTELLUNGEN_STANDARD)


_get_config = _standard_config


def configure(get_config):
    """get_config() -> dict mit den aktuellen Einstellungen"""
    global _get_config
    _get_config = get_config


def _load_sprueche():
    global _sprueche
    try:
        with open(os.path.join(FILES_DIR, "sprueche.json"), encoding="utf-8") as f:
            _sprueche = [s for s in json.load(f) if isinstance(s, str) and s.strip()]
    except (OSError, ValueError):
        _sprueche = []
    random.shuffle(_sprueche)


_load_sprueche()


def _ziel(cfg):
    if cfg["drucker_verbindung"] == "netzwerk":
        return ("netzwerk", cfg["drucker_host"], cfg["drucker_port"])
    return ("usb", PRINTER_DEV_FILE or cfg["drucker_geraet"], None)


def beschreibung(cfg=None):
    cfg = cfg or _get_config()
    art, adr, port = _ziel(cfg)
    return f"{adr}:{port}" if art == "netzwerk" else adr


def _patch_profile(printer, breite_mm):
    # Druckbreite: 58-mm-Papier = 48 mm bedruckbar, 80 mm = 72 mm (bei 203 dpi = 8 Punkte/mm)
    mm = 72 if breite_mm == 80 else 48
    printer.profile.profile_data["media"] = {"dpi": 203, "width": {"mm": mm, "pixels": 8 * mm}}


def _schliessen():
    global _printer, _printer_key
    try:
        if _printer is not None:
            _printer.close()
    except Exception:
        pass
    _printer = None
    _printer_key = None


def _get_printer(cfg):
    global _printer, _printer_key
    if File is None:
        raise RuntimeError("python-escpos ist nicht installiert")
    art, adr, port = _ziel(cfg)
    key = (art, adr, port, cfg["bon_breite_mm"])
    if _printer is not None and key != _printer_key:
        _schliessen()  # Einstellungen geändert
    if art == "usb" and not os.path.exists(adr):
        _schliessen()
        raise RuntimeError(f"Drucker {adr} nicht gefunden")
    if art == "netzwerk" and not adr:
        raise RuntimeError("Keine Drucker-Adresse eingestellt")
    if _printer is None:
        _printer = Network(adr, port=port, timeout=3) if art == "netzwerk" else File(adr)
        _patch_profile(_printer, cfg["bon_breite_mm"])
        _printer_key = key
    return _printer


def status():
    """{aktiv, verbunden, ziel, fehler} – für die Einstellungsseite"""
    cfg = _get_config()
    art, adr, port = _ziel(cfg)
    verbunden = False
    if cfg["drucker_aktiv"]:
        if art == "usb":
            verbunden = os.path.exists(adr)
        elif adr:
            try:
                socket.create_connection((adr, port), timeout=2).close()
                verbunden = True
            except OSError:
                verbunden = False
    return {"aktiv": cfg["drucker_aktiv"], "verbunden": verbunden, "ziel": beschreibung(cfg),
            "fehler": _letzter_fehler, "bibliothek": File is not None}


def is_connected():
    return status()["verbunden"]


def _run(job):
    """None = Drucker ausgeschaltet, True = gedruckt, False = Fehler"""
    global _letzter_fehler
    cfg = _get_config()
    if not cfg["drucker_aktiv"]:
        return None
    with _lock:
        try:
            p = _get_printer(cfg)
            job(p, cfg)
            _letzter_fehler = None
            return True
        except Exception as e:  # noqa: BLE001 – Drucken darf nie die Kasse stören
            _letzter_fehler = str(e)
            print(f"[drucker] Fehler: {e}")
            _schliessen()  # beim nächsten Mal neu verbinden (z.B. nach Ab-/Anstecken)
            return False


def print_number(num):
    def job(p, cfg):
        p.set(align="center", double_height=True, double_width=True)
        p.text(f"\n\n{num}\n\n\n\n\n")
        p.set(normal_textsize=True)

    return _run(job)


def _bon(p, cfg, bestellung):
    bid = bestellung["id"]
    if cfg["bon_logo"] and os.path.exists(LOGO):
        p.image(LOGO, center=True)
    p.set(align="center", normal_textsize=True)
    if cfg["bon_kopf"]:
        p.text(f"\n{cfg['bon_kopf']}\n\n")
    p.set(align="center", double_height=True, double_width=True)
    p.text(f"{bid}\n")
    p.set(align="center", normal_textsize=True)
    if cfg["bon_karte"] and bestellung.get("karte"):
        p.text(f"Karte: {bestellung['karte']}\n")
    if cfg["bon_positionen"] and bestellung.get("produkte"):
        p.text("\n")
        for pos in bestellung["produkte"]:
            p.text(f"{pos['anzahl']}x {pos['name']}\n")
    if cfg["bon_sprueche"] and _sprueche:
        p.text(f"\n{_sprueche[bid % len(_sprueche)]}\n")
        if bid % len(_sprueche) == 0:
            random.shuffle(_sprueche)
    n = cfg["bon_gewinn_alle"]
    if n and bid and bid % n == 0:
        p.text("\n")
        p.set(align="center", double_height=True)
        p.text(cfg["bon_gewinn_text"].replace("{n}", str(bid)) + "\n")
        p.set(align="center", normal_textsize=True)
    if cfg["bon_fuss"]:
        p.text(f"\n{cfg['bon_fuss']}\n")
    p.text("\n\n\n")


def print_receipt(bestellung):
    """bestellung: dict mit id, karte (Name oder None), produkte [{name, anzahl}]"""
    return _run(lambda p, cfg: _bon(p, cfg, bestellung))


def print_test():
    beispiel = {"id": 42, "karte": "Beispiel", "produkte": [{"name": "Testprodukt", "anzahl": 2}]}
    return _run(lambda p, cfg: (p.set(align="center"), p.text("*** Testdruck ***\n"), _bon(p, cfg, beispiel)))


if __name__ == "__main__":
    # Testdruck der Sprüche: python printer.py [index ...]
    with open(os.path.join(FILES_DIR, "sprueche.json"), encoding="utf-8") as f:
        sprueche = json.load(f)
    numbers = [int(n) for n in sys.argv[1:]] or list(range(len(sprueche)))

    def job(p, cfg):
        for n in numbers:
            p.text(f"\n\n{sprueche[n]}\n\n")
        p.text("\n\n")

    print({True: "gedruckt", False: "Fehler", None: "Drucker ausgeschaltet"}[_run(job)])
