// Zoom pro Gerät: ganze Seite (A−/A+ in der Kopfzeile) und – getrennt davon – die Produktkacheln
// an der Kasse. Tablets merken sich das im Browser. Der Kiosk-Browser am Kassen-Rechner (localhost)
// startet bei jedem Hochfahren mit leerem Profil – dort wird es deshalb auf dem Server gespeichert.

import { ref, watch } from 'vue'
import api from './api.js'
import { state } from './store.js'
import { showError } from './ui.js'

export const STUFEN = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]
export const istKiosk = ['localhost', '127.0.0.1', '[::1]'].indexOf(location.hostname) >= 0

function naechsteStufe(z) {
  return STUFEN.reduce((best, s) => (Math.abs(s - z) < Math.abs(best - z) ? s : best), 1)
}

/** Ein Zoom-Wert: lokal gemerkt bzw. am Kiosk in der Server-Einstellung `einstellung` */
function geraeteWert(speicherKey, einstellung) {
  let start = 1
  if (!istKiosk) {
    try {
      const v = parseFloat(localStorage.getItem(speicherKey))
      if (isFinite(v)) start = naechsteStufe(v)
    } catch { /* privat-Modus */ }
  }
  const wert = ref(start)
  if (istKiosk) {
    watch(() => state.einstellungen[einstellung], (z) => { if (typeof z === 'number') wert.value = naechsteStufe(z) }, { immediate: true })
  }
  async function setzen(z) {
    wert.value = naechsteStufe(z)
    if (istKiosk) {
      try { await api.setEinstellungen({ [einstellung]: wert.value }) } catch (e) { showError(e) }
    } else {
      try { localStorage.setItem(speicherKey, String(wert.value)) } catch { /* privat-Modus */ }
    }
  }
  function schritt(richtung) {
    const i = STUFEN.indexOf(naechsteStufe(wert.value))
    const j = Math.min(STUFEN.length - 1, Math.max(0, i + richtung))
    if (j !== i) setzen(STUFEN[j])
  }
  return { wert, setzen, schritt }
}

// ---- ganze Seite ----
const seite = geraeteWert('kasse-zoom', 'kiosk_zoom')
export const zoom = seite.wert
export const zoomSetzen = seite.setzen
export const zoomSchritt = seite.schritt

// ---- nur die Produktkacheln an der Kasse ----
const kacheln = geraeteWert('kasse-kacheln', 'kiosk_kacheln')
export const kachelZoom = kacheln.wert
export const kachelSetzen = kacheln.setzen
export const kachelSchritt = kacheln.schritt

function anwenden() {
  const el = document.documentElement
  const z = zoom.value
  el.style.zoom = z === 1 ? '' : String(z)
  // 100vh wächst bei CSS-zoom mit – die echte Fensterhöhe in Seiten-Pixeln geht immer
  el.style.setProperty('--vh100', `${window.innerHeight / z}px`)
}

export function zoomStarten() {
  anwenden()
  window.addEventListener('resize', anwenden)
  watch(zoom, anwenden)
}
