<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api.js'
import { state } from '../store.js'
import { euroInput, parseEuro } from '../format.js'
import { confirmDialog, showError, toast } from '../ui.js'
import Icon from '../components/Icon.vue'
import DruckerEinstellungen from '../components/DruckerEinstellungen.vue'

// Lokale Entwürfe: Live-Updates vom Server überschreiben nichts, was gerade getippt wird
const pDraft = reactive({})
const kDraft = reactive({})

// Zur Fehlersuche auf alten Tablets: welcher Browser, welche Fallbacks greifen
const geraet = (() => {
  const m = navigator.userAgent.match(/Chrome\/(\d+)/)
  const android = navigator.userAgent.match(/Android ([\d.]+)/)
  return {
    browser: m ? `Chrome/WebView ${m[1]}` : navigator.userAgent.slice(0, 60),
    android: android ? android[1] : null,
    alt: m && +m[1] < 84,
    grid: !!(window.CSS && CSS.supports && CSS.supports('display', 'grid')),
    flexgap: !document.documentElement.classList.contains('no-flexgap')
  }
})()

const verkauft = computed(() => {
  const m = new Map()
  for (const b of state.bestellungen) for (const p of b.produkte) m.set(p.id, (m.get(p.id) || 0) + p.anzahl)
  return m
})
const produkte = computed(() => [...state.produkte].sort((a, b) => (b.aktiv - a.aktiv) || a.sortierung - b.sortierung || a.id - b.id))

function pFeld(p, key) {
  const d = pDraft[p.id]
  if (d && key in d) return d[key]
  if (key === 'preis') return euroInput(p.preis_cent)
  if (key === 'pfand') return euroInput(p.pfand_cent)
  return p[key]
}
function pSet(p, key, value) {
  pDraft[p.id] = { ...(pDraft[p.id] || {}), [key]: value }
}
/** Fehler eines einzelnen Feldes (wird statt des Labels angezeigt) */
function feldFehler(p, key) {
  const d = pDraft[p.id] || {}
  if (!(key in d)) return null
  if (key === 'name' && !d.name.trim()) return 'Name fehlt'
  if ((key === 'preis' || key === 'pfand') && parseEuro(d[key]) == null) return 'ungültig'
  return null
}
function pFehler(p) {
  const d = pDraft[p.id] || {}
  if ('name' in d && !d.name.trim()) return 'Name fehlt'
  if ('preis' in d && parseEuro(d.preis) == null) return 'Preis ungültig'
  if ('pfand' in d && parseEuro(d.pfand) == null) return 'Pfand ungültig'
  return null
}

async function pSpeichern(p) {
  const d = pDraft[p.id]
  if (!d || pFehler(p)) return
  const body = {}
  if ('name' in d) body.name = d.name
  if ('beschreibung' in d) body.beschreibung = d.beschreibung
  if ('preis' in d) body.preis_cent = parseEuro(d.preis)
  if ('pfand' in d) body.pfand_cent = parseEuro(d.pfand)
  try {
    await api.updateProdukt(p.id, body)
    delete pDraft[p.id]
    toast(`„${body.name ?? p.name}" gespeichert`, 'ok')
  } catch (e) { showError(e) }
}

async function pAktiv(p, aktiv) {
  try { await api.updateProdukt(p.id, { aktiv }) } catch (e) { showError(e) }
}

async function pVerschieben(p, dir) {
  const list = produkte.value.filter(x => x.aktiv)
  const i = list.findIndex(x => x.id === p.id)
  const j = i + dir
  if (i < 0 || j < 0 || j >= list.length) return
  const neu = [...list]
  ;[neu[i], neu[j]] = [neu[j], neu[i]]
  try {
    await Promise.all(neu.map((x, idx) => (x.sortierung !== idx + 1 ? api.updateProdukt(x.id, { sortierung: idx + 1 }) : null)))
  } catch (e) { showError(e) }
}

async function pNeu(typ = 'normal') {
  const daten = typ === 'pfand'
    ? { typ, name: 'Pfand zurück', pfand_cent: 200 }
    : { name: 'Neues Produkt' }
  try { await api.createProdukt(daten) } catch (e) { showError(e) }
}

// ---------- Ablauf ----------
async function setBereit(aktiv) {
  try {
    await api.setEinstellungen({ bereit_aktiv: aktiv })
    toast(aktiv ? '„Abholbereit" ist eingeschaltet' : '„Abholbereit" ist ausgeschaltet', 'ok')
  } catch (e) { showError(e) }
}

