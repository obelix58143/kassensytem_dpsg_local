<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import api, { newClientRef } from '../api.js'
import { aktiveProdukte, pfandProdukte, produktById, state, verkaufsProdukte } from '../store.js'
import { euro } from '../format.js'
import { toast, showError } from '../ui.js'
import Icon from '../components/Icon.vue'

// Warenkorb: produktId -> Anzahl (Reihenfolge = Reihenfolge des Hinzufügens)
const korb = reactive(new Map())
const eigenbedarf = ref(false)
const karte = ref(null)
const gegeben = ref([]) // Liste von Cent-Beträgen
const sending = ref(false)
let clientRef = newClientRef()
const letzte = ref(null) // Info zur zuletzt aufgegebenen Bestellung (für Rückgeld)
const korbEl = ref(null)
const zumKorb = () => korbEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })

const scheine = [5000, 2000, 1000, 500]
const muenzen = [200, 100, 50, 20, 10, 5]

const positionen = computed(() =>
  [...korb.entries()]
    .map(([id, anzahl]) => ({ produkt: produktById.value.get(id), anzahl }))
    .filter(p => p.produkt)
)
const anzahlGesamt = computed(() => positionen.value.reduce((s, p) => s + p.anzahl, 0))
const istRueckgabe = (p) => p.typ === 'pfand'
const warenwert = computed(() => eigenbedarf.value ? 0 : positionen.value.reduce((s, p) => s + p.produkt.preis_cent * p.anzahl, 0))
// Pfand für neue Produkte (+) und Pfandrückgabe (−), getrennt angezeigt
const pfandPlus = computed(() => eigenbedarf.value ? 0 : positionen.value.filter(p => !istRueckgabe(p.produkt)).reduce((s, p) => s + p.produkt.pfand_cent * p.anzahl, 0))
const pfandMinus = computed(() => eigenbedarf.value ? 0 : positionen.value.filter(p => istRueckgabe(p.produkt)).reduce((s, p) => s + p.produkt.pfand_cent * p.anzahl, 0))
const gesamt = computed(() => warenwert.value + pfandPlus.value - pfandMinus.value)
// Nur Pfandrückgabe: nichts abzuholen, keine Karte, Geld geht raus
const nurPfand = computed(() => positionen.value.length > 0 && positionen.value.every(p => istRueckgabe(p.produkt)))
function positionsSumme(pos) {
  if (eigenbedarf.value) return 0
  return istRueckgabe(pos.produkt) ? -pos.produkt.pfand_cent * pos.anzahl : pos.produkt.preis_cent * pos.anzahl
}
const aufgebenText = computed(() => {
  if (sending.value) return 'Sende …'
  if (nurPfand.value) return `Pfand auszahlen · ${euro(-gesamt.value)}`
  if (gesamt.value < 0) return `Aufgeben · ${euro(-gesamt.value)} auszahlen`
  return `Bestellung aufgeben · ${euro(gesamt.value)}`
})
const gegebenSumme = computed(() => gegeben.value.reduce((s, c) => s + c, 0))
const rueckgeld = computed(() => gegebenSumme.value - gesamt.value)
const freieKarten = computed(() => state.karten.filter(k => !k.inUse || k.id === karte.value))

function add(id, n = 1) {
  letzte.value = null
  const neu = (korb.get(id) || 0) + n
  if (neu <= 0) korb.delete(id)
  else korb.set(id, neu)
}

function leeren() {
  korb.clear()
  eigenbedarf.value = false
  karte.value = null
  gegeben.value = []
  clientRef = newClientRef()
}

// Produkt wurde (an einem anderen Gerät) deaktiviert -> aus dem Korb nehmen
watch(aktiveProdukte, (list) => {
  const ids = new Set(list.map(p => p.id))
  for (const id of [...korb.keys()]) {
    if (!ids.has(id)) {
      korb.delete(id)
      toast('Ein Produkt im Warenkorb ist nicht mehr verfügbar und wurde entfernt', 'warn')
    }
  }
})
// Karte wurde gerade an einer anderen Kasse vergeben
watch(() => state.karten, (list) => {
  if (karte.value == null) return
  const k = list.find(k => k.id === karte.value)
  if (!k || k.inUse) {
    karte.value = null
    toast('Die gewählte Karte ist nicht mehr frei', 'warn')
  }
})

