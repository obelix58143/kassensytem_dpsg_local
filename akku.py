"""Akkustand des Rechners, auf dem die Kasse läuft (Linux, /sys/class/power_supply).

Damit sieht man auf jedem Gerät, wie voll der Kassen-Laptop noch ist und ob er
am Strom hängt. Auf Rechnern ohne Akku (oder ohne Linux) liefert status() None.
"""

import os

POWER_DIR = os.environ.get("KASSE_POWER_DIR", "/sys/class/power_supply")


def _lies(pfad, name):
    try:
        with open(os.path.join(pfad, name), encoding="ascii", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def status():
    try:
        namen = sorted(os.listdir(POWER_DIR))
    except OSError:
        return None
    akkus, quellen = [], []
    for n in namen:
        p = os.path.join(POWER_DIR, n)
        typ = _lies(p, "type")
        if typ == "Battery":
            if _lies(p, "present") == "0" or _lies(p, "scope") == "Device":  # z.B. Akku einer Funkmaus
                continue
            cap = _lies(p, "capacity")
            if cap and cap.isdigit():
                akkus.append((min(int(cap), 100), _lies(p, "status") or "Unknown"))
        elif typ is not None:  # Mains, USB, USB_C, …: Netzteil
            online = _lies(p, "online")
            if online is not None:
                quellen.append(online == "1")
    if not akkus:
        return None
    if quellen:
        netzteil = any(quellen)
    else:  # kein Netzteil-Eintrag: aus dem Akkustatus ableiten
        netzteil = any(s != "Discharging" for _, s in akkus)
    return {
        "prozent": round(sum(c for c, _ in akkus) / len(akkus)),
        "netzteil": netzteil,
        "laedt": any(s == "Charging" for _, s in akkus),
    }