async function pLoeschen(p) {
  const n = verkauft.value.get(p.id) || 0
  const ok = await confirmDialog({
    title: `„${p.name}" löschen?`,
    text: n ? `Wurde schon ${n}× verkauft – wird deshalb nur deaktiviert, damit die Statistik stimmt.` : 'Wurde noch nie verkauft und wird endgültig gelöscht.',
    confirmText: n ? 'Deaktivieren' : 'Löschen',
    danger: true
  })
  if (!ok) return
  try { await api.deleteProdukt(p.id); delete pDraft[p.id] } catch (e) { showError(e) }
}

// ---------- Karten ----------
async function kNeu() {
  try { await api.createKarte({ beschreibung: `Karte ${state.karten.length + 1}` }) } catch (e) { showError(e) }
}
async function kSpeichern(k) {
  if (!(k.id in kDraft)) return
  try { await api.updateKarte(k.id, { beschreibung: kDraft[k.id] }); delete kDraft[k.id] } catch (e) { showError(e) }
}
async function kLoeschen(k) {
  if (!(await confirmDialog({ title: `Karte „${k.beschreibung}" löschen?`, confirmText: 'Löschen', danger: true }))) return
  try { await api.deleteKarte(k.id) } catch (e) { showError(e) }
}

// ---------- Sicherungen ----------
const sicherung = ref(null)
async function sicherungenLaden() {
  try { sicherung.value = await api.sicherungen() } catch (e) { showError(e) }
}
async function jetztSichern() {
  try {
    const r = await api.sicherungJetzt()
    toast(`Gesichert: ${r.datei}`, 'ok')
    sicherungenLaden()
  } catch (e) { showError(e) }
}
onMounted(sicherungenLaden)

// ---------- Allgemein ----------
const titelEntwurf = ref(null)
async function titelSpeichern() {
  if (titelEntwurf.value == null) return
  try {
    await api.setEinstellungen({ titel: titelEntwurf.value })
    titelEntwurf.value = null
    toast('Name gespeichert', 'ok')
  } catch (e) { showError(e) }
}

async function reset() {
  const ok = await confirmDialog({
    title: 'Alle Daten löschen?',
    text: 'Löscht alle Bestellungen, Produkte und Karten. Einstellungen (Name, Drucker, Logo, Sprüche) bleiben. Vorher wird automatisch eine Sicherung angelegt.',
    confirmText: 'Alles löschen',
    danger: true,
    requireText: 'RESET'
  })
  if (!ok) return
  try {
    const r = await api.hardReset()
    toast(`Zurückgesetzt. Sicherung: ${r.backup ?? '–'}`, 'ok', { timeout: 8000 })
  } catch (e) { showError(e) }
}

</script>

