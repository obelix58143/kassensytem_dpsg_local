// Reine Berechnungen für die Statistik (kein Vue, kein Plotly) – alles in Lokalzeit.

const MAX_SERIEN = 8 // mehr Farben gibt die Palette nicht her -> Rest = "Sonstige"

export function tagKey(ms) {
  const d = new Date(ms)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function verfuegbareTage(bestellungen) {
  return [...new Set(bestellungen.map(b => tagKey(Date.parse(b.zeitpunkt_annahme))))].sort()
}

function median(arr) {
  if (!arr.length) return null
  const s = [...arr].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

/**
 * @param bestellungen  Liste aus dem Store
 * @param tag           'alle' oder 'YYYY-MM-DD'
 * @param bucketMin     Zeitfenster in Minuten
 * @param nowMs         aktuelle (Server-)Zeit
 */
export function berechne({ bestellungen, produktById, karteById, tag, bucketMin, nowMs }) {
  const alle = bestellungen
    .map(b => ({
      ...b,
      t0: Date.parse(b.zeitpunkt_annahme),
      tb: b.zeitpunkt_bereit ? Date.parse(b.zeitpunkt_bereit) : null,
      t1: b.zeitpunkt_abgeholt ? Date.parse(b.zeitpunkt_abgeholt) : null
    }))
    .filter(b => tag === 'alle' || tagKey(b.t0) === tag)
    .sort((a, b) => a.t0 - b.t0)
  // Reine Pfandrückgaben sind keine Bestellungen (nichts zu machen, nichts abzuholen)
  const liste = alle.filter(b => !b.nur_pfand)
  const istPfandProdukt = (id) => produktById.get(id)?.typ === 'pfand'

  const bezahlt = liste.filter(b => !b.eigenbedarf)
  const umsatz = bezahlt.reduce((s, b) => s + b.preis_cent, 0)
  // Pfand je Position: positiv = kassiert, negativ = zurückgezahlt
  let pfandKassiert = 0, pfandZurueck = 0, rueckStk = 0
  for (const b of alle) {
    for (const p of b.produkte) {
      const v = (p.einzelpfand_cent || 0) * p.anzahl
      if (v > 0) pfandKassiert += v
      if (v < 0) { pfandZurueck -= v; rueckStk += p.anzahl }
    }
  }
  const pfand = pfandKassiert - pfandZurueck
  const warte = liste.filter(b => b.t1 != null).map(b => b.t1 - b.t0)
  const zubereitung = liste.filter(b => b.tb != null).map(b => b.tb - b.t0)
  const abholung = liste.filter(b => b.tb != null && b.t1 != null).map(b => b.t1 - b.tb)
  const avg = (a) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null)
  const istHeute = tag === 'alle' || tag === tagKey(nowMs)

  // --- Produkte ---
  const prod = new Map()
  for (const b of liste) {
    for (const p of b.produkte) {
      if (istPfandProdukt(p.id)) continue
      const e = prod.get(p.id) || { id: p.id, name: produktById.get(p.id)?.name ?? `Produkt #${p.id}`, stk: 0, eigen: 0, umsatz: 0, events: [] }
      if (b.eigenbedarf) e.eigen += p.anzahl
      else { e.stk += p.anzahl; e.umsatz += p.anzahl * p.einzelpreis_cent }
      e.events.push([b.t0, p.anzahl])
      prod.set(p.id, e)
    }
  }
  const produkte = [...prod.values()].sort((a, b) => (b.stk + b.eigen) - (a.stk + a.eigen) || a.name.localeCompare(b.name))
  const verkauft = produkte.reduce((s, p) => s + p.stk, 0)
  const eigenStk = produkte.reduce((s, p) => s + p.eigen, 0)

  const tStart = liste.length ? liste[0].t0 : nowMs
  const tEnde = liste.length ? Math.max(istHeute ? nowMs : 0, ...liste.map(b => b.t1 ?? b.t0)) : nowMs

  // --- Zeitfenster ---
  const bMs = bucketMin * 60000
  const buckets = []
  if (liste.length) {
    const first = Math.floor(tStart / bMs) * bMs
    const last = Math.floor(liste[liste.length - 1].t0 / bMs) * bMs
    const idx = new Map()
    for (let t = first; t <= last; t += bMs) {
      idx.set(t, buckets.length)
      buckets.push({ start: new Date(t), mitte: new Date(t + bMs / 2), umsatz: 0, bestellungen: 0, warte: [] })
    }
    for (const b of liste) {
      const k = buckets[idx.get(Math.floor(b.t0 / bMs) * bMs)]
      k.bestellungen++
      if (!b.eigenbedarf) k.umsatz += b.preis_cent
      if (b.t1 != null) k.warte.push(b.t1 - b.t0)
    }
    for (const k of buckets) {
      k.warteAvgMin = k.warte.length ? k.warte.reduce((s, x) => s + x, 0) / k.warte.length / 60000 : null
      k.warteN = k.warte.length
      delete k.warte
    }
  }
  const beste = buckets.reduce((best, k) => (k.umsatz > (best?.umsatz ?? -1) ? k : best), null)

  // --- Umsatz kumuliert ---
  const umsatzKum = { x: [], y: [] }
  if (liste.length) {
    let s = 0
    umsatzKum.x.push(new Date(tStart)); umsatzKum.y.push(0)
    for (const b of bezahlt) { s += b.preis_cent; umsatzKum.x.push(new Date(b.t0)); umsatzKum.y.push(s / 100) }
    umsatzKum.x.push(new Date(tEnde)); umsatzKum.y.push(s / 100)
  }

  // --- Produktverkäufe kumuliert (Top 7 + Sonstige) ---
  let serien = produkte
  if (produkte.length > MAX_SERIEN) {
    const rest = produkte.slice(MAX_SERIEN - 1)
    serien = [
      ...produkte.slice(0, MAX_SERIEN - 1),
      { id: 'rest', name: `Sonstige (${rest.length})`, events: rest.flatMap(p => p.events) }
    ]
  }
  const produktKum = serien.map(p => {
    const ev = [...p.events].sort((a, b) => a[0] - b[0])
    const x = [new Date(tStart)], y = [0]
    let s = 0
    for (const [t, n] of ev) { s += n; x.push(new Date(t)); y.push(s) }
    x.push(new Date(tEnde)); y.push(s)
    return { id: p.id, name: p.name, x, y }
  })

  // --- Offene Bestellungen über die Zeit ---
  const events = []
  for (const b of liste) {
    events.push([b.t0, 1])
    if (b.t1 != null) events.push([b.t1, -1])
  }
  events.sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const offen = { x: [], y: [] }
  let o = 0, maxOffen = 0
  for (const [t, d] of events) {
    o += d
    maxOffen = Math.max(maxOffen, o)
    offen.x.push(new Date(t)); offen.y.push(o)
  }
  if (liste.length) { offen.x.push(new Date(tEnde)); offen.y.push(o) }

  // --- Karten ---
  const kartenMap = new Map()
  for (const b of liste) {
    if (b.karte == null) continue
    const name = karteById.get(b.karte)?.beschreibung ?? `Karte #${b.karte}`
    kartenMap.set(name, (kartenMap.get(name) || 0) + 1)
  }
  const karten = [...kartenMap.entries()].map(([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n)

  // --- Ranking Kasse: wer hat am meisten eingenommen (Waren, ohne Pfand) ---
  const kasseMap = new Map()
  for (const b of liste) {
    if (!b.kassierer) continue
    const e = kasseMap.get(b.kassierer) || { name: b.kassierer, umsatz: 0, bestellungen: 0, stk: 0 }
    e.bestellungen++
    if (!b.eigenbedarf) e.umsatz += b.preis_cent
    for (const p of b.produkte) if (!istPfandProdukt(p.id)) e.stk += p.anzahl
    kasseMap.set(b.kassierer, e)
  }
  const rankingKasse = [...kasseMap.values()]
    .map(e => ({ ...e, avgBon: e.bestellungen ? e.umsatz / e.bestellungen : 0 }))
    .sort((a, b) => b.umsatz - a.umsatz || b.bestellungen - a.bestellungen || a.name.localeCompare(b.name))

  // --- Ranking Ausgabe: wer meldet am schnellsten fertig (Bestellung -> fertig/abgeholt) ---
  const ausMap = new Map()
  for (const b of liste) {
    const fertig = b.tb ?? b.t1
    if (!b.ausgabe || fertig == null) continue
    const e = ausMap.get(b.ausgabe) || { name: b.ausgabe, zeiten: [] }
    e.zeiten.push(fertig - b.t0)
    ausMap.set(b.ausgabe, e)
  }
  const rankingAusgabe = [...ausMap.values()]
    .map(e => ({ name: e.name, anzahl: e.zeiten.length, avg: avg(e.zeiten), median: median(e.zeiten), schnellste: Math.min(...e.zeiten) }))
    .sort((a, b) => a.avg - b.avg || b.anzahl - a.anzahl || a.name.localeCompare(b.name))

  return {
    rankingKasse,
    rankingAusgabe,
    kpi: {
      umsatz,
      pfand,
      pfandKassiert,
      pfandZurueck,
      rueckStk,
      pfandVorgaenge: alle.length - liste.length,
      zubereitungAvg: avg(zubereitung),
      abholungAvg: avg(abholung),
      bestellungen: liste.length,
      bezahlteBestellungen: bezahlt.length,
      avgBon: bezahlt.length ? umsatz / bezahlt.length : 0,
      verkauft,
      eigenStk,
      warteAvg: warte.length ? warte.reduce((s, x) => s + x, 0) / warte.length : null,
      warteMedian: median(warte),
      offenJetzt: liste.filter(b => b.status === 'bestellt').length,
      maxOffen,
      beste
    },
    buckets,
    umsatzKum,
    produkte,
    produktKum,
    offen,
    karten,
    mehrtaegig: new Set(liste.map(b => tagKey(b.t0))).size > 1,
    // Sehr kurzer Zeitraum (Start des Abends): Achse auf mind. 30 min strecken,
    // sonst steht an jedem Strich dieselbe Uhrzeit
    xRange: liste.length && tEnde - tStart < 30 * 60000
      ? [new Date(tStart - 2 * 60000), new Date(tStart + 30 * 60000)]
      : null
  }
}
