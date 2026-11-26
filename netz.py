"""IPv4-Adressen des Kassen-Rechners – damit man sie auf der Startseite
ablesen und in die Tablets eintippen kann."""

import ipaddress
import socket
import subprocess


def _gueltig(ip):
    try:
        a = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast)


def adressen():
    """Liste der IPv4-Adressen im lokalen Netz (private zuerst), leer wenn offline."""
    gefunden = []
    try:
        aus = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout
        gefunden = [x for x in aus.split() if _gueltig(x)]
    except (OSError, subprocess.SubprocessError):
        pass
    if not gefunden:
        # Fallback: Ausgehende Adresse über die Routing-Tabelle (es wird nichts gesendet)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if _gueltig(ip):
                gefunden = [ip]
        except OSError:
            pass
        finally:
            s.close()
    # Docker-/VPN-Brücken nach hinten, private LAN-Adressen nach vorn
    return sorted(dict.fromkeys(gefunden), key=lambda x: (not ipaddress.IPv4Address(x).is_private, x.startswith("172.")))


def hostname():
    try:
        return socket.gethostname()
    except OSError:
        return None