<template>
  <main class="page settings">
    <div class="page-head"><h1>Einstellungen</h1></div>

    <section class="card">
      <h2 style="margin-bottom: 12px">Allgemein</h2>
      <div class="row" style="align-items: flex-end; margin-bottom: 16px">
        <label class="field" style="flex: 1; max-width: 420px">Name der Kasse (Kopfzeile &amp; Kundendisplay)
          <input :value="titelEntwurf ?? state.einstellungen.titel" maxlength="60"
                 @input="titelEntwurf = $event.target.value" @keydown.enter="titelSpeichern">
        </label>
        <button class="btn" :disabled="titelEntwurf == null || !titelEntwurf.trim()" @click="titelSpeichern">Speichern</button>
      </div>
      <label class="switch">
        <input type="checkbox" :checked="state.einstellungen.bereit_aktiv" @change="setBereit($event.target.checked)">
        Zwischenschritt „Abholbereit" verwenden
      </label>
      <p class="muted" style="font-size: .9rem; margin-top: 8px">
        Aus: <strong>bestellt → abgeholt</strong>. An: <strong>bestellt → abholbereit → abgeholt</strong> –
        die Ausgabe tippt „Fertig", das Kundendisplay zeigt die Nummer groß unter „Bitte abholen".
      </p>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Produkte</h2>
        <div class="row" style="gap: 8px">
          <button class="btn btn-sm" @click="pNeu('pfand')">+ Pfandrückgabe</button>
          <button class="btn btn-primary btn-sm" @click="pNeu()">+ Produkt</button>
        </div>
      </div>
      <div v-if="!produkte.length" class="empty">Noch keine Produkte.</div>
      <div class="plist">
        <div v-for="(p, i) in produkte" :key="p.id" class="pitem" :class="{ inaktiv: !p.aktiv, dirty: pDraft[p.id], 'typ-pfand': p.typ === 'pfand' }">
          <div class="psort">
            <button class="btn btn-ghost btn-icon btn-sm" :disabled="!p.aktiv || i === 0" aria-label="Nach oben" @click="pVerschieben(p, -1)">▲</button>
            <button class="btn btn-ghost btn-icon btn-sm" :disabled="!p.aktiv || !produkte[i + 1]?.aktiv" aria-label="Nach unten" @click="pVerschieben(p, 1)">▼</button>
          </div>
          <label class="field pname" :class="{ invalid: feldFehler(p, 'name') }">
            <span class="field-label">{{ feldFehler(p, 'name') || 'Name' }}</span>
            <input :value="pFeld(p, 'name')" maxlength="200" :aria-invalid="!!feldFehler(p, 'name')" @input="pSet(p, 'name', $event.target.value)" @keydown.enter="pSpeichern(p)">
          </label>
          <label class="field pdesc" :class="{ invalid: feldFehler(p, 'beschreibung') }">
            <span class="field-label">{{ feldFehler(p, 'beschreibung') || 'Beschreibung' }}</span>
            <input :value="pFeld(p, 'beschreibung')" maxlength="1000" :aria-invalid="!!feldFehler(p, 'beschreibung')" @input="pSet(p, 'beschreibung', $event.target.value)" @keydown.enter="pSpeichern(p)">
          </label>
          <label v-if="p.typ === 'pfand'" class="field pnum">
            <span class="field-label">Typ</span>
            <input value="Pfand" disabled>
          </label>
          <label v-else class="field pnum" :class="{ invalid: feldFehler(p, 'preis') }">
            <span class="field-label">{{ feldFehler(p, 'preis') || 'Preis €' }}</span>
            <input :value="pFeld(p, 'preis')" inputmode="decimal" :aria-invalid="!!feldFehler(p, 'preis')" @input="pSet(p, 'preis', $event.target.value)" @keydown.enter="pSpeichern(p)">
          </label>
          <label class="field pnum" :class="{ invalid: feldFehler(p, 'pfand') }">
            <span class="field-label">{{ feldFehler(p, 'pfand') || (p.typ === 'pfand' ? 'Zurück €' : 'Pfand €') }}</span>
            <input :value="pFeld(p, 'pfand')" inputmode="decimal" :aria-invalid="!!feldFehler(p, 'pfand')" @input="pSet(p, 'pfand', $event.target.value)" @keydown.enter="pSpeichern(p)">
          </label>
          <div class="pmeta">
            <label class="switch" :title="p.aktiv ? 'An der Kasse sichtbar' : 'Ausgeblendet'">
              <input type="checkbox" :checked="p.aktiv" @change="pAktiv(p, $event.target.checked)">
              <span class="hide-sm">{{ p.aktiv ? 'Aktiv' : 'Aus' }}</span>
            </label>
            <span class="muted num" style="font-size: .85rem">{{ verkauft.get(p.id) || 0 }}× {{ p.typ === 'pfand' ? 'zurück' : 'verkauft' }}</span>
          </div>
          <div class="pactions">
            <button class="btn btn-sm btn-primary" :disabled="!pDraft[p.id] || !!pFehler(p)" @click="pSpeichern(p)">Speichern</button>
            <button class="btn btn-sm btn-icon" :disabled="!pDraft[p.id]" title="Änderungen verwerfen" aria-label="Änderungen verwerfen" @click="delete pDraft[p.id]"><Icon name="undo" :size="16" /></button>
            <button class="btn btn-sm btn-icon btn-danger" aria-label="Löschen" @click="pLoeschen(p)"><Icon name="x" :size="16" /></button>
          </div>
        </div>
      </div>
      <p class="muted" style="font-size: .85rem; margin-top: 10px">
        Preisänderungen gelten nur für neue Bestellungen – bisherige Umsätze bleiben korrekt.
      </p>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>Karten</h2>
        <button class="btn btn-primary btn-sm" @click="kNeu">+ Karte</button>
      </div>
      <p class="muted" style="font-size: .9rem; margin-bottom: 12px">Optionale Marken (z.B. Tischnummer), die der Kunde bis zur Abholung bekommt.</p>
      <div class="klist">
        <div v-for="k in state.karten" :key="k.id" class="kitem">
          <input :value="k.id in kDraft ? kDraft[k.id] : k.beschreibung" maxlength="200" aria-label="Bezeichnung"
                 @input="kDraft[k.id] = $event.target.value" @keydown.enter="kSpeichern(k)" @blur="kSpeichern(k)">
          <span class="badge" :class="k.inUse ? 'badge-warn' : 'badge-ok'">{{ k.inUse ? 'in Benutzung' : 'frei' }}</span>
          <button class="btn btn-sm btn-icon btn-danger" :disabled="k.inUse" aria-label="Löschen" @click="kLoeschen(k)"><Icon name="x" :size="16" /></button>
        </div>
      </div>
    </section>

    <DruckerEinstellungen />

    <section class="card">
      <h2 style="margin-bottom: 12px">Daten &amp; Sicherungen</h2>
      <p class="text-2" style="margin-bottom: 10px">
        Der Server sichert automatisch alle 5 Minuten (wenn sich etwas geändert hat), beim Start und beim Beenden.
        <template v-if="sicherung">
          <br>Letzte Sicherung:
          <strong v-if="sicherung.letzte.zeit">{{ new Date(sicherung.letzte.zeit).toLocaleString('de-DE') }}</strong>
          <span v-else>–</span>
          <span v-if="sicherung.letzte.fehler" class="badge badge-danger">Fehler: {{ sicherung.letzte.fehler }}</span>
          · {{ sicherung.dateien.length }} Sicherungen in <code>{{ sicherung.ordner }}</code>
        </template>
      </p>
      <div class="row">
        <button class="btn btn-sm" @click="jetztSichern">Jetzt sichern</button>
        <a class="btn btn-sm" href="/api/sicherungen/download"><Icon name="download" :size="16" /> Datenbank herunterladen</a>
        <a class="btn btn-sm" href="/api/export.csv" download><Icon name="download" :size="16" /> Bestellungen als CSV</a>
      </div>
      <p class="muted" style="font-size: .85rem; margin-top: 12px">
        Dieses Gerät: {{ geraet.browser }}<span v-if="geraet.android"> · Android {{ geraet.android }}</span>
        · Grid {{ geraet.grid ? 'ja' : 'nein (Fallback)' }} · Flex-Abstände {{ geraet.flexgap ? 'ja' : 'nein (Fallback)' }}
      </p>
    </section>

    <section class="card danger-zone">
      <h2>Alle Daten zurücksetzen</h2>
      <p class="text-2" style="margin: 6px 0 12px">Für den Start einer neuen Veranstaltung. Es wird vorher automatisch eine Sicherung angelegt.</p>
      <button class="btn btn-danger" @click="reset">Hard Reset …</button>
    </section>
  </main>