async function aufgeben() {
  if (sending.value || positionen.value.length === 0) return
  sending.value = true
  const betrag = gesamt.value
  const bezahlt = gegebenSumme.value
  try {
    const res = await api.addBestellung({
      client_ref: clientRef,
      karte: nurPfand.value ? null : karte.value,
      eigenbedarf: eigenbedarf.value,
      produkte: positionen.value.map(p => ({ id: p.produkt.id, anzahl: p.anzahl }))
    })
    const serverGesamt = res.preis_cent + res.pfand_cent
    letzte.value = {
      id: res.id, nurPfand: res.nur_pfand, gesamt: serverGesamt, gegeben: bezahlt,
      rueckgeld: bezahlt && serverGesamt > 0 ? bezahlt - serverGesamt : null
    }
    leeren()
    if (serverGesamt !== betrag) toast(`Preis wurde zwischenzeitlich geändert: ${euro(serverGesamt)}`, 'warn')
    if (res.nur_pfand) toast(`Pfand ausgezahlt: ${euro(-serverGesamt)}`, 'ok')
    else if (res.gedruckt === false) toast(`Bestellung #${res.id} gespeichert – Bon NICHT gedruckt (Drucker prüfen)`, 'warn', { timeout: 8000 })
    else toast(`Bestellung #${res.id} aufgegeben`, 'ok')
  } catch (e) {
    // clientRef bleibt gleich: erneutes Drücken legt keine doppelte Bestellung an
    showError(e)
  } finally {
    sending.value = false
  }
}

async function letzteNummer() {
  try {
    const r = await api.letzteNummerDrucken()
    toast(r.gedruckt ? `Nummer ${r.id} gedruckt` : 'Drucker nicht verbunden', r.gedruckt ? 'ok' : 'warn')
  } catch (e) { showError(e) }
}

