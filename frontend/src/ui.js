// Toasts und Bestätigungsdialog (statt alert/confirm, die den Browser blockieren)

import { reactive } from 'vue'

export const toasts = reactive([])
let nextId = 1

/**
 * toast('Gespeichert') / toast('Fehler', 'error') /
 * toast('Abgeholt', 'ok', { action: { label: 'Rückgängig', run: fn } })
 */
export function toast(text, type = 'info', { timeout, action } = {}) {
  const id = nextId++
  toasts.push({ id, text, type, action })
  // Nicht mehr als 3 gleichzeitig – sonst verdecken sie die Kasse
  while (toasts.length > 3) toasts.shift()
  const ms = timeout ?? (type === 'error' ? 6000 : action ? 6000 : 3500)
  setTimeout(() => dismiss(id), ms)
  return id
}

export function dismiss(id) {
  const i = toasts.findIndex(t => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

/** Fehler aus API-Aufrufen einheitlich anzeigen */
export function showError(e) {
  toast(e?.message || String(e), 'error')
}

export const dialog = reactive({ open: false, title: '', text: '', confirmText: 'OK', danger: false, requireText: '', resolve: null })

export function confirmDialog({ title, text = '', confirmText = 'OK', danger = false, requireText = '' }) {
  if (dialog.resolve) dialog.resolve(false)
  return new Promise(resolve => {
    Object.assign(dialog, { open: true, title, text, confirmText, danger, requireText, resolve })
  })
}

export function closeDialog(result) {
  const r = dialog.resolve
  Object.assign(dialog, { open: false, resolve: null })
  if (r) r(result)
}

// Hell/Dunkel: 'auto' folgt dem Gerät
const THEME_KEY = 'kasse-theme'
export function getTheme() {
  try { return localStorage.getItem(THEME_KEY) || 'auto' } catch { return 'auto' }
}
export function setTheme(t) {
  try { localStorage.setItem(THEME_KEY, t) } catch { /* privat-Modus */ }
  applyTheme(t)
}
export function applyTheme(t = getTheme()) {
  if (t === 'auto') delete document.documentElement.dataset.theme
  else document.documentElement.dataset.theme = t
  window.dispatchEvent(new Event('themechange'))
}
const darkMq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
const onMq = () => window.dispatchEvent(new Event('themechange'))
if (darkMq) {
  if (darkMq.addEventListener) darkMq.addEventListener('change', onMq)
  else if (darkMq.addListener) darkMq.addListener(onMq) // ältere WebViews
}

/** Ist gerade das dunkle Theme aktiv? (computed colorScheme gibt es erst ab Chrome 81) */
export function isDark() {
  const t = document.documentElement.dataset.theme
  if (t) return t === 'dark'
  return !!(darkMq && darkMq.matches)
}
