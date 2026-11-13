<script setup>
import { computed } from 'vue'
import { karteById, serverNow, state } from '../store.js'
import { dauer, uhrzeit } from '../format.js'
import BestellPositionen from './BestellPositionen.vue'
import Icon from './Icon.vue'

// Ab wann eine Bestellung farblich markiert wird (Minuten)
const WARN_MIN = 5
const KRIT_MIN = 10

const props = defineProps({
  b: { type: Object, required: true },
  // 'offen' (ohne Bereit-Schritt), 'zubereitung' oder 'bereit'
  phase: { type: String, default: 'offen' },
  busy: { type: Boolean, default: false }
})
defineEmits(['fertig', 'abgeholt', 'zurueck', 'bon', 'storno'])

// Abholbereite Bestellungen: Zeit seit „bereit", sonst seit Bestellung
const seit = computed(() => (props.phase === 'bereit' && props.b.zeitpunkt_bereit ? props.b.zeitpunkt_bereit : props.b.zeitpunkt_annahme))
const wartezeit = computed(() => serverNow() - Date.parse(seit.value))
const stufe = computed(() => {
  const min = wartezeit.value / 60000
  return min >= KRIT_MIN ? 'krit' : min >= WARN_MIN ? 'warn' : 'ok'
})
const karte = computed(() => (props.b.karte == null ? null : karteById.value.get(props.b.karte)?.beschreibung ?? '?'))
</script>

<template>
  <article class="order card" :class="['stufe-' + stufe, 'phase-' + phase]">
    <header class="order-head">
      <span class="order-id">#{{ b.id }}</span>
      <span v-if="karte" class="badge badge-primary">{{ karte }}</span>
      <span v-if="b.eigenbedarf" class="badge">Eigenbedarf</span>
      <span v-if="phase === 'offen' && b.status === 'bereit'" class="badge badge-ok">bereit</span>
      <span class="spacer"></span>
      <span class="wait num" :title="(phase === 'bereit' ? 'Bereit seit ' : 'Bestellt um ') + uhrzeit(seit)">
        <Icon v-if="stufe !== 'ok'" name="clock" :size="16" /> {{ dauer(wartezeit) }}
      </span>
    </header>
    <BestellPositionen :produkte="b.produkte" class="order-items" />
    <footer class="order-foot">
      <button v-if="phase === 'zubereitung'" class="btn btn-primary btn-lg order-done" :disabled="busy" @click="$emit('fertig', b)">
        <Icon name="check" :size="22" /> Fertig
      </button>
      <button v-else class="btn btn-ok btn-lg order-done" :disabled="busy" @click="$emit('abgeholt', b)">
        <Icon name="check" :size="22" /> Abgeholt
      </button>
      <button v-if="phase === 'bereit'" class="btn btn-icon" title="Zurück in Zubereitung" aria-label="Zurück in Zubereitung" :disabled="busy" @click="$emit('zurueck', b)"><Icon name="undo" /></button>
      <button v-if="state.einstellungen.drucker_aktiv" class="btn btn-icon" title="Bon nachdrucken" aria-label="Bon nachdrucken" @click="$emit('bon', b)"><Icon name="printer" /></button>
      <button class="btn btn-icon btn-danger" title="Stornieren" aria-label="Stornieren" @click="$emit('storno', b)"><Icon name="x" /></button>
    </footer>
  </article>
</template>

<style>
.order { --stufe: var(--ok); display: flex; flex-direction: column; gap: 12px; padding: 16px 16px 16px 22px; box-shadow: inset 6px 0 0 var(--stufe), var(--shadow); }
.order.stufe-warn { --stufe: var(--warn); }
.order.stufe-krit { --stufe: var(--danger); background: var(--krit-bg); }
.order.phase-bereit { --stufe: var(--ok); background: var(--ok-soft); }
.order.phase-bereit.stufe-krit { --stufe: var(--warn); }
.order-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.order-id { font-size: 1.7rem; font-weight: 800; letter-spacing: -0.02em; }
.wait { font-weight: 700; color: var(--text-2); display: inline-flex; align-items: center; gap: 4px; }
.stufe-warn .wait { color: var(--warn); }
.stufe-krit .wait { color: var(--danger); }
.phase-bereit .wait { color: var(--ok); }
.order-items { font-size: 1.15rem; flex: 1; }
.order-foot { display: flex; gap: 6px; flex-wrap: wrap; }
.order-done { flex: 1 1 110px; padding: 0 12px; }
.order-foot .btn-icon { flex: none; width: 40px; min-height: 60px; }
</style>
