"""Akkustand des Kassen-Rechners (/sys/class/power_supply nachgebaut)."""

import pytest

import akku


def geraet(root, name, **werte):
    d = root / name
    d.mkdir()
    for k, v in werte.items():
        (d / k).write_text(f"{v}\n")


@pytest.fixture
def ps(tmp_path, monkeypatch):
    monkeypatch.setattr(akku, "POWER_DIR", str(tmp_path))
    return tmp_path


def test_ohne_akku(ps):
    geraet(ps, "AC", type="Mains", online=1)
    assert akku.status() is None


def test_ordner_fehlt(monkeypatch, tmp_path):
    monkeypatch.setattr(akku, "POWER_DIR", str(tmp_path / "gibtsnicht"))
    assert akku.status() is None


def test_laptop_laedt_ueber_usb_ladechip(ps):
    # So sieht es auf einem Atom-Laptop mit AXP288 aus
    geraet(ps, "axp288_charger", type="USB", online=1, present=1)
    geraet(ps, "axp288_fuel_gauge", type="Battery", status="Charging", capacity=95, present=1)
    assert akku.status() == {"prozent": 95, "netzteil": True, "laedt": True}


def test_strom_weg(ps):
    geraet(ps, "AC", type="Mains", online=0)
    geraet(ps, "BAT0", type="Battery", status="Discharging", capacity=14, present=1)
    assert akku.status() == {"prozent": 14, "netzteil": False, "laedt": False}


def test_ohne_netzteil_eintrag_aus_status_abgeleitet(ps):
    geraet(ps, "BAT0", type="Battery", status="Full", capacity=100)
    assert akku.status()["netzteil"] is True
    (ps / "BAT0" / "status").write_text("Discharging\n")
    assert akku.status()["netzteil"] is False


def test_zwei_akkus_gemittelt_und_funkmaus_ignoriert(ps):
    geraet(ps, "BAT0", type="Battery", status="Discharging", capacity=80)
    geraet(ps, "BAT1", type="Battery", status="Discharging", capacity=40)
    geraet(ps, "hidpp_battery_0", type="Battery", status="Discharging", capacity=5, scope="Device")
    geraet(ps, "BAT2", type="Battery", status="Unknown", capacity=7, present=0)
    assert akku.status()["prozent"] == 60


def test_kaputte_werte(ps):
    geraet(ps, "BAT0", type="Battery", status="Discharging", capacity="abc")
    assert akku.status() is None
    geraet(ps, "BAT1", type="Battery", capacity=150)
    assert akku.status()["prozent"] == 100


def test_api(api, ps):
    assert api.get("/api/system") == (200, {"akku": None})
    geraet(ps, "BAT0", type="Battery", status="Discharging", capacity=42)
    assert api.get("/api/system")[1]["akku"] == {"prozent": 42, "netzteil": False, "laedt": False}
