import { watchEffect } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { state } from './store.js'
import HomeView from './views/HomeView.vue'
import KasseView from './views/KasseView.vue'
import AusgabeView from './views/AusgabeView.vue'
import FrontView from './views/FrontView.vue'
import SettingsView from './views/SettingsView.vue'

// Hash-Routing: alte Links (/#/kasse, /#/ausgabe, …) funktionieren weiter.
const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { title: 'Start' } },
  { path: '/kasse', name: 'kasse', component: KasseView, meta: { title: 'Kasse' } },
  { path: '/ausgabe', name: 'ausgabe', component: AusgabeView, meta: { title: 'Ausgabe' } },
  { path: '/front', name: 'front', component: FrontView, meta: { title: 'Kundendisplay', kiosk: true } },
  // Plotly ist groß – erst laden, wenn die Statistik geöffnet wird
  { path: '/statistik', name: 'statistik', component: () => import('./views/StatistikView.vue'), meta: { title: 'Statistik' } },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { title: 'Einstellungen' }, alias: '/einstellungen' },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({ history: createWebHashHistory(), routes })
// Browser-Tab: „Kasse · <Name der Kasse>“
watchEffect(() => {
  document.title = `${router.currentRoute.value.meta.title || ''} · ${state.einstellungen.titel}`
})
export default router
