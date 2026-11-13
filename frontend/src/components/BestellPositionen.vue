<script setup>
import { computed } from 'vue'
import { produktById } from '../store.js'

const props = defineProps({ produkte: { type: Array, required: true } })
// Pfandrückgaben interessieren Ausgabe/Display nicht
const sichtbar = computed(() => props.produkte.filter(p => produktById.value.get(p.id)?.typ !== 'pfand'))
</script>

<template>
  <ul class="bpos">
    <li v-for="p in sichtbar" :key="p.id">
      <span class="bpos-anz num">{{ p.anzahl }}×</span>
      <span>{{ produktById.get(p.id)?.name ?? `Produkt #${p.id}` }}</span>
    </li>
  </ul>
</template>

<style>
.bpos { list-style: none; margin: 0; padding: 0; }
.bpos li { display: flex; gap: 8px; padding: 2px 0; }
.bpos-anz { font-weight: 800; min-width: 2.2ch; text-align: right; }
</style>
