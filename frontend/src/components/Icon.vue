<script setup>
// Inline-SVG statt Emoji: Emoji fehlen auf manchen Geräten (z.B. Raspberry Pi) und erscheinen als Kästchen.
defineProps({ name: { type: String, required: true }, size: { type: [Number, String], default: 18 } })

const paths = {
  printer: 'M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v7H6z',
  clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2',
  x: 'M18 6 6 18M6 6l12 12',
  check: 'M20 6 9 17l-5-5',
  undo: 'M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3'
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="icon">
    <path :d="paths[name]" />
  </svg>
</template>

<style>
.icon { flex: none; vertical-align: -0.15em; }
</style>
