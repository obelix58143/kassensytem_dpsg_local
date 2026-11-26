<script setup>
import { computed, ref, watch } from 'vue'
import PlotlyChart from '../components/PlotlyChart.vue'
import Icon from '../components/Icon.vue'
import { karteById, produktById, serverNow, state } from '../store.js'
import { berechne, tagKey, verfuegbareTage } from '../stats.js'
import { dauer, euro, tag as tagFmt, zahl } from '../format.js'

// Nur minütlich neu rechnen, nicht bei jedem Sekunden-Tick der Uhr
const nowMin = computed(() => Math.floor(serverNow() / 60000))

const tage = computed(() => verfuegbareTage(state.bestellungen))
const tag = ref('alle')
// Standard: heute, falls es heute Bestellungen gibt
watch(tage, (t) => {
  const heute = tagKey(serverNow())
  if (tag.value === 'alle' && t.includes(heute) && t.length > 1) tag.value = heute
  if (tag.value !== 'alle' && !t.includes(tag.value)) tag.value = 'alle'
}, { immediate: true })

const bucketMin = ref(30)
const fenster = [15, 30, 60]

const s = computed(() => berechne({
  bestellungen: state.bestellungen,
  produktById: produktById.value,
  karteById: karteById.value,
  tag: tag.value,
  bucketMin: bucketMin.value,
  nowMs: nowMin.value * 60000
}))

const zeitFmt = computed(() => (s.value.mehrtaegig ? '%a %H:%M' : '%H:%M'))
const zeitAchse = computed(() => ({
  tickformat: zeitFmt.value,
  type: 'date',
  ...(s.value.xRange ? { range: s.value.xRange, autorange: false } : {})
}))
const fensterLabel = computed(() => (bucketMin.value === 60 ? 'Stunde' : `${bucketMin.value} min`))
const tagLabel = (k) => tagFmt(new Date(k + 'T12:00:00'))

// ---------- Chart-Spezifikationen ----------

const umsatzKum = (t) => ({
  data: [{
    type: 'scatter', mode: 'lines', line: { color: t.series[0], width: 2, shape: 'hv' },
    x: s.value.umsatzKum.x, y: s.value.umsatzKum.y,
    hovertemplate: `%{x|${zeitFmt.value}}<br><b>%{y:,.2f} €</b><extra></extra>`
  }],
  layout: { xaxis: zeitAchse.value, yaxis: { ticksuffix: ' €', tickformat: ',.0f' }, hovermode: 'x' }
})

const umsatzBuckets = (t) => ({
  data: [{
    type: 'bar', marker: { color: t.series[0] },
    x: s.value.buckets.map(b => b.mitte), y: s.value.buckets.map(b => b.umsatz / 100),
    customdata: s.value.buckets.map(b => [b.bestellungen]),
    hovertemplate: `ab %{x|${zeitFmt.value}}<br><b>%{y:,.2f} €</b> · %{customdata[0]} Bestellungen<extra></extra>`
  }],
  layout: { xaxis: zeitAchse.value, yaxis: { ticksuffix: ' €', tickformat: ',.0f' } }
})

const produktBars = (t) => {
  const p = [...s.value.produkte].reverse()
  return {
    data: [{
      type: 'bar', orientation: 'h', marker: { color: t.series[0] },
      y: p.map(x => x.name), x: p.map(x => x.stk + x.eigen),
      customdata: p.map(x => [x.stk, x.eigen, x.umsatz / 100]),
      hovertemplate: '<b>%{y}</b><br>%{customdata[0]} verkauft · %{customdata[1]} Eigenbedarf<br>%{customdata[2]:,.2f} €<extra></extra>',
      text: p.map(x => String(x.stk + x.eigen)), textposition: 'outside', cliponaxis: false,
      textfont: { color: t.text2 }
    }],
    layout: {
      xaxis: { showgrid: false, showline: false, showticklabels: false },
      yaxis: { showline: true, ticksuffix: '  ', rangemode: undefined },
      margin: { r: 40 }
    }
  }
}

