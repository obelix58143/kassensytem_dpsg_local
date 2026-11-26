<script setup>
import { computed } from 'vue'
import { abholbereit, inZubereitung, karteById, offeneBestellungen, serverNow, state, displayProdukte } from '../store.js'
import { euro } from '../format.js'

const uhr = computed(() => new Date(serverNow()).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }))
const mitPfand = computed(() => displayProdukte.value.some(p => p.pfand_cent))
const bereitAktiv = computed(() => !!state.einstellungen.bereit_aktiv)
// Ohne Bereit-Schritt ist alles Offene „in Zubereitung"
const zubereitung = computed(() => (bereitAktiv.value ? inZubereitung.value : offeneBestellungen.value))
const karteVon = (b) => (b.karte != null && karteById.value.get(b.karte) ? karteById.value.get(b.karte).beschreibung : null)

function vollbild() {
  const el = document.documentElement
  const aktiv = document.fullscreenElement || document.webkitFullscreenElement
  try {
    if (!aktiv) {
      const req = el.requestFullscreen || el.webkitRequestFullscreen
      const p = req && req.call(el)
      if (p && p.catch) p.catch(() => {})
    } else {
      const exit = document.exitFullscreen || document.webkitExitFullscreen
      if (exit) exit.call(document)
    }
  } catch { /* Vollbild nicht erlaubt */ }
}
</script>

<template>
  <main class="front" @dblclick="vollbild">
    <header class="front-head">
      <div class="front-brand"><span aria-hidden="true">⚜</span> {{ state.einstellungen.titel }}</div>
      <div class="row" style="gap: 14px">
        <span class="front-dot" :class="{ off: !state.connected }" :title="state.connected ? 'Live' : 'Offline'"></span>
        <span class="front-clock num">{{ uhr }}</span>
        <router-link to="/" class="front-exit" title="Zurück">×</router-link>
      </div>
    </header>

    <div class="front-body">
      <section class="front-queue">
        <div v-if="bereitAktiv" class="front-ready">
          <h1>Bitte abholen</h1>
          <TransitionGroup v-if="abholbereit.length" tag="div" name="list" class="front-grid">
            <div v-for="b in abholbereit" :key="b.id" class="front-num ready">
              <span class="n">{{ b.id }}</span>
              <span v-if="karteVon(b)" class="k">{{ karteVon(b) }}</span>
            </div>
          </TransitionGroup>
          <p v-else class="front-sub">Gerade nichts abholbereit.</p>
        </div>

        <h1>In Zubereitung</h1>
        <p class="front-sub">Deine Nummer steht auf dem Bon.</p>
        <TransitionGroup v-if="zubereitung.length" tag="div" name="list" class="front-grid">
          <div v-for="b in zubereitung" :key="b.id" class="front-num">
            <span class="n">{{ b.id }}</span>
            <span v-if="karteVon(b)" class="k">{{ karteVon(b) }}</span>
          </div>
        </TransitionGroup>
        <p v-else class="front-empty">Gerade keine Wartezeit – bestell jetzt!</p>
      </section>

      <section class="front-menu">
        <h1>Unser Angebot</h1>
        <ul>
          <li v-for="p in displayProdukte" :key="p.id">
            <div>
              <div class="m-name">{{ p.name }}</div>
              <div v-if="p.beschreibung" class="m-desc">{{ p.beschreibung }}</div>
            </div>
            <div class="m-price num">{{ euro(p.preis_cent) }}<span v-if="p.pfand_cent">*</span></div>
          </li>
        </ul>
        <p v-if="mitPfand" class="m-note">* zzgl. Pfand</p>
      </section>
    </div>
  </main>
</template>

<style>
/* Kundendisplay: immer dunkel, gut lesbar aus der Entfernung */
.front {
  --f-bg: #0f1115; --f-surface: #1a1d23; --f-text: #f4f2ee; --f-muted: #9aa0a8; --f-accent: #e0394e;
  min-height: 100vh; background: var(--f-bg); color: var(--f-text);
  display: flex; flex-direction: column;
  padding: 24px;
  padding: clamp(16px, 2.5vw, 40px);
  font-size: 18px;
  font-size: clamp(16px, 1.4vw, 26px);
}
.front-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2.5vh; }
.front-brand { font-weight: 800; font-size: 1.3em; color: var(--f-accent); }
.front-clock { font-size: 1.4em; font-weight: 700; }
.front-dot { width: 12px; height: 12px; border-radius: 50%; background: #3dbb62; }
.front-dot.off { background: #ef5b5b; }
.front-exit { color: var(--f-muted); text-decoration: none; font-size: 1.6em; line-height: 1; opacity: .35; }
.front-exit:hover { opacity: 1; }
.front-body { flex: 1; display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: 32px; gap: clamp(16px, 3vw, 56px); }
@media (max-width: 800px) { .front-body { grid-template-columns: minmax(0, 1fr); } }
.front h1 { font-size: 2em; color: var(--f-text); }
.front-sub { color: var(--f-muted); margin: .3em 0 1.2em; }
.front-grid { position: relative; display: grid; grid-template-columns: repeat(auto-fill, minmax(6.6em, 1fr)); gap: .7em; }
.front-num {
  background: var(--f-surface); border-radius: 18px;
  padding: .6em .4em; text-align: center;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border: 1px solid rgba(255,255,255,.07);
}
.front-num .n { font-size: 2.4em; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums; }
.front-num .k { font-size: .75em; color: var(--f-muted); margin-top: .35em; }
.front-ready { background: rgba(61, 187, 98, .12); border: 2px solid #3dbb62; border-radius: 24px; padding: .8em 1em 1em; margin-bottom: 1.4em; }
.front-ready h1 { color: #5fd283; margin-bottom: .5em; }
.front-num.ready { background: #1f6b37; border-color: #3dbb62; animation: ready-pop .6s ease; }
.front-num.ready .k { color: #c9f2d6; }
@keyframes ready-pop { 0% { transform: scale(.8); } 60% { transform: scale(1.08); } 100% { transform: scale(1); } }
.front-empty { font-size: 1.4em; color: var(--f-muted); margin-top: 1em; }
.front-menu { background: var(--f-surface); border-radius: 24px; padding: 1.2em 1.4em; align-self: start; }
.front-menu ul { list-style: none; margin: 1em 0 0; padding: 0; }
.front-menu li { display: flex; justify-content: space-between; align-items: baseline; gap: 1em; padding: .65em 0; border-bottom: 1px solid rgba(255,255,255,.08); }
.front-menu li:last-child { border-bottom: 0; }
.m-name { font-weight: 700; font-size: 1.15em; }
.m-desc { color: var(--f-muted); font-size: .85em; }
.m-price { font-weight: 800; font-size: 1.3em; color: var(--f-accent); white-space: nowrap; }
.m-note { color: var(--f-muted); font-size: .8em; margin-top: .8em; }
</style>
