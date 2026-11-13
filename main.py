import os

import database
import flaskserver

if __name__ == "__main__":
    database.setup_db()
    port = int(os.environ.get("PORT", "5000"))
    print(f"[server] http://0.0.0.0:{port}  (Kasse: /#/kasse, Ausgabe: /#/ausgabe, Display: /#/front)")
    # threaded=True: jede WebSocket-Verbindung belegt einen Thread
    flaskserver.app.run(host="0.0.0.0", port=port, threaded=True)
