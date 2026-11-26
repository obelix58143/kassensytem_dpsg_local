<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import api from '../api.js'
import { offeneBestellungen, serverNow, state } from '../store.js'
import { tagKey } from '../stats.js'
import { euro } from '../format.js'

const heute = computed(() => {
  const k = tagKey(serverNow())
  const b = state.bestellungen.filter(x => !x.nur_pfand && tagKey(Date.parse(x.zeitpunkt_annahme)) === k)
  return {
    anzahl: b.length,
    umsatz: b.reduce((s, x) => s + (x.eigenbedarf ? 0 : x.preis_cent), 0)
  }
})

// Adresse des Kassen-Rechners zum Abtippen auf den Tablets
const adressen = ref(null) // null = noch unbekannt
const hostname = ref('')
async function ladeAdressen() {
  try {
    const r = await api.system()
    adressen.value = r.adressen || []
    hostname.value = r.hostname || ''
  } catch { /* offline – alter Stand bleibt */ }
}
let timer
onMounted(() => { ladeAdressen(); timer = setInterval(ladeAdressen, 30000) })
onBeforeUnmount(() => clearInterval(timer))

const stationen = [
  { to: '/kasse', title: 'Kasse', text: 'Bestellungen aufnehmen, Rückgeld berechnen, Bon drucken', icon: '€' },
  { to: '/ausgabe', title: 'Ausgabe', text: 'Offene Bestellungen sehen und als abgeholt markieren', icon: '✓' },
  { to: '/front', title: 'Kundendisplay', text: 'Vollbild für den Bildschirm am Stand (Doppelklick = Vollbild)', icon: '▣' },
  { to: '/statistik', title: 'Statistik', text: 'Umsatz, Produkte, Wartezeiten – live', icon: '↗' },
  { to: '/settings', title: 'Einstellungen', text: 'Produkte, Preise, Karten, Export, Reset', icon: '⚙' }
]
</script>

<template>
  <main class="page">
    <div class="home-hero">
      <div>
        <h1>Gut Pfad! ⚜</h1>
        <p class="text-2">Welche Station ist dieses Gerät?</p>
      </div>
      <div class="row home-kpis">
        <div class="home-kpi"><span class="muted">Heute</span><strong>{{ euro(heute.umsatz) }}</strong></div>
        <div class="home-kpi"><span class="muted">Bestellungen</span><strong>{{ heute.anzahl }}</strong></div>
        <div class="home-kpi"><span class="muted">Offen</span><strong>{{ offeneBestellungen.length }}</strong></div>
      </div>
    </div>
    <div v-if="adressen" class="card adresse" :class="{ fehlt: !adressen.length }">
      <span class="adresse-label">Tablets verbinden – im Browser eintippen:</span>
      <template v-if="adressen.length">
        <strong v-for="ip in adressen.slice(0, 2)" :key="ip" class="adresse-ip num">http://{{ ip }}</strong>
        <span v-if="hostname" class="muted">oder http://{{ hostname }}.local</span>
      </template>
      <strong v-else class="adresse-ip">Kein Netzwerk – WLAN / Router prüfen</strong>
    </div>
    <div class="stationen">
      <router-link v-for="s in stationen" :key="s.to" :to="s.to" class="station card">
        <span class="station-icon" aria-hidden="true">{{ s.icon }}</span>
        <span class="station-title">{{ s.title }}</span>
        <span class="text-2">{{ s.text }}</span>
      </router-link>
    </div>
  </main>
</template>

<style>
.home-hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; flex-wrap: wrap; margin: 12px 0 24px; }
.home-hero h1 { font-size: 2.2rem; }
.home-kpis { gap: 28px; }
.home-kpi { display: flex; flex-direction: column; }
.home-kpi span { font-size: .8rem; font-weight: 600; }
.home-kpi strong { font-size: 1.6rem; }
.adresse { display: flex; align-items: baseline; gap: 6px 16px; flex-wrap: wrap; padding: 14px 20px; margin-bottom: 18px; border-left: 6px solid var(--primary); }
.adresse.fehlt { border-left-color: var(--danger); }
.adresse-label { font-weight: 600; color: var(--text-2); }
.adresse-ip { font-size: 1.6rem; font-weight: 800; letter-spacing: .01em; color: var(--primary); }
.adresse.fehlt .adresse-ip { color: var(--danger); font-size: 1.2rem; }
.stationen { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.station { display: flex; flex-direction: column; gap: 6px; text-decoration: none; padding: 22px; transition: transform .08s, border-color .12s; }
.station:hover { border-color: var(--primary); transform: translateY(-2px); }
.station-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: var(--primary-soft); color: var(--primary); font-size: 1.5rem; font-weight: 800; margin-bottom: 6px; }
.station-title { font-weight: 800; font-size: 1.2rem; }
</style>