function onKey(e) {
  if (e.target.closest('input, textarea, select')) return
  if (e.key === 'Enter') { e.preventDefault(); aufgeben() }
  if (e.key === 'Escape') leeren()
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <main class="page kasse">
    <section class="produkte" aria-label="Produkte">
      <div v-if="aktiveProdukte.length === 0" class="empty">
        Noch keine Produkte – unter <router-link to="/settings">Einstellungen</router-link> anlegen.
      </div>
      <div class="tiles">
        <div v-for="p in verkaufsProdukte" :key="p.id" class="tile-wrap">
          <button class="tile" :class="{ 'in-korb': korb.has(p.id) }" @click="add(p.id)">
            <span class="tile-name">{{ p.name }}</span>
            <span v-if="p.beschreibung" class="tile-desc">{{ p.beschreibung }}</span>
            <span class="tile-price">
              {{ euro(p.preis_cent) }}
              <small v-if="p.pfand_cent">+ {{ euro(p.pfand_cent) }} Pfand</small>
            </span>
          </button>
          <span v-if="korb.has(p.id)" class="tile-count" aria-label="Anzahl im Warenkorb">{{ korb.get(p.id) }}</span>
          <button v-if="korb.has(p.id)" class="tile-minus" :aria-label="p.name + ' entfernen'" @click="add(p.id, -1)">−</button>
        </div>
      </div>

      <template v-if="pfandProdukte.length">
        <h2 class="pfand-titel">Pfandrückgabe</h2>
        <div class="tiles">
          <div v-for="p in pfandProdukte" :key="p.id" class="tile-wrap">
            <button class="tile tile-pfand" :class="{ 'in-korb': korb.has(p.id) }" @click="add(p.id)">
              <span class="tile-name">{{ p.name }}</span>
              <span v-if="p.beschreibung" class="tile-desc">{{ p.beschreibung }}</span>
              <span class="tile-price">− {{ euro(p.pfand_cent) }}</span>
            </button>
            <span v-if="korb.has(p.id)" class="tile-count" aria-label="Anzahl im Warenkorb">{{ korb.get(p.id) }}</span>
            <button v-if="korb.has(p.id)" class="tile-minus" :aria-label="p.name + ' entfernen'" @click="add(p.id, -1)">−</button>
          </div>
        </div>
      </template>
    </section>

    <aside ref="korbEl" class="korb card" aria-label="Aktuelle Bestellung">
      <div class="card-head">
        <h2>Bestellung <span v-if="anzahlGesamt" class="badge">{{ anzahlGesamt }} Artikel</span></h2>
        <button class="btn btn-ghost btn-sm" :disabled="!korb.size && !gegeben.length" @click="leeren">Leeren</button>
      </div>

      <div v-if="letzte && !korb.size" class="letzte">
        <div class="row">
          <span class="badge badge-ok">✓ {{ letzte.nurPfand ? 'Pfand ausgezahlt' : 'Aufgegeben' }}</span>
          <strong v-if="!letzte.nurPfand" class="letzte-id">#{{ letzte.id }}</strong>
          <span class="spacer"></span>
          <span class="num">{{ euro(letzte.gesamt) }}</span>
        </div>
        <div v-if="letzte.gesamt < 0" class="letzte-rueck">
          Auszahlen <strong class="num">{{ euro(-letzte.gesamt) }}</strong>
        </div>
        <div v-if="letzte.rueckgeld != null" class="letzte-rueck">
          Rückgeld <strong class="num">{{ euro(letzte.rueckgeld) }}</strong>
          <span class="muted">(gegeben {{ euro(letzte.gegeben) }})</span>
        </div>
      </div>

      <ul v-if="positionen.length" class="positionen">
        <li v-for="pos in positionen" :key="pos.produkt.id">
          <span class="pos-name">{{ pos.produkt.name }}</span>
          <span class="stepper">
            <button class="btn btn-icon btn-sm" :aria-label="'Weniger ' + pos.produkt.name" @click="add(pos.produkt.id, -1)">−</button>
            <span class="num pos-anz">{{ pos.anzahl }}</span>
            <button class="btn btn-icon btn-sm" :aria-label="'Mehr ' + pos.produkt.name" @click="add(pos.produkt.id, 1)">+</button>
          </span>
          <span class="num pos-sum" :class="{ negativ: positionsSumme(pos) < 0 }">{{ euro(positionsSumme(pos)) }}</span>
        </li>
      </ul>
      <p v-else-if="!letzte" class="muted hint">Produkte links antippen.</p>

      <div class="section">
        <label class="switch">
          <input v-model="eigenbedarf" type="checkbox">
          Eigenbedarf (kostenlos)
        </label>
      </div>

      <div v-if="state.karten.length && !nurPfand" class="section">
        <div class="label">Karte</div>
        <div class="row chips">
          <button class="chip" :aria-pressed="karte === null" @click="karte = null">Ohne</button>
          <button v-for="k in freieKarten" :key="k.id" class="chip" :aria-pressed="karte === k.id" @click="karte = k.id">
            {{ k.beschreibung }}
          </button>
        </div>
      </div>

      <div class="summen section">
        <div v-if="!nurPfand" class="sum-row"><span>Waren</span><span class="num">{{ euro(warenwert) }}</span></div>
        <div v-if="pfandPlus" class="sum-row"><span>Pfand</span><span class="num">{{ euro(pfandPlus) }}</span></div>
        <div v-if="pfandMinus" class="sum-row"><span>Pfandrückgabe</span><span class="num negativ">− {{ euro(pfandMinus) }}</span></div>
        <div class="sum-row total" :class="{ auszahlen: gesamt < 0 }">
          <span>{{ gesamt < 0 ? 'Auszahlen' : 'Gesamt' }}</span><span>{{ euro(Math.abs(gesamt)) }}</span>
        </div>
      </div>

      <div v-if="gesamt > 0" class="section">
        <div class="label">Gegeben</div>
        <div class="geld">
          <button class="btn btn-sm passend" @click="gegeben = [gesamt]">Passend</button>
          <button v-for="c in scheine" :key="c" class="btn btn-sm schein" @click="gegeben.push(c)">{{ c / 100 }} €</button>
        </div>
        <div class="geld">
          <button v-for="c in muenzen" :key="c" class="btn btn-sm muenze" @click="gegeben.push(c)">{{ c >= 100 ? c / 100 + ' €' : c + ' ct' }}</button>
          <button class="btn btn-sm btn-ghost" :disabled="!gegeben.length" aria-label="Letzten Betrag entfernen" @click="gegeben.pop()"><Icon name="undo" /></button>
        </div>
        <div v-if="gegeben.length" class="rueckgeld" :class="rueckgeld < 0 ? 'fehlt' : 'ok'">
          <span>{{ rueckgeld < 0 ? 'Fehlt noch' : 'Rückgeld' }}</span>
          <strong class="num">{{ euro(Math.abs(rueckgeld)) }}</strong>
          <small class="muted">gegeben {{ euro(gegebenSumme) }}</small>
        </div>
      </div>

      <button class="btn btn-primary btn-lg btn-block" :disabled="!positionen.length || sending" @click="aufgeben">
        {{ aufgebenText }}
      </button>
      <button v-if="state.einstellungen.drucker_aktiv" class="btn btn-ghost btn-sm btn-block" style="margin-top: 6px" @click="letzteNummer">
        Nummer der letzten Bestellung drucken
      </button>
    </aside>

    <!-- Nur auf schmalen Geräten: Summe immer sichtbar -->
    <button v-if="anzahlGesamt" class="mobile-bar btn btn-primary btn-lg" @click="zumKorb">
      <span class="badge">{{ anzahlGesamt }}</span> Zur Bestellung · {{ gesamt < 0 ? 'auszahlen ' : '' }}{{ euro(Math.abs(gesamt)) }}
    </button>
  </main>
</template>

<style>
.kasse { display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, 400px); gap: 20px; align-items: start; }
@media (max-width: 900px) { .kasse { grid-template-columns: minmax(0, 1fr); } }

