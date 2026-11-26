// Wer steht an diesem Gerät? (Kasse / Ausgabe) – pro Gerät gemerkt, für das Ranking in der Statistik.

import { computed, ref, watch } from 'vue'
import { state } from './store.js'

function gemerkt(schluessel) {
  let start = ''
  try { start = localStorage.getItem(schluessel) || '' } catch { /* privat/gesperrt */ }
  const r = ref(start)
  watch(r, (v) => {
    try { localStorage.setItem(schluessel, (v || '').trim()) } catch { /* egal */ }
  })
  return r
}

export const kassierer = gemerkt('kasse.kassierer')
export const ausgabePerson = gemerkt('kasse.ausgabe')

/** Zuletzt benutzte Namen (neueste zuerst) – zum schnellen Wechseln per Antippen */
function letzteNamen(feld) {
  return computed(() => {
    const namen = []
    for (const b of state.bestellungen) { // neueste zuerst
      const n = b[feld]
      if (n && !namen.includes(n)) namen.push(n)
      if (namen.length >= 6) break
    }
    return namen
  })
}
export const letzteKassierer = letzteNamen('kassierer')
export const letzteAusgabe = letzteNamen('ausgabe')
