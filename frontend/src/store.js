// Zentraler Zustand, live per WebSocket vom Server.
// Der Server schickt bei jeder Änderung den kompletten Zustand – damit können
// Geräte nie auseinanderlaufen, auch nicht nach einem Verbindungsabbruch.

import { reactive, computed } from 'vue'

const WATCHDOG_MS = 40000 // Server pingt alle 15 s; danach gilt die Verbindung als tot
const MAX_BACKOFF_MS = 5000

export const state = reactive({
  produkte: [],
  karten: [],
  bestellungen: [],
  einstellungen: { titel: 'Kasse', bereit_aktiv: false, drucker_aktiv: true, name_kasse: true, name_ausgabe: true },
  loaded: false,
  connected: false,
  clockOffset: 0, // Serverzeit - Gerätezeit (Tablets haben oft falsche Uhren)
  now: Date.now()
})

export const produktById = computed(() => new Map(state.produkte.map(p => [p.id, p])))
export const karteById = computed(() => new Map(state.karten.map(k => [k.id, k])))
export const aktiveProdukte = computed(() => state.produkte.filter(p => p.aktiv))
// Normale Produkte vs. Pfandrückgaben (typ 'pfand': Geld zurück an den Kunden)
export const verkaufsProdukte = computed(() => aktiveProdukte.value.filter(p => p.typ !== 'pfand'))
// Kundendisplay: einzelne Produkte lassen sich dort ausblenden (z.B. Kombi nur auf Nachfrage)
export const displayProdukte = computed(() => verkaufsProdukte.value.filter(p => p.auf_display !== false))
export const pfandProdukte = computed(() => aktiveProdukte.value.filter(p => p.typ === 'pfand'))
export const istPfand = (produktId) => produktById.value.get(produktId)?.typ === 'pfand'

/** Alles, was noch nicht abgeholt ist (bestellt + bereit) */
export const offeneBestellungen = computed(() =>
  state.bestellungen.filter(b => b.status !== 'abgeholt').sort((a, b) => a.id - b.id)
)
export const inZubereitung = computed(() => offeneBestellungen.value.filter(b => b.status === 'bestellt'))
export const abholbereit = computed(() =>
  offeneBestellungen.value
    .filter(b => b.status === 'bereit')
    .sort((a, b) => (a.zeitpunkt_bereit || '').localeCompare(b.zeitpunkt_bereit || '') || a.id - b.id)
)
export const abgeholteBestellungen = computed(() =>
  state.bestellungen
    .filter(b => b.status === 'abgeholt' && !b.nur_pfand)
    .sort((a, b) => (b.zeitpunkt_abgeholt || '').localeCompare(a.zeitpunkt_abgeholt || '') || b.id - a.id)
)

export function serverNow() {
  return state.now + state.clockOffset
}

function applyState(data) {
  state.produkte = data.produkte
  state.karten = data.karten
  state.bestellungen = data.bestellungen
  if (data.einstellungen) state.einstellungen = data.einstellungen
  state.clockOffset = Date.parse(data.server_time) - Date.now()
  state.loaded = true
}

let socket = null
let attempt = 0
let watchdog = null
let reconnectTimer = null

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws`
}

function dropSocket() {
  clearTimeout(watchdog)
  if (socket) {
    const old = socket
    socket = null
    old.onopen = old.onmessage = old.onclose = old.onerror = null
    try { old.close() } catch { /* egal */ }
  }
  state.connected = false
}

function armWatchdog() {
  clearTimeout(watchdog)
  watchdog = setTimeout(() => {
    // Keine Nachricht (auch kein Ping) mehr: Verbindung hängt, neu aufbauen
    dropSocket()
    scheduleReconnect(0)
  }, WATCHDOG_MS)
}

function scheduleReconnect(delay) {
  clearTimeout(reconnectTimer)
  const wait = delay ?? Math.min(MAX_BACKOFF_MS, 300 * 2 ** attempt)
  attempt++
  reconnectTimer = setTimeout(connect, wait)
}

export function connect() {
  clearTimeout(reconnectTimer)
  if (socket) return
  const ws = new WebSocket(wsUrl())
  socket = ws
  ws.onopen = () => {
    attempt = 0
    state.connected = true
    armWatchdog()
  }
  ws.onmessage = (e) => {
    armWatchdog()
    const msg = JSON.parse(e.data)
    if (msg.type === 'state') applyState(msg.data)
  }
  ws.onclose = () => {
    if (socket !== ws) return
    dropSocket()
    scheduleReconnect()
  }
  ws.onerror = () => ws.close()
}

// Tablet aufgeweckt / WLAN wieder da: nicht auf den Backoff warten
function reconnectNow() {
  if (!state.connected) {
    dropSocket()
    attempt = 0
    connect()
  }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') reconnectNow()
})
window.addEventListener('online', reconnectNow)

setInterval(() => { state.now = Date.now() }, 1000)
