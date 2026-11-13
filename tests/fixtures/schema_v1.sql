-- Schema der ersten Version (v1) – nur für Migrationstests
CREATE TABLE KARTEN(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    beschreibung TEXT
);

CREATE TABLE BESTELLUNGEN(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitpunkt_annahme datetime,
    zeitpunkt_fertig datetime,
    zeitpunkt_abgeholt datetime,
    
    status VARCHAR(14) DEFAULT "in bearbeitung" CHECK (status IN ("in bearbeitung", "abholbereit", "abgeholt")),
    karte INTEGER,
    preis DECIMAL(5,2),
    FOREIGN KEY (karte) REFERENCES KARTEN(id)
);

CREATE TABLE PRODUKTE(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    beschreibung TEXT,
    preis DECIMAL(3,2),
    pfand DECIMAL(3,2)
);

CREATE TABLE BESTELLUNGSINHALT(
    anzahl INTEGER,
    produkt_id INTEGER,
    bestellung_id INTEGER,

    FOREIGN KEY (bestellung_id) REFERENCES BESTELLUNGEN(id),
    FOREIGN KEY (produkt_id) REFERENCES PRODUKTE(id)
);