const produktKum = (t) => ({
  data: s.value.produktKum.map((p, i) => ({
    type: 'scatter', mode: 'lines', name: p.name,
    line: { color: t.series[i % t.series.length], width: 2, shape: 'hv' },
    x: p.x, y: p.y,
    hovertemplate: '%{fullData.name}: <b>%{y}</b><extra></extra>'
  })),
  layout: {
    showlegend: s.value.produktKum.length > 1,
    hovermode: 'x unified',
    xaxis: { ...zeitAchse.value, hoverformat: zeitFmt.value },
    margin: { t: 34 }
  }
})

const warteChart = (t) => {
  const b = s.value.buckets.filter(k => k.warteAvgMin != null)
  return {
    data: [{
      type: 'scatter', mode: 'lines+markers',
      line: { color: t.series[0], width: 2 }, marker: { size: 8, color: t.series[0], line: { color: t.surface, width: 2 } },
      x: b.map(k => k.mitte), y: b.map(k => k.warteAvgMin),
      customdata: b.map(k => [k.warteN]),
      hovertemplate: `bestellt ab %{x|${zeitFmt.value}}<br><b>Ø %{y:.1f} min</b> (%{customdata[0]} Bestellungen)<extra></extra>`
    }],
    layout: { xaxis: zeitAchse.value, yaxis: { ticksuffix: ' min' } }
  }
}

const offenChart = (t) => ({
  data: [{
    type: 'scatter', mode: 'lines', line: { color: t.series[0], width: 2, shape: 'hv' },
    fill: 'tozeroy', fillcolor: t.series[0] + '22',
    x: s.value.offen.x, y: s.value.offen.y,
    hovertemplate: `%{x|${zeitFmt.value}}<br><b>%{y} offen</b><extra></extra>`
  }],
  layout: { xaxis: zeitAchse.value, yaxis: { dtick: s.value.kpi.maxOffen <= 6 ? 1 : undefined }, hovermode: 'x' }
})

const kartenChart = (t) => {
  const k = [...s.value.karten].reverse()
  return {
    data: [{
      type: 'bar', orientation: 'h', marker: { color: t.series[0] },
      y: k.map(x => x.name), x: k.map(x => x.n),
      hovertemplate: '<b>%{y}</b>: %{x}× benutzt<extra></extra>',
      text: k.map(x => String(x.n)), textposition: 'outside', cliponaxis: false, textfont: { color: t.text2 }
    }],
    layout: {
      xaxis: { showgrid: false, showline: false, showticklabels: false },
      yaxis: { showline: true, ticksuffix: '  ', rangemode: undefined },
      margin: { r: 40 }
    }
  }
}