</template>

<style>
.settings { display: flex; flex-direction: column; gap: 16px; max-width: 1200px; }
.plist { display: flex; flex-direction: column; gap: 10px; }
.pitem {
  display: grid; gap: 10px; align-items: end;
  /* feste Spaltenbreiten: beim Tippen darf sich nichts verschieben */
  grid-template-columns: 44px minmax(160px, 2fr) minmax(140px, 1.5fr) 96px 96px 120px 196px;
  padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface);
}
.pitem.dirty { border-color: var(--primary); }
.pitem.typ-pfand { border-style: dashed; }
.pitem input:disabled { background: var(--surface-2); color: var(--muted); }
.pitem.inaktiv { opacity: .6; background: var(--surface-2); }
.psort { display: flex; flex-direction: column; }
.psort .btn { min-height: 26px; height: 26px; font-size: .7rem; }
.pmeta { display: flex; flex-direction: column; gap: 4px; padding-bottom: 4px; }
.pactions { display: flex; gap: 6px; align-items: center; justify-content: flex-end; }
.pmeta .switch span { display: inline-block; min-width: 3.2em; }
.pitem .field-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pitem .field.invalid .field-label { color: var(--danger); }
.pitem .field.invalid input { border-color: var(--danger); box-shadow: 0 0 0 1px var(--danger); }
@media (max-width: 1000px) {
  .pitem { grid-template-columns: 44px 1fr 1fr; }
  .pdesc { grid-column: 2 / -1; }
  .psort { grid-row: span 3; }
  .pactions { grid-column: 2 / -1; justify-content: flex-start; }
}
.klist { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.kitem { display: flex; align-items: center; gap: 8px; }
.danger-zone { border-color: var(--danger-border); }
</style>
