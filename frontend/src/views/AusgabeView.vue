<script setup>
import { computed, ref } from 'vue'
import api from '../api.js'
import { abgeholteBestellungen, abholbereit, inZubereitung, karteById, offeneBestellungen, produktById, state } from '../store.js'
import { euro, uhrzeit } from '../format.js'
import { confirmDialog, showError, toast } from '../ui.js'
import BestellPositionen from '../components/BestellPositionen.vue'
import OrderCard from '../components/OrderCard.vue'
import Icon from '../components/Icon.vue'
import PersonWahl from '../components/PersonWahl.vue'
import { ausgabePerson, letzteAusgabe } from '../personen.js'

const maxAbgeholt = ref(8)
const busy = ref(new Set())
const bereitAktiv = computed(() => !!state.einstellungen.bereit_aktiv)

// Was die Küche noch machen muss (Pfandrückgaben zählen nicht)
const zuProduzieren = computed(() => {
  const sum = new Map()
  const liste = bereitAktiv.value ? inZubereitung.value : offeneBestellungen.value
  for (const b of liste) {
    for (const p of b.produkte) {
      if (produktById.value.get(p.id)?.typ === 'pfand') continue
      sum.set(p.id, (sum.get(p.id) || 0) + p.anzahl)
    }
  }
  return [...sum.entries()]
    .map(([id, anzahl]) => ({ id, anzahl, name: produktById.value.get(id)?.name ?? `#${id}` }))
    .sort((a, b) => b.anzahl - a.anzahl)
})

const karteName = (id) => (id == null ? null : karteById.value.get(id)?.beschreibung ?? '?')

async function run(id, fn) {
  if (busy.value.has(id)) return
  busy.value.add(id)
  try { await fn() } catch (e) { showError(e) } finally { busy.value.delete(id) }
}

function setStatus(b, status, text, undoStatus) {
  run(b.id, async () => {
    // Wer fertig meldet, zählt fürs Ranking „schnellste Bearbeitung"
    await api.setStatus(b.id, status, (state.einstellungen.name_ausgabe !== false && ausgabePerson.value) || null)
    toast(`#${b.id} ${text}`, 'ok', { action: { label: 'Rückgängig', run: () => run(b.id, () => api.setStatus(b.id, undoStatus)) } })
  })
}
const fertig = (b) => setStatus(b, 'bereit', 'ist abholbereit', 'bestellt')
const abgeholt = (b) => setStatus(b, 'abgeholt', 'abgeholt', b.status)
const zurueckInZubereitung = (b) => run(b.id, () => api.setStatus(b.id, 'bestellt'))
// Aus „Zuletzt abgeholt" zurückholen: in den vorherigen offenen Zustand
const zurueck = (b) => run(b.id, () => api.setStatus(b.id, bereitAktiv.value ? 'bereit' : 'bestellt'))

