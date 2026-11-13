const eur = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' })
const num = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 })
const time = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit' })
const day = new Intl.DateTimeFormat('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' })

export const euro = (cent) => eur.format((cent || 0) / 100)
export const zahl = (n) => num.format(n)
export const uhrzeit = (iso) => (iso ? time.format(new Date(iso)) : '–')
export const tag = (d) => day.format(d)

/** "7,50" / "7.5" / "7" -> 750; ungültig -> null */
export function parseEuro(text) {
  const s = String(text ?? '').trim().replace(/\s|€/g, '').replace(',', '.')
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return null
  return Math.round(parseFloat(s) * 100)
}

export const euroInput = (cent) => ((cent || 0) / 100).toFixed(2).replace('.', ',')

/** Dauer in ms -> "45 s", "4 min", "1 h 05 min" */
export function dauer(ms) {
  if (ms == null || !isFinite(ms)) return '–'
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`
}
