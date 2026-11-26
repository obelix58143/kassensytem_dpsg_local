<script setup>
// Namensfeld „Wer kassiert / wer gibt aus?" mit zuletzt benutzten Namen zum Antippen
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, required: true },
  vorschlaege: { type: Array, default: () => [] },
  startOffen: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'fertig'])
const offen = ref(props.startOffen || !props.modelValue)
const andere = computed(() => props.vorschlaege.filter(n => n !== props.modelValue).slice(0, 5))

function setzen(n) {
  emit('update:modelValue', (n || '').trim())
  if ((n || '').trim()) { offen.value = false; emit('fertig') }
}
</script>

<template>
  <div class="person" :class="{ leer: !modelValue }">
    <template v-if="!offen && modelValue">
      <span class="person-label">{{ label }}</span>
      <strong class="person-name">{{ modelValue }}</strong>
      <button class="btn btn-sm btn-ghost" @click="offen = true">Wechseln</button>
    </template>
    <template v-else>
      <label class="person-feld">
        <span class="person-label">{{ label }}</span>
        <input :value="modelValue" maxlength="40" placeholder="Name eintragen" autocomplete="off"
               @change="setzen($event.target.value)" @keydown.enter="setzen($event.target.value)">
      </label>
      <div v-if="andere.length" class="row person-chips">
        <button v-for="n in andere" :key="n" class="chip" @click="setzen(n)">{{ n }}</button>
      </div>
      <button v-if="modelValue" class="btn btn-sm" @click="offen = false; $emit('fertig')">OK</button>
    </template>
  </div>
</template>

<style>
.person { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px; border-radius: var(--radius-sm); background: var(--surface-2); }
.person.leer { background: var(--warn-soft, var(--surface-2)); outline: 2px dashed var(--warn); }
.person-label { font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 700; }
.person-name { font-size: 1.05rem; flex: 1; }
.person-feld { display: flex; align-items: center; gap: 8px; flex: 1 1 200px; }
.person-feld input { flex: 1; min-width: 0; height: 40px; padding: 0 10px; font: inherit; border: 1px solid var(--border-strong); border-radius: var(--radius-sm); background: var(--surface); color: var(--text); }
.person-chips { gap: 6px; }
</style>
