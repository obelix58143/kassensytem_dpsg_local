// REST-Aufrufe. Lesen passiert über den WebSocket (store.js), hier nur Änderungen.

const TIMEOUT_MS = 8000

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.status = status
  }
}

async function call(method, path, body) {
  // AbortController gibt es erst ab Chrome 66 – ohne ihn läuft der Timeout trotzdem
  const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      if (ctrl) ctrl.abort()
      reject(new ApiError('Zeitüberschreitung – Server antwortet nicht'))
    }, TIMEOUT_MS)
  })
  let res
  try {
    res = await Promise.race([
      fetch(`/api${path}`, {
        method,
        headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctrl ? ctrl.signal : undefined
      }),
      timeout
    ])
  } catch (e) {
    throw e instanceof ApiError ? e : new ApiError('Server nicht erreichbar')
  } finally {
    clearTimeout(timer)
  }
  let data = null
  try { data = await res.json() } catch { /* kein JSON */ }
  if (!res.ok) throw new ApiError(data?.error || `Fehler ${res.status}`, res.status)
  return data
}

// crypto.randomUUID gibt es nur über HTTPS/localhost – im LAN per http nicht.
export function newClientRef() {
  const c = window.crypto
  if (c && c.randomUUID) return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && c.getRandomValues) c.getRandomValues(bytes)
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  let s = ''
  for (let i = 0; i < 16; i++) s += ('0' + bytes[i].toString(16)).slice(-2)
  return s
}

export default {
  addBestellung: (b) => call('POST', '/bestellungen', b),
  setStatus: (id, status, person) => call('PUT', `/bestellungen/${id}/status`, person ? { status, person } : { status }),
  storno: (id) => call('DELETE', `/bestellungen/${id}`),
  bonNachdrucken: (id) => call('POST', `/bestellungen/${id}/bon`),
  nummerDrucken: (id) => call('POST', `/bestellungen/${id}/nummer`),
  letzteNummerDrucken: () => call('POST', '/drucker/letzte-nummer'),
  system: () => call('GET', '/system'),
  druckerStatus: () => call('GET', '/drucker'),
  druckerTest: () => call('POST', '/drucker/test'),
  logoLoeschen: () => call('DELETE', '/drucker/logo'),
  sicherungen: () => call('GET', '/sicherungen'),
  sicherungJetzt: () => call('POST', '/sicherungen'),
  /** Bilddatei roh hochladen (kein JSON) */
  async logoHochladen(datei) {
    const res = await fetch('/api/drucker/logo', { method: 'PUT', body: datei, headers: { 'Content-Type': datei.type || 'application/octet-stream' } })
    let data = null
    try { data = await res.json() } catch { /* leer */ }
    if (!res.ok) throw new ApiError(res.status === 413 ? 'Datei ist zu groß (max. 2 MB)' : (data && data.error) || `Fehler ${res.status}`, res.status)
    return data
  },

  createProdukt: (p = {}) => call('POST', '/produkte', p),
  updateProdukt: (id, p) => call('PUT', `/produkte/${id}`, p),
  deleteProdukt: (id) => call('DELETE', `/produkte/${id}`),

  createKarte: (k = {}) => call('POST', '/karten', k),
  updateKarte: (id, k) => call('PUT', `/karten/${id}`, k),
  deleteKarte: (id) => call('DELETE', `/karten/${id}`),

  setEinstellungen: (e) => call('PUT', '/einstellungen', e),
  hardReset: () => call('POST', '/reset', { bestaetigung: 'RESET' })
}
