<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import api from '../api.js'
import { state, offeneBestellungen, serverNow } from '../store.js'
import { getTheme, setTheme, toast } from '../ui.js'
import { STUFEN, zoom, zoomSchritt, zoomSetzen } from '../zoom.js'

const links = [
  { to: '/', label: 'Start' },
  { to: '/kasse', label: 'Kasse' },
  { to: '/ausgabe', label: 'Ausgabe' },
  { to: '/statistik', label: 'Statistik' },
  { to: '/settings', label: 'Einstellungen' },
  { to: '/front', label: 'Display' }
]

const uhr = computed(() =>
  new Date(serverNow()).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
)

// Akku des Kassen-Rechners: alle 30 s abfragen, nur anzeigen, wenn es einen gibt
const akku = ref(null)
const akkuStufe = computed(() => {
  const a = akku.value
  if (!a || a.netzteil) return 'ok'
  return a.prozent <= 15 ? 'krit' : a.prozent <= 30 ? 'warn' : 'ok'
})
const akkuTitel = computed(() => {
  const a = akku.value
  if (!a) return ''
  return `Akku der Kasse: ${a.prozent} % – ` + (a.laedt ? 'wird geladen' : a.netzteil ? 'am Netzteil' : 'läuft auf Akku')
})
let akkuTimer = null
async function akkuLaden() {
  if (document.hidden) return
  let neu
  try { neu = (await api.system()).akku } catch (e) { return }
  const alt = akku.value
  // nur bei Änderungen melden, nicht beim ersten Laden
  if (alt && neu) {
    if (alt.netzteil && !neu.netzteil) toast(`Kasse läuft auf Akku (${neu.prozent} %) – Strom prüfen!`, 'warn', { timeout: 10000 })
    else if (!neu.netzteil && alt.prozent > 15 && neu.prozent <= 15) toast(`Akku der Kasse fast leer (${neu.prozent} %) – Netzteil anstecken!`, 'error', { timeout: 15000 })
    else if (!alt.netzteil && neu.netzteil) toast('Kasse hängt wieder am Strom', 'ok')
  }
  akku.value = neu
}
onMounted(() => { akkuLaden(); akkuTimer = setInterval(akkuLaden, 30000) })
onBeforeUnmount(() => clearInterval(akkuTimer))

const theme = ref(getTheme())
const themes = { auto: 'Auto', light: 'Hell', dark: 'Dunkel' }
function nextTheme() {
  const order = ['auto', 'light', 'dark']
  theme.value = order[(order.indexOf(theme.value) + 1) % order.length]
  setTheme(theme.value)
}
</script>

<template>
  <header class="header">
    <router-link to="/" class="brand">
      <span class="lilie" aria-hidden="true">⚜</span>
      <span>{{ state.einstellungen.titel }}</span>
    </router-link>
    <nav class="nav" aria-label="Hauptnavigation">
      <router-link v-for="l in links" :key="l.to" :to="l.to" class="nav-link">
        {{ l.label }}
        <span v-if="l.to === '/ausgabe' && offeneBestellungen.length" class="nav-count">{{ offeneBestellungen.length }}</span>
      </router-link>
    </nav>
    <div class="header-right">
      <span class="zoom" role="group" aria-label="Zoom">
        <button class="btn btn-ghost btn-sm" title="Kleiner" aria-label="Kleiner" :disabled="zoom <= STUFEN[0]" @click="zoomSchritt(-1)">A−</button>
        <button class="btn btn-ghost btn-sm zoom-wert hide-sm" title="Zoom auf 100 %" @click="zoomSetzen(1)">{{ Math.round(zoom * 100) }} %</button>
        <button class="btn btn-ghost btn-sm" title="Größer" aria-label="Größer" :disabled="zoom >= STUFEN[STUFEN.length - 1]" @click="zoomSchritt(1)">A+</button>
      </span>
      <button class="btn btn-ghost btn-sm" :title="'Darstellung: ' + themes[theme]" @click="nextTheme">
        {{ theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐' }} <span class="hide-sm">{{ themes[theme] }}</span>
      </button>
      <span v-if="akku" class="status akku" :class="'akku-' + akkuStufe" :title="akkuTitel" :aria-label="akkuTitel">
        <svg class="akku-icon" viewBox="0 0 26 14" aria-hidden="true">
          <rect x="1" y="1" width="21" height="12" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/>
          <rect x="23" y="4.5" width="2" height="5" rx="1" fill="currentColor"/>
          <rect x="3" y="3" :width="Math.max(1, 17 * akku.prozent / 100)" height="8" rx="1.2" fill="currentColor"/>
        </svg>
        <span v-if="akku.netzteil" aria-hidden="true">⚡</span>{{ akku.prozent }} %
      </span>
      <span class="status" :class="state.connected ? 'is-on' : 'is-off'" :title="state.connected ? 'Live verbunden' : 'Getrennt'">
        <span class="dot" aria-hidden="true"></span>
        {{ state.connected ? 'Live' : 'Offline' }}
      </span>
      <span class="clock num">{{ uhr }}</span>
    </div>
  </header>
</template>

<style>
.header {
  position: sticky; top: 0; z-index: 40;
  display: flex; align-items: center; gap: 18px;
  padding: 8px 24px;
  padding: 8px clamp(16px, 3vw, 32px);
  background: var(--header-bg);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 8px; font-weight: 800; text-decoration: none; color: var(--primary); font-size: 1.05rem; white-space: nowrap; }
.lilie { font-size: 1.35rem; }
.nav { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none; flex: 1; }
.nav::-webkit-scrollbar { display: none; }
.nav-link {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 10px 12px; border-radius: 9px;
  text-decoration: none; font-weight: 600; color: var(--text-2);
  white-space: nowrap;
}
.nav-link:hover { background: var(--surface-2); color: var(--text); }
.nav-link.router-link-exact-active { background: var(--primary-soft); color: var(--primary); }
.nav-count { background: var(--primary); color: var(--on-primary); border-radius: 999px; font-size: .75rem; padding: 1px 7px; font-weight: 700; }
.header-right { display: flex; align-items: center; gap: 10px; }
.zoom { display: inline-flex; align-items: center; }
.zoom .btn { padding: 0 8px; font-weight: 700; }
.zoom-wert { min-width: 4.2em; font-variant-numeric: tabular-nums; color: var(--text-2); }
/* wird es eng, reichen A− / A+ (Navigation geht vor) */
@media (max-width: 1400px) { .zoom-wert { display: none; } }
.status { display: inline-flex; align-items: center; gap: 6px; font-size: .85rem; font-weight: 700; padding: 4px 10px; border-radius: 999px; }
.status.is-on { color: var(--ok); background: var(--ok-soft); }
.status.is-off { color: var(--danger); background: var(--danger-soft); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.is-on .dot { animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .35; } }
.clock { font-weight: 700; color: var(--text-2); }
.akku { gap: 5px; white-space: nowrap; }
.akku-icon { width: 24px; height: 13px; }
.akku-ok { color: var(--text-2); background: var(--surface-2); }
.akku-warn { color: var(--warn); background: var(--warn-soft); }
.akku-krit { color: var(--danger); background: var(--danger-soft); animation: pulse 1.2s ease-in-out infinite; }
@media (max-width: 720px) {
  .hide-sm, .clock { display: none; }
  .brand span:last-child { display: none; }
  .header { gap: 8px; }
}
</style>
