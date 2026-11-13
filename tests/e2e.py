"""Browser-Ende-zu-Ende-Test mit Playwright (mehrere Tabs = mehrere Geräte).

Startet einen eigenen Server mit leerer Datenbank auf Port 5077.
Aufruf:  python tests/e2e.py [--sim-alt] [--dist PFAD]
  --sim-alt  simuliert einen alten Browser (Android 7 WebView): ohne AbortController,
             ResizeObserver, randomUUID, Flex-gap und CSS-Grid
Voraussetzung: pip install playwright && playwright install chromium
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 5077
B = f"http://127.0.0.1:{PORT}"

SIM_INIT = """
delete window.AbortController; delete window.ResizeObserver;
try { Object.defineProperty(Crypto.prototype, 'randomUUID', {value: undefined}) } catch (e) {}
"""
SIM_POST = """() => {
  if (document.getElementById('sim')) return;
  document.documentElement.classList.add('no-flexgap');
  [].forEach.call(document.querySelectorAll('style'), s => {
    if (s.textContent.indexOf('@supports not (display: grid)') >= 0)
      s.textContent = s.textContent.split('@supports not (display: grid)').join('@supports (display: grid)');
  });
  const st = document.createElement('style'); st.id = 'sim';
  st.textContent = '*{gap:0 !important;row-gap:0 !important;column-gap:0 !important}';
  document.head.appendChild(st);
}"""

ergebnisse = []


def check(name, ok, info=""):
    ergebnisse.append((name, bool(ok), info))
    print(f"  {'✓' if ok else '✗'} {name}{'' if ok else '  -> ' + str(info)}")


def api(method, path, body=None):
    req = urllib.request.Request(B + "/api" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"null")


def state():
    return api("GET", "/state")


class Server:
    def __init__(self, db, dist):
        self.env = dict(os.environ, KASSE_DB=db, PORT=str(PORT), PRINTER_DEV="/nonexistent", KASSE_DIST=dist)
        self.p = None

    def start(self):
        try:  # Port muss frei sein – sonst würden wir mit einem fremden Server testen
            urllib.request.urlopen(B + "/api/state", timeout=1)
            raise RuntimeError(f"Port {PORT} ist schon belegt")
        except urllib.error.URLError:
            pass
        self.p = subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(B + "/api/state", timeout=1)
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Server startet nicht")

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.kill()
            self.p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim-alt", action="store_true")
    ap.add_argument("--dist", default=os.path.join(ROOT, "frontend", "dist"))
    ap.add_argument("--shots", default=None, help="Ordner für Screenshots")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp()
    server = Server(os.path.join(tmp, "e2e.db"), args.dist)
    server.start()
    try:
        lauf(args, server)
    finally:
        server.stop()
    ok = sum(1 for _, o, _ in ergebnisse if o)
    print(f"\n{ok}/{len(ergebnisse)} Prüfungen bestanden")
    sys.exit(0 if ok == len(ergebnisse) else 1)


def lauf(args, server):
    print(f"E2E {'(simulierter Alt-Browser)' if args.sim_alt else ''} gegen {B}")

    # Grunddaten
    fk = api("POST", "/produkte", {"name": "Flammkuchen", "preis_cent": 750})["id"]
    gw = api("POST", "/produkte", {"name": "Glühwein", "preis_cent": 350, "pfand_cent": 200})["id"]
    tasse = api("POST", "/produkte", {"typ": "pfand", "name": "Tasse zurück", "pfand_cent": 200})["id"]
    xss = api("POST", "/produkte", {"name": '<img src=x onerror="window.__xss=1"> 50% %{y}', "preis_cent": 100})["id"]
    rot = api("POST", "/karten", {"beschreibung": "Rot 1"})["id"]
    api("POST", "/produkte", {"name": "Ziegenkäse-Honig-Walnuss-Flammkuchenspezialität", "preis_cent": 950})
    erste = api("POST", "/bestellungen", {"produkte": [{"id": xss, "anzahl": 2}]})["id"]
    api("PUT", f"/bestellungen/{erste}/status", {"status": "abgeholt"})

    konsole = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1280, "height": 900})
        if args.sim_alt:
            ctx.add_init_script(SIM_INIT)

        def seite(pfad):
            pg = ctx.new_page()
            # Erwartete Netzwerkfehler (4xx-Tests, absichtlicher Server-Neustart) ignorieren
            erwartet = ("status of 4", "net::ERR_", "WebSocket connection to")
            pg.on("console", lambda m: m.type == "error" and not any(e in m.text for e in erwartet) and konsole.append(m.text))
            pg.on("pageerror", lambda e: konsole.append(str(e)))
            pg.on("dialog", lambda d: (konsole.append("DIALOG: " + d.message), d.dismiss()))
            pg.goto(B + "/#" + pfad)
            pg.wait_for_selector("main", timeout=15000)
            if args.sim_alt:
                pg.evaluate(SIM_POST)
            return pg

        def shot(pg, name):
            if args.shots:
                pg.screenshot(path=os.path.join(args.shots, f"e2e_{'alt_' if args.sim_alt else ''}{name}.png"))

        def toast(pg, *texte):
            """Wartet (max. 5 s) auf einen Toast, der einen der Texte enthält"""
            ende = time.time() + 5
            while time.time() < ende:
                alle = pg.locator(".toast-text").all_inner_texts()
                if any(t in a for a in alle for t in texte):
                    return True
                time.sleep(0.1)
            print("    vorhandene Toasts:", pg.locator(".toast-text").all_inner_texts())
            return False

        def tile(pg, name):
            return pg.locator(".tile", has_text=name).first

        def pitem(pg, name):
            """Produktzeile in den Einstellungen (Name steht im Eingabefeld, nicht als Text)"""
            i = pg.evaluate("n => [].findIndex.call(document.querySelectorAll('.pitem'), r => r.querySelector('input').value === n)", name)
            assert i >= 0, f"Produktzeile {name} nicht gefunden"
            return pg.locator(".pitem").nth(i)

        kasse = seite("/kasse")
        ausgabe = seite("/ausgabe")
        kasse.bring_to_front()

        print("Kasse & Live-Sync")
        tile(kasse, "Flammkuchen").click()
        tile(kasse, "Flammkuchen").click()
        tile(kasse, "Glühwein").click()
        summe = kasse.locator(".summen .total").inner_text()
        check("Summe 2×7,50 + 3,50 + 2,00 Pfand = 20,50", "20,50" in summe, summe)
        kasse.get_by_role("button", name="Passend").click()
        kasse.locator(".chip", has_text="Rot 1").click()
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        check("Toast nach Aufgeben", toast(kasse, "aufgegeben", "gespeichert"))
        ausgabe.wait_for_selector(".order", timeout=3000)
        check("Ausgabe-Tab zeigt Bestellung live", ausgabe.locator(".order").count() == 1)
        check("Karte jetzt belegt (nicht mehr wählbar)", kasse.locator(".chip", has_text="Rot 1").count() == 0)
        shot(kasse, "kasse")

        print("Doppelklick / Enter / Escape")
        n0 = len(state()["bestellungen"])
        tile(kasse, "Flammkuchen").click()
        kasse.locator("button", has_text="Bestellung aufgeben").dblclick()
        time.sleep(0.8)
        check("Doppelklick erzeugt genau 1 Bestellung", len(state()["bestellungen"]) == n0 + 1)
        tile(kasse, "Flammkuchen").click()
        kasse.keyboard.press("Escape")
        check("Escape leert den Warenkorb", kasse.locator(".positionen li").count() == 0)
        tile(kasse, "Flammkuchen").click()
        kasse.keyboard.press("Enter")
        time.sleep(0.8)
        check("Enter gibt auf (genau 1 neue)", len(state()["bestellungen"]) == n0 + 2)

        print("Pfandrückgabe")
        offen_vorher = ausgabe.locator(".order").count()
        tile(kasse, "Tasse zurück").click()
        tile(kasse, "Tasse zurück").click()
        total = kasse.locator(".summen .total").inner_text()
        check("Nur Rückgabe: 'Auszahlen 4,00 €'", "Auszahlen" in total and "4,00" in total, total)
        check("Keine Kartenwahl bei reiner Rückgabe", kasse.locator(".chip", has_text="Ohne").count() == 0)
        check("Kein 'Gegeben'-Block", kasse.locator(".geld").count() == 0)
        check("Button 'Pfand auszahlen'", "Pfand auszahlen" in kasse.locator(".korb .btn-primary.btn-lg").inner_text())
        shot(kasse, "pfand")
        kasse.locator(".korb .btn-primary.btn-lg").click()
        check("Toast 'Pfand ausgezahlt: 4,00 €'", toast(kasse, "Pfand ausgezahlt: 4,00"))
        time.sleep(0.5)
        check("Rückgabe erscheint nicht in der Ausgabe", ausgabe.locator(".order").count() == offen_vorher)
        check("…und nicht unter 'Zuletzt abgeholt'", "Tasse" not in ausgabe.locator(".abgeholt").inner_text())
        tile(kasse, "Glühwein").click()
        tile(kasse, "Tasse zurück").click()
        check("Glühwein + Tasse zurück = 3,50 €", "3,50" in kasse.locator(".summen .total").inner_text())
        kasse.keyboard.press("Escape")

        print("Abholbereit-Modus")
        settings = seite("/settings")
        settings.locator("label.switch", has_text="Abholbereit").click()
        ausgabe.wait_for_selector("text=In Zubereitung", timeout=3000)
        check("Ausgabe schaltet live auf 2 Abschnitte", ausgabe.locator("#h-bereit").count() == 1)
        front = seite("/front")
        erste = ausgabe.locator(".phase-zubereitung").first
        nr = erste.locator(".order-id").inner_text().strip("#")
        erste.locator("button", has_text="Fertig").click()
        front.wait_for_selector(".front-num.ready", timeout=3000)
        check("Display zeigt Nummer unter 'Bitte abholen'", nr in front.locator(".front-ready").inner_text())
        check("Ausgabe: Karte im Abschnitt Abholbereit", ausgabe.locator(".phase-bereit").count() == 1)
        shot(front, "display_bereit")
        shot(ausgabe, "ausgabe_bereit")
        ausgabe.locator(".phase-bereit button", has_text="Abgeholt").first.click()
        ausgabe.wait_for_selector(".toast button:has-text('Rückgängig')", timeout=3000)
        ausgabe.locator(".toast button", has_text="Rückgängig").last.click()
        time.sleep(0.6)
        b = next(x for x in state()["bestellungen"] if str(x["id"]) == nr)
        check("Rückgängig nach Abholen -> wieder 'bereit'", b["status"] == "bereit", b["status"])
        settings.locator("label.switch", has_text="Abholbereit").click()
        time.sleep(0.6)
        check("Modus aus: 'bereit'-Bestellung bleibt sichtbar (Badge)", ausgabe.locator(".order .badge-ok", has_text="bereit").count() == 1)

        print("Konflikte zwischen Geräten")
        kasse2 = seite("/kasse")
        api("POST", "/karten", {"beschreibung": "Blau 2"})
        kasse.wait_for_selector(".chip:has-text('Blau 2')")
        kasse2.wait_for_selector(".chip:has-text('Blau 2')")
        for k in (kasse, kasse2):
            tile(k, "Flammkuchen").click()
            k.locator(".chip", has_text="Blau 2").click()
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        time.sleep(0.8)
        check("Andere Kasse: Karte automatisch abgewählt", kasse2.locator(".chip[aria-pressed=true]").inner_text().strip() == "Ohne")
        tile(kasse2, "Glühwein").click()
        pitem(settings, "Glühwein").locator("label.switch").click()  # deaktivieren
        time.sleep(0.8)
        check("Deaktiviertes Produkt fliegt aus fremdem Warenkorb", "Glühwein" not in kasse2.locator(".positionen").inner_text())
        pitem(settings, "Glühwein").locator("label.switch").click()  # wieder an

        print("Einstellungen: Entwurf überlebt Live-Updates")
        zeile = pitem(settings, "Flammkuchen")
        feld = zeile.locator("input").first
        feld.fill("Flammkuchen XL")
        api("POST", "/karten", {"beschreibung": "Grün 3"})
        time.sleep(0.8)
        check("Getippter Name nicht überschrieben", feld.input_value() == "Flammkuchen XL")
        zeile.locator("button", has_text="Speichern").click()
        kasse.wait_for_selector(".tile:has-text('Flammkuchen XL')", timeout=3000)
        check("Gespeicherter Name live an der Kasse", True)

        print("Drucker & Name")
        settings.reload()
        settings.wait_for_selector(".drucker")
        if args.sim_alt:
            settings.evaluate(SIM_POST)
        settings.locator(".drucker .card-head label.switch").click()
        time.sleep(0.8)
        check("Drucker aus: Button 'Nummer drucken' an der Kasse weg",
              kasse.locator("button", has_text="Nummer der letzten Bestellung").count() == 0)
        check("Drucker aus: Bon-Icon in der Ausgabe weg", ausgabe.locator("button[aria-label='Bon nachdrucken']").count() == 0)
        check("Einstellung gespeichert", state()["einstellungen"]["drucker_aktiv"] is False)
        settings.locator(".drucker .card-head label.switch").click()
        time.sleep(0.6)
        settings.locator(".drucker input[placeholder='/dev/usb/lp0']").fill("/etc/passwd")
        settings.locator(".drucker button", has_text="Speichern").click()
        check("Ungültiges Druckergerät wird abgelehnt", toast(settings, "Ungültiges Druckergerät"))
        settings.locator(".drucker button", has_text="Verwerfen").click()
        settings.locator(".drucker textarea").first.fill("Danke & guten Hunger!")
        settings.locator(".drucker select").nth(1).select_option("80")
        settings.locator(".drucker button", has_text="Speichern").click()
        time.sleep(0.6)
        e = state()["einstellungen"]
        check("Bon-Kopf + Papierbreite gespeichert", e["bon_kopf"] == "Danke & guten Hunger!" and e["bon_breite_mm"] == 80, e)
        name = settings.locator("label.field", has_text="Name der Kasse").locator("input")
        name.fill("Sommerfest-Kasse")
        name.press("Enter")
        kasse.wait_for_selector(".brand:has-text('Sommerfest-Kasse')", timeout=3000)
        check("Name live in Kopfzeile (anderes Gerät)", True)
        check("Name im Browser-Tab", "Sommerfest-Kasse" in kasse.title())

        print("Verbindungsabbruch")
        tile(kasse, "Flammkuchen XL").click()
        # Antwort geht verloren, Bestellung ist aber auf dem Server angekommen
        verloren = {"n": 0}

        def antwort_verlieren(route):
            if verloren["n"] == 0:
                verloren["n"] += 1
                route.fetch()  # Server verarbeitet
                route.abort()  # Antwort kommt nie an
            else:
                route.continue_()
        n0 = len(state()["bestellungen"])
        kasse.route("**/api/bestellungen", antwort_verlieren)
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        check("Fehler-Toast bei verlorener Antwort", toast(kasse, "nicht erreichbar"))
        check("Warenkorb bleibt erhalten", kasse.locator(".positionen li").count() == 1)
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        time.sleep(0.8)
        kasse.unroute("**/api/bestellungen")
        check("Erneutes Senden -> trotzdem nur 1 Bestellung", len(state()["bestellungen"]) == n0 + 1)

        server.stop()
        kasse.wait_for_selector(".status.is-off", timeout=5000)
        kasse.wait_for_selector(".offline", timeout=6000)
        check("Offline-Banner erscheint", True)
        tile(kasse, "Flammkuchen XL").click()
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        check("Aufgeben offline -> Fehlermeldung", toast(kasse, "nicht erreichbar", "Zeitüber"))
        server.start()
        kasse.wait_for_selector(".status.is-on", timeout=15000)
        check("Automatisch wieder verbunden", kasse.locator(".offline").count() == 0)
        n0 = len(state()["bestellungen"])
        kasse.locator("button", has_text="Bestellung aufgeben").click()
        time.sleep(0.8)
        check("Nach Reconnect: offline gebliebener Warenkorb geht durch", len(state()["bestellungen"]) == n0 + 1)

        print("Storno")
        ausgabe.reload()
        ausgabe.wait_for_selector(".order")
        if args.sim_alt:
            ausgabe.evaluate(SIM_POST)
        n0 = len(state()["bestellungen"])
        ausgabe.locator(".order").first.locator("button[aria-label=Stornieren]").click()
        ausgabe.locator("dialog button", has_text="Stornieren").click()
        time.sleep(0.6)
        check("Storno über Dialog", len(state()["bestellungen"]) == n0 - 1)

        print("Alle Seiten: Darstellung, XSS, Fehler")
        for pfad in ["/", "/kasse", "/ausgabe", "/front", "/statistik", "/settings"]:
            pg = seite(pfad)
            if pfad == "/statistik":
                pg.wait_for_selector(".plot .main-svg", timeout=20000)
                time.sleep(1)
                kum = pg.locator(".chart-card", has_text="über die Zeit").locator(".plot")
                kum.scroll_into_view_if_needed()
                time.sleep(0.3)
                # Maus exakt auf den letzten Datenpunkt der Serie mit dem kritischen Namen
                pos = kum.evaluate("""gd => {
                  const i = gd.data.findIndex(t => t.name.indexOf('%{y}') >= 0);
                  const t = gd.data[i], xa = gd._fullLayout.xaxis, ya = gd._fullLayout.yaxis, n = t.x.length - 2;
                  const r = gd.getBoundingClientRect();
                  return [r.left + xa._offset + xa.d2p(t.x[n]), r.top + ya._offset + ya.d2p(t.y[n])];
                }""")
                pg.mouse.move(pos[0] - 3, pos[1], steps=3)
                pg.mouse.move(pos[0], pos[1], steps=2)
                time.sleep(0.5)
                hover = kum.locator(".hoverlayer").text_content() or ""
                check("Statistik-Tooltip: Produktname wörtlich, kein Template-Bruch", "50% %{y}" in hover, hover[:120])
                kpis = pg.locator(".kpis").inner_text()
                check("Statistik zeigt Pfand netto + zurück", "Pfand (netto)" in kpis and "zurück" in kpis)
                shot(pg, "statistik")
            check(f"{pfad}: kein XSS ausgeführt", pg.evaluate("window.__xss") is None)
            for w in (390, 800):
                pg.set_viewport_size({"width": w, "height": 900})
                time.sleep(0.2)
                sw = pg.evaluate("document.documentElement.scrollWidth")
                check(f"{pfad} @{w}px: kein horizontales Scrollen", sw <= w, sw)
            pg.close()
        br.close()

    check("Keine JS-Fehler/Dialoge in der Konsole", not konsole, konsole[:5])


if __name__ == "__main__":
    main()
