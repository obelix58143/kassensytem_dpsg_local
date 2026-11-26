import os
import signal
import sys
import threading

import database
import flaskserver

# Alle N Minuten eine Sicherung (nur wenn sich seit der letzten etwas geändert hat)
BACKUP_MINUTEN = float(os.environ.get("KASSE_BACKUP_MINUTEN", "5"))


def sicherungsdienst():
    stand = database.aenderungen
    while True:
        threading.Event().wait(BACKUP_MINUTEN * 60)
        if database.aenderungen != stand:
            stand = database.aenderungen
            database.sicherung_erstellen("auto")


def beenden(signum, _frame):
    # systemctl stop / Strg+C: letzten Stand sichern, dann sauber beenden
    print("[server] wird beendet – letzte Sicherung …")
    database.sicherung_erstellen("ende")
    sys.exit(0)


if __name__ == "__main__":
    database.startpruefung()  # nach Stromausfall: kaputte DB -> letzte Sicherung
    database.setup_db()
    print(f"[db] Datenbank: {database.DB_PATH}")
    print(f"[backup] Sicherungen alle {BACKUP_MINUTEN:g} min nach: {database.BACKUP_DIR}")
    database.sicherung_erstellen("start")
    if BACKUP_MINUTEN > 0:
        threading.Thread(target=sicherungsdienst, daemon=True, name="sicherung").start()
    signal.signal(signal.SIGTERM, beenden)
    signal.signal(signal.SIGINT, beenden)

    port = int(os.environ.get("PORT", "5000"))
    print(f"[server] http://0.0.0.0:{port}  (Kasse: /#/kasse, Ausgabe: /#/ausgabe, Display: /#/front)")
    # threaded=True: jede WebSocket-Verbindung belegt einen Thread
    flaskserver.app.run(host="0.0.0.0", port=port, threaded=True)
