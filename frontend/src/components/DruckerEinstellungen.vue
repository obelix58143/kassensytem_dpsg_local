<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api.js'
import { state } from '../store.js'
import { showError, toast } from '../ui.js'

const FELDER = ['drucker_verbindung', 'drucker_geraet', 'drucker_host', 'drucker_port', 'bon_breite_mm',
  'bon_kopf', 'bon_fuss', 'bon_logo', 'bon_positionen', 'bon_karte', 'bon_sprueche', 'bon_gewinn_alle', 'bon_gewinn_text']

// Entwurf: Live-Updates überschreiben nichts, was gerade bearbeitet wird
const entwurf = reactive({})
const wert = (k) => (k in entwurf ? entwurf[k] : state.einstellungen[k])
const setze = (k, v) => { entwurf[k] = v }
const geaendert = computed(() => Object.keys(entwurf).length > 0)
const status = ref(null)
const busy = ref(false)

async function pruefen() {
  try { status.value = await api.druckerStatus() } catch (e) { showError(e) }
}

async function setAktiv(aktiv) {
  try {
    await api.setEinstellungen({ drucker_aktiv: aktiv })
    toast(aktiv ? 'Bondrucker eingeschaltet' : 'Bondrucker ausgeschaltet – es wird nichts gedruckt', 'ok')
    pruefen()
  } catch (e) { showError(e) }
}

async function speichern() {
  const daten = {}
  for (const k of Object.keys(entwurf)) {
    let v = entwurf[k]
    if (k === 'drucker_port' || k === 'bon_breite_mm' || k === 'bon_gewinn_alle') v = parseInt(v, 10) || 0
    daten[k] = v
  }
  busy.value = true
  try {
    await api.setEinstellungen(daten)
    for (const k of Object.keys(entwurf)) delete entwurf[k]
    toast('Druckereinstellungen gespeichert', 'ok')
    pruefen()
  } catch (e) { showError(e) } finally { busy.value = false }
}

async function testdruck() {
  busy.value = true
  try {
    const r = await api.druckerTest()
    if (r.gedruckt === null) toast('Drucker ist ausgeschaltet', 'warn')
    else toast(r.gedruckt ? 'Testbon gedruckt' : 'Testdruck fehlgeschlagen – siehe Status', r.gedruckt ? 'ok' : 'warn')
    pruefen()
  } catch (e) { showError(e) } finally { busy.value = false }
}

onMounted(pruefen)
defineExpose({ FELDER })
</script>