.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
.tile-wrap { position: relative; }
.tile {
  width: 100%; min-height: 128px;
  display: flex; flex-direction: column; align-items: flex-start; gap: 4px;
  padding: 16px; text-align: left;
  background: var(--surface); color: var(--text);
  border: 1.5px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow);
  font: inherit; cursor: pointer;
  touch-action: manipulation; user-select: none;
  transition: transform .06s, border-color .12s, background .12s;
}
.tile:hover { border-color: var(--border-strong); }
.tile:active { transform: scale(.97); }
.tile.in-korb { border-color: var(--primary); background: var(--primary-soft); }
.tile-name { font-weight: 700; font-size: 1.1rem; line-height: 1.25; }
.tile-desc { font-size: .85rem; color: var(--text-2); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.tile-price { margin-top: auto; font-weight: 700; color: var(--primary); font-size: 1.05rem; }
.tile-price small { display: block; font-weight: 500; color: var(--muted); font-size: .8rem; }
.tile-count {
  position: absolute; top: -8px; right: -8px;
  min-width: 34px; height: 34px; padding: 0 8px;
  display: flex; align-items: center; justify-content: center;
  background: var(--primary); color: var(--on-primary);
  border-radius: 999px; font-weight: 800; font-size: 1.05rem;
  box-shadow: 0 2px 6px rgba(0,0,0,.25);
  pointer-events: none;
}
.tile-minus {
  position: absolute; bottom: 10px; right: 10px;
  width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid var(--border-strong); background: var(--surface);
  color: var(--text); font-size: 1.4rem; line-height: 1; cursor: pointer;
}

.korb { position: sticky; top: 72px; display: flex; flex-direction: column; max-height: calc(100vh - 92px); overflow-y: auto; }
@media (max-width: 900px) { .korb { position: static; max-height: none; } }
.korb .section { padding: 12px 0; border-top: 1px solid var(--border); }
.korb .label { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 700; margin-bottom: 8px; }
.korb .hint { padding: 8px 0 14px; }
.chips { gap: 8px; }

.positionen { list-style: none; margin: 0 0 8px; padding: 0; }
.positionen li { display: grid; grid-template-columns: minmax(0, 1fr) auto 76px; gap: 10px; align-items: center; padding: 6px 0; }
.pos-name { font-weight: 600; }
.stepper { display: inline-flex; align-items: center; gap: 6px; }
.stepper .btn { width: 36px; font-size: 1.1rem; }
.pos-anz { min-width: 22px; text-align: center; font-weight: 700; }
.pos-sum { text-align: right; }

.summen .sum-row { display: flex; justify-content: space-between; padding: 2px 0; color: var(--text-2); }
.summen .total { color: var(--text); font-size: 1.6rem; font-weight: 800; margin-top: 4px; }

.geld { display: grid; grid-template-columns: repeat(auto-fill, minmax(64px, 1fr)); gap: 6px; margin-bottom: 6px; }
.geld .btn { padding: 0 6px; }
.schein { background: var(--surface-2); }
.passend { grid-column: span 2; }
.rueckgeld { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; padding: 10px 12px; border-radius: var(--radius-sm); margin-top: 6px; font-weight: 600; }
.rueckgeld strong { font-size: 1.5rem; }
.rueckgeld.ok { background: var(--ok-soft); color: var(--ok); }
.rueckgeld.fehlt { background: var(--danger-soft); color: var(--danger); }

.kasse .mobile-bar { display: none; }
@media (max-width: 900px) {
  .kasse .mobile-bar { display: flex; position: fixed; left: 16px; right: 16px; bottom: 16px; bottom: max(16px, env(safe-area-inset-bottom)); z-index: 30; box-shadow: var(--shadow-lg); }
  .kasse { padding-bottom: 100px; }
}
.pfand-titel { margin: 22px 0 10px; font-size: 1rem; color: var(--text-2); }
.tile-pfand { border-style: dashed; min-height: 96px; }
.tile-pfand .tile-price { color: var(--ok); }
.tile-pfand.in-korb { border-color: var(--ok); background: var(--ok-soft); }
.negativ { color: var(--ok); }
.summen .total.auszahlen { color: var(--ok); }
.letzte { background: var(--ok-soft); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 12px; }
.letzte-id { font-size: 1.3rem; }
.letzte-rueck { margin-top: 6px; color: var(--ok); }
.letzte-rueck strong { font-size: 1.5rem; margin: 0 4px; }
</style>
