// Zoom pro Gerät (A− / A+ in der Kopfzeile).
// Tablets merken ihn im Browser. Der Kiosk-Browser am Kassen-Rechner (localhost) startet bei jedem
// Hochfahren mit leerem Profil – dort wird der Zoom deshalb auf dem Server gespeichert.

import { ref, watch } from 'vue'
import api from './api.js'
import { state } from './store.js'
import { showError } from './ui.js'

export const STUFEN = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]
const KEY = 'kasse-zoom'
export const istKiosk = ['localhost', '127.0.0.1', '[::1]'].indexOf(location.hostname) >= 0

function naechsteStufe(z) {
  return STUFEN.reduce((best, s) => (Math.abs(s - z) < Math.abs(best - z) ? s : best), 1)
}

function gespeichert() {
  try {
    const v = parseFloat(localStorage.getItem(KEY))
    return isFinite(v) ? naechsteStufe(v) : 1
  } catch { return 1 }
}

export const zoom = ref(istKiosk ? 1 : gespeichert())

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
  if (istKiosk) {
    watch(() => state.einstellungen.kiosk_zoom, (z) => { if (typeof z === 'number') zoom.value = naechsteStufe(z) }, { immediate: true })
  }
}

export async function zoomSetzen(z) {
  zoom.value = naechsteStufe(z)
  if (istKiosk) {
    try { await api.setEinstellungen({ kiosk_zoom: zoom.value }) } catch (e) { showError(e) }
  } else {
    try { localStorage.setItem(KEY, String(zoom.value)) } catch { /* privat-Modus */ }
  }
}

export function zoomSchritt(richtung) {
  const i = STUFEN.indexOf(naechsteStufe(zoom.value))
  const j = Math.min(STUFEN.length - 1, Math.max(0, i + richtung))
  if (j !== i) zoomSetzen(STUFEN[j])
}