const produktChartHoehe = computed(() => Math.max(160, s.value.produkte.length * 40 + 40))
const kartenChartHoehe = computed(() => Math.max(140, s.value.karten.length * 34 + 40))
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>Statistik</h1>
      <a class="btn btn-sm" href="/api/export.csv" download><Icon name="download" :size="16" /> CSV-Export</a>
    </div>

    <div class="filter card" role="group" aria-label="Filter">
      <div class="row">
        <span class="filter-label">Tag</span>
        <button class="chip" :aria-pressed="tag === 'alle'" @click="tag = 'alle'">Alle</button>
        <button v-for="t in tage" :key="t" class="chip" :aria-pressed="tag === t" @click="tag = t">{{ tagLabel(t) }}</button>
      </div>
      <div class="row">
        <span class="filter-label">Zeitfenster</span>
        <button v-for="f in fenster" :key="f" class="chip" :aria-pressed="bucketMin === f" @click="bucketMin = f">
          {{ f === 60 ? '1 h' : f + ' min' }}
        </button>
      </div>
    </div>

    <div v-if="!s.kpi.bestellungen" class="empty" style="margin-top: 16px">Noch keine Bestellungen in diesem Zeitraum.</div>

    <template v-else>
      <div class="kpis">
        <div class="kpi card kpi-hero">
          <div class="kpi-label">Umsatz</div>
          <div class="kpi-value">{{ euro(s.kpi.umsatz) }}</div>
          <div class="kpi-sub">ohne Pfand</div>
        </div>
        <div class="kpi card">
          <div class="kpi-label">Bestellungen</div>
          <div class="kpi-value">{{ s.kpi.bestellungen }}</div>
          <div class="kpi-sub">Ø Bon {{ euro(s.kpi.avgBon) }}</div>
        </div>
        <div class="kpi card">
          <div class="kpi-label">Produkte verkauft</div>
          <div class="kpi-value">{{ s.kpi.verkauft }}</div>
          <div class="kpi-sub">+ {{ s.kpi.eigenStk }} Eigenbedarf</div>
        </div>
        <div class="kpi card">
          <div class="kpi-label">Pfand (netto)</div>
          <div class="kpi-value">{{ euro(s.kpi.pfand) }}</div>
          <div class="kpi-sub">{{ euro(s.kpi.pfandKassiert) }} kassiert · {{ euro(s.kpi.pfandZurueck) }} zurück ({{ s.kpi.rueckStk }} Stk.)</div>
        </div>
        <div v-if="s.kpi.zubereitungAvg != null" class="kpi card">
          <div class="kpi-label">Ø Zubereitung</div>
          <div class="kpi-value">{{ dauer(s.kpi.zubereitungAvg) }}</div>
          <div class="kpi-sub">bis „abholbereit" · danach Ø {{ dauer(s.kpi.abholungAvg) }} bis Abholung</div>
        </div>
        <div class="kpi card">
          <div class="kpi-label">Ø Wartezeit</div>
          <div class="kpi-value">{{ dauer(s.kpi.warteAvg) }}</div>
          <div class="kpi-sub">Median {{ dauer(s.kpi.warteMedian) }} · bis Abholung</div>
        </div>
        <div class="kpi card">
          <div class="kpi-label">Offen</div>
          <div class="kpi-value">{{ s.kpi.offenJetzt }}</div>
          <div class="kpi-sub">max. {{ s.kpi.maxOffen }} gleichzeitig</div>
        </div>
        <div v-if="s.kpi.beste" class="kpi card">
          <div class="kpi-label">Stärkstes Zeitfenster</div>
          <div class="kpi-value">{{ euro(s.kpi.beste.umsatz) }}</div>
          <div class="kpi-sub">
            ab {{ s.kpi.beste.start.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }) }} Uhr
            ({{ fensterLabel }})
          </div>
        </div>
      </div>

      <div class="charts">
        <section class="card chart-card">
          <h2>Umsatz kumuliert</h2>
          <PlotlyChart :spec="umsatzKum" label="Kumulierter Umsatz über die Zeit" />
        </section>
        <section class="card chart-card">
          <h2>Umsatz pro {{ fensterLabel }}</h2>
          <PlotlyChart :spec="umsatzBuckets" label="Umsatz je Zeitfenster" />
        </section>
        <section class="card chart-card">
          <h2>Ausgegebene Produkte</h2>
          <p class="chart-sub">Stück, inkl. Eigenbedarf</p>
          <PlotlyChart :spec="produktBars" :height="produktChartHoehe" label="Stückzahl je Produkt" />
        </section>
        <section class="card chart-card">
          <h2>Verkäufe je Produkt über die Zeit</h2>
          <PlotlyChart :spec="produktKum" label="Kumulierte Stückzahl je Produkt" />
        </section>
        <section class="card chart-card">
          <h2>Ø Wartezeit bis Abholung</h2>
          <p class="chart-sub">nach Bestellzeitpunkt, je {{ fensterLabel }}</p>
          <PlotlyChart :spec="warteChart" label="Durchschnittliche Wartezeit je Zeitfenster" />
        </section>
        <section class="card chart-card">
          <h2>Offene Bestellungen</h2>
          <p class="chart-sub">gleichzeitig wartende Bestellungen</p>
          <PlotlyChart :spec="offenChart" label="Anzahl offener Bestellungen über die Zeit" />
        </section>
        <section v-if="s.karten.length" class="card chart-card">
          <h2>Kartennutzung</h2>
          <PlotlyChart :spec="kartenChart" :height="kartenChartHoehe" label="Nutzung je Karte" />
        </section>
      </div>

      <div v-if="s.rankingKasse.length || s.rankingAusgabe.length" class="rankings">
        <section v-if="s.rankingKasse.length" class="card ranking" aria-labelledby="h-rk">
          <h2 id="h-rk">Kasse – meiste Einnahmen</h2>
          <p class="chart-sub">Warenumsatz ohne Pfand und Eigenbedarf</p>
          <table class="table">
            <thead><tr><th></th><th>Name</th><th class="r">Umsatz</th><th class="r">Bestellungen</th><th class="r">Ø Bon</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in s.rankingKasse" :key="r.name">
                <td><span class="platz" :class="'platz-' + (i + 1)">{{ i + 1 }}</span></td>
                <td><strong>{{ r.name }}</strong></td>
                <td class="r num"><strong>{{ euro(r.umsatz) }}</strong></td>
                <td class="r num">{{ r.bestellungen }}</td>
                <td class="r num">{{ euro(r.avgBon) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section v-if="s.rankingAusgabe.length" class="card ranking" aria-labelledby="h-ra">
          <h2 id="h-ra">Ausgabe – schnellste Bearbeitung</h2>
          <p class="chart-sub">Ø Zeit von der Bestellung bis „{{ state.einstellungen.bereit_aktiv ? 'Fertig' : 'Abgeholt' }}"</p>
          <table class="table">
            <thead><tr><th></th><th>Name</th><th class="r">Ø Zeit</th><th class="r">Bearbeitet</th><th class="r">Schnellste</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in s.rankingAusgabe" :key="r.name">
                <td><span class="platz" :class="'platz-' + (i + 1)">{{ i + 1 }}</span></td>
                <td><strong>{{ r.name }}</strong></td>
                <td class="r num"><strong>{{ dauer(r.avg) }}</strong></td>
                <td class="r num">{{ r.anzahl }}</td>
                <td class="r num">{{ dauer(r.schnellste) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section class="card" style="margin-top: 16px; overflow-x: auto">
        <h2 style="margin-bottom: 8px">Produkte im Detail</h2>
        <table class="table">
          <thead>
            <tr><th>Produkt</th><th class="r">Verkauft</th><th class="r">Eigenbedarf</th><th class="r">Umsatz</th><th class="r">Anteil</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in s.produkte" :key="p.id">
              <td>{{ p.name }}</td>
              <td class="r num">{{ p.stk }}</td>
              <td class="r num">{{ p.eigen }}</td>
              <td class="r num">{{ euro(p.umsatz) }}</td>
              <td class="r num">{{ s.kpi.umsatz ? zahl((p.umsatz / s.kpi.umsatz) * 100) + ' %' : '–' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </main>
</template>

<style>
.filter { display: flex; flex-wrap: wrap; gap: 12px 28px; padding: 12px 16px; }
.filter .row { gap: 8px; }
.filter-label { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 700; margin-right: 4px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 16px; }
.kpi { padding: 16px; }
.kpi-label { font-size: .8rem; color: var(--text-2); font-weight: 600; }
.kpi-value { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; margin: 2px 0; }
.kpi-hero .kpi-value { color: var(--primary); }
.kpi-sub { font-size: .82rem; color: var(--muted); }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 16px; margin-top: 16px; }
.chart-card { padding: 16px 16px 8px; min-width: 0; }
.chart-card h2 { font-size: 1rem; margin-bottom: 4px; }
.chart-sub { font-size: .8rem; color: var(--muted); }
.rankings { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 16px; margin-top: 16px; }
.ranking { padding: 16px; overflow-x: auto; }
.ranking h2 { font-size: 1.05rem; margin-bottom: 2px; }
.ranking .table { margin-top: 8px; }
.ranking .platz { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%; font-weight: 800; background: var(--surface-2); color: var(--text-2); }
/* Gold, Silber, Bronze – ohne Emoji, die fehlen auf manchen Geräten */
.ranking .platz-1 { background: #e8b923; color: #3b2a00; }
.ranking .platz-2 { background: #b9c0c8; color: #22272d; }
.ranking .platz-3 { background: #cd8a4f; color: #2e1600; }
</style>