async function storno(b) {
  const ok = await confirmDialog({
    title: `Bestellung #${b.id} stornieren?`,
    text: `${euro(b.preis_cent + b.pfand_cent)} – das Geld muss zurückgegeben werden. Kann nicht rückgängig gemacht werden.`,
    confirmText: 'Stornieren',
    danger: true
  })
  if (ok) run(b.id, async () => { await api.storno(b.id); toast(`#${b.id} storniert`, 'ok') })
}
function bon(b) {
  run(b.id, async () => {
    const r = await api.bonNachdrucken(b.id)
    toast(r.gedruckt ? `Bon #${b.id} gedruckt` : 'Drucker nicht verbunden', r.gedruckt ? 'ok' : 'warn')
  })
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>Ausgabe</h1>
      <div v-if="zuProduzieren.length" class="row produktion" aria-label="Offen zu produzieren">
        <span class="muted">{{ bereitAktiv ? 'Zu machen:' : 'Offen:' }}</span>
        <span v-for="p in zuProduzieren" :key="p.id" class="badge badge-primary prod-badge">{{ p.anzahl }}× {{ p.name }}</span>
      </div>
    </div>

    <PersonWahl v-if="state.einstellungen.name_ausgabe !== false" v-model="ausgabePerson" label="Ausgabe:" :vorschlaege="letzteAusgabe" class="ausgabe-person" />

    <div class="ausgabe">
      <div>
        <template v-if="bereitAktiv">
          <section aria-labelledby="h-bereit" class="ausgabe-sec">
            <h2 id="h-bereit" class="sec-title">Abholbereit <span class="badge badge-ok">{{ abholbereit.length }}</span></h2>
            <div v-if="!abholbereit.length" class="empty empty-sm">Nichts wartet auf Abholung.</div>
            <TransitionGroup tag="div" name="list" class="order-grid">
              <OrderCard v-for="b in abholbereit" :key="b.id" :b="b" phase="bereit" :busy="busy.has(b.id)"
                         @abgeholt="abgeholt" @zurueck="zurueckInZubereitung" @bon="bon" @storno="storno" />
            </TransitionGroup>
          </section>
          <section aria-labelledby="h-zub" class="ausgabe-sec">
            <h2 id="h-zub" class="sec-title">In Zubereitung <span class="badge">{{ inZubereitung.length }}</span></h2>
            <div v-if="!inZubereitung.length" class="empty empty-sm">Keine offenen Bestellungen</div>
            <TransitionGroup tag="div" name="list" class="order-grid">
              <OrderCard v-for="b in inZubereitung" :key="b.id" :b="b" phase="zubereitung" :busy="busy.has(b.id)"
                         @fertig="fertig" @bon="bon" @storno="storno" />
            </TransitionGroup>
          </section>
        </template>
        <section v-else aria-labelledby="h-offen" class="ausgabe-sec">
          <h2 id="h-offen" class="sec-title">Bestellt <span class="badge">{{ offeneBestellungen.length }}</span></h2>
          <div v-if="!offeneBestellungen.length" class="empty">Keine offenen Bestellungen</div>
          <TransitionGroup tag="div" name="list" class="order-grid">
            <OrderCard v-for="b in offeneBestellungen" :key="b.id" :b="b" phase="offen" :busy="busy.has(b.id)"
                       @abgeholt="abgeholt" @bon="bon" @storno="storno" />
          </TransitionGroup>
        </section>
      </div>

      <section aria-labelledby="h-abgeholt" class="abgeholt">
        <h2 id="h-abgeholt" class="sec-title">Zuletzt abgeholt</h2>
        <div class="card" style="padding: 6px 14px">
          <div v-if="!abgeholteBestellungen.length" class="muted" style="padding: 12px 0">Noch nichts abgeholt.</div>
          <div v-for="b in abgeholteBestellungen.slice(0, maxAbgeholt)" :key="b.id" class="done-row">
            <div>
              <div class="row" style="gap: 8px">
                <strong>#{{ b.id }}</strong>
                <span v-if="karteName(b.karte)" class="badge">{{ karteName(b.karte) }}</span>
                <span class="muted num" style="font-size: .85rem">{{ uhrzeit(b.zeitpunkt_abgeholt) }}</span>
              </div>
              <BestellPositionen :produkte="b.produkte" class="text-2 done-items" />
            </div>
            <div class="row" style="gap: 6px; flex-wrap: nowrap">
              <button class="btn btn-sm" :disabled="busy.has(b.id)" @click="zurueck(b)">Zurück</button>
              <button class="btn btn-sm btn-icon btn-danger" aria-label="Stornieren" @click="storno(b)"><Icon name="x" :size="16" /></button>
            </div>
          </div>
          <div v-if="abgeholteBestellungen.length > 8" class="row" style="padding: 10px 0">
            <button v-if="maxAbgeholt < abgeholteBestellungen.length" class="btn btn-sm" @click="maxAbgeholt += 10">Mehr anzeigen</button>
            <button v-if="maxAbgeholt > 8" class="btn btn-sm btn-ghost" @click="maxAbgeholt = 8">Weniger</button>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<style>
.ausgabe { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 24px; align-items: start; }
@media (max-width: 1000px) { .ausgabe { grid-template-columns: minmax(0, 1fr); } }
.ausgabe-person { margin-bottom: 16px; max-width: 640px; }
.ausgabe-sec + .ausgabe-sec { margin-top: 28px; }
.sec-title { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.produktion { gap: 6px; }
.prod-badge { font-size: .95rem; padding: 4px 12px; }
.empty-sm { padding: 18px 16px; }

.order-grid { position: relative; display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 14px; }

.done-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.done-row:last-of-type { border-bottom: 0; }
.done-items { font-size: .9rem; }
</style>
