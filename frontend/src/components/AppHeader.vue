<script setup>
import { computed, ref } from 'vue'
import { state, offeneBestellungen, serverNow } from '../store.js'
import { getTheme, setTheme } from '../ui.js'

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
      <button class="btn btn-ghost btn-sm" :title="'Darstellung: ' + themes[theme]" @click="nextTheme">
        {{ theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐' }} <span class="hide-sm">{{ themes[theme] }}</span>
      </button>
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
.status { display: inline-flex; align-items: center; gap: 6px; font-size: .85rem; font-weight: 700; padding: 4px 10px; border-radius: 999px; }
.status.is-on { color: var(--ok); background: var(--ok-soft); }
.status.is-off { color: var(--danger); background: var(--danger-soft); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.is-on .dot { animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .35; } }
.clock { font-weight: 700; color: var(--text-2); }
@media (max-width: 720px) {
  .hide-sm, .clock { display: none; }
  .brand span:last-child { display: none; }
  .header { gap: 8px; }
}
</style>