<template>
  <section class="card drucker">
    <div class="card-head">
      <h2>Bondrucker</h2>
      <label class="switch">
        <input type="checkbox" :checked="state.einstellungen.drucker_aktiv" @change="setAktiv($event.target.checked)">
        {{ state.einstellungen.drucker_aktiv ? 'An' : 'Aus' }}
      </label>
    </div>

    <div class="row status-zeile">
      <span>Status:</span>
      <span v-if="!status" class="badge">?</span>
      <span v-else-if="!status.aktiv" class="badge">ausgeschaltet</span>
      <span v-else class="badge" :class="status.verbunden ? 'badge-ok' : 'badge-danger'">
        {{ status.verbunden ? 'verbunden' : 'nicht erreichbar' }} ({{ status.ziel }})
      </span>
      <span v-if="status && status.fehler && status.aktiv" class="muted" style="font-size: .85rem">Letzter Fehler: {{ status.fehler }}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" @click="pruefen">Prüfen</button>
      <button class="btn btn-sm" :disabled="busy || !state.einstellungen.drucker_aktiv" @click="testdruck">Testdruck</button>
    </div>

    <fieldset :disabled="!state.einstellungen.drucker_aktiv" class="drucker-form">
      <div class="grid2">
        <label class="field">Verbindung
          <select :value="wert('drucker_verbindung')" @change="setze('drucker_verbindung', $event.target.value)">
            <option value="usb">USB / Gerätedatei</option>
            <option value="netzwerk">Netzwerk (LAN/WLAN, Port 9100)</option>
          </select>
        </label>
        <label v-if="wert('drucker_verbindung') === 'usb'" class="field">Gerät
          <input :value="wert('drucker_geraet')" placeholder="/dev/usb/lp0" @input="setze('drucker_geraet', $event.target.value)">
        </label>
        <div v-else class="grid2 inner">
          <label class="field">IP-Adresse / Name
            <input :value="wert('drucker_host')" placeholder="192.168.1.50" @input="setze('drucker_host', $event.target.value)">
          </label>
          <label class="field">Port
            <input type="number" :value="wert('drucker_port')" min="1" max="65535" @input="setze('drucker_port', $event.target.value)">
          </label>
        </div>
        <label class="field">Papierbreite
          <select :value="wert('bon_breite_mm')" @change="setze('bon_breite_mm', parseInt($event.target.value, 10))">
            <option :value="58">58 mm</option>
            <option :value="80">80 mm</option>
          </select>
        </label>
        <label class="field">Jede N-te Bestellung gewinnt (0 = aus)
          <input type="number" min="0" :value="wert('bon_gewinn_alle')" @input="setze('bon_gewinn_alle', $event.target.value)">
        </label>
      </div>

      <label class="field">Kopfzeile auf dem Bon
        <textarea :value="wert('bon_kopf')" maxlength="300" rows="2" @input="setze('bon_kopf', $event.target.value)"></textarea>
      </label>
      <label class="field">Fußzeile (z.B. Webseite)
        <textarea :value="wert('bon_fuss')" maxlength="300" rows="2" @input="setze('bon_fuss', $event.target.value)"></textarea>
      </label>
      <label v-if="Number(wert('bon_gewinn_alle')) > 0" class="field">Gewinn-Text ({n} = Bestellnummer)
        <input :value="wert('bon_gewinn_text')" maxlength="200" @input="setze('bon_gewinn_text', $event.target.value)">
      </label>

      <div class="row schalter">
        <label class="switch"><input type="checkbox" :checked="wert('bon_positionen')" @change="setze('bon_positionen', $event.target.checked)"> Bestellte Produkte</label>
        <label class="switch"><input type="checkbox" :checked="wert('bon_karte')" @change="setze('bon_karte', $event.target.checked)"> Karte</label>
        <label class="switch"><input type="checkbox" :checked="wert('bon_sprueche')" @change="setze('bon_sprueche', $event.target.checked)"> Zufälliger Spruch</label>
        <label class="switch"><input type="checkbox" :checked="wert('bon_logo')" @change="setze('bon_logo', $event.target.checked)"> Logo</label>
      </div>
      <p class="muted hinweis">
        Logo: Datei <code>printer_files/logo.png</code> auf dem Server ablegen (max. 384 px breit bei 58 mm, 576 px bei 80 mm).
        Sprüche: <code>printer_files/sprueche.json</code>.
      </p>

      <div class="row">
        <button class="btn btn-primary" :disabled="!geaendert || busy" @click="speichern">Speichern</button>
        <button class="btn btn-ghost" :disabled="!geaendert" @click="Object.keys(entwurf).forEach(k => delete entwurf[k])">Verwerfen</button>
      </div>
    </fieldset>
  </section>
</template>

<style>
.drucker .status-zeile { margin-bottom: 16px; }
.drucker-form { border: 0; padding: 0; margin: 0; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.drucker-form:disabled { opacity: .5; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }
.grid2.inner { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); }
.drucker .schalter { gap: 18px; }
.drucker .hinweis { font-size: .85rem; }
.drucker code { font-size: .85em; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
.no-flexgap .drucker-form > * + * { margin-top: 14px; }
@supports not (display: grid) {
  html .grid2 { display: flex; flex-wrap: wrap; }
  html .grid2 > * { flex: 1 1 220px; margin: 0 14px 14px 0; }
}
</style>
