<script setup>
// Dünner Wrapper um Plotly: theme-bewusst, reaktiv, ohne Zoom (Touch-Geräte).
import { onBeforeUnmount, onMounted, ref, shallowRef, watchEffect } from 'vue'
import { isDark } from '../ui.js'

const props = defineProps({
  // (theme) => ({ data, layout }) – wird bei jeder Datenänderung neu aufgerufen
  spec: { type: Function, required: true },
  height: { type: Number, default: 280 },
  label: { type: String, default: '' }
})

const el = ref(null)
const Plotly = shallowRef(null)
const themeVer = ref(0)
let ro = null
let resizeTimer = null
// Gebündelt (alte Browser feuern resize sehr oft); Plotly lehnt das Promise ab, wenn das Chart
// gerade nicht sichtbar ist oder noch aufgebaut wird – das ist harmlos und wird abgefangen.
const onResize = () => {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    if (!el.value || !Plotly.value) return
    const r = Plotly.value.Plots.resize(el.value)
    if (r && r.catch) r.catch(() => {})
  }, 100)
}

// Validierte Referenzpalette (dataviz/palette.md), feste Reihenfolge
const PALETTE = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767']
}

function readTheme() {
  const cs = getComputedStyle(document.documentElement)
  const v = (n) => cs.getPropertyValue(n).trim()
  const dark = isDark()
  return {
    dark,
    series: dark ? PALETTE.dark : PALETTE.light,
    text: v('--text'),
    text2: v('--text-2'),
    muted: v('--muted'),
    surface: v('--surface'),
    border: v('--border-strong'),
    grid: v('--chart-grid'),
    axis: v('--chart-axis'),
    font: v('--font')
  }
}

function baseLayout(t) {
  const axis = {
    gridcolor: t.grid, linecolor: t.axis, zeroline: false, showline: true,
    tickfont: { color: t.muted, size: 12 }, fixedrange: true, automargin: true,
    title: { font: { color: t.muted, size: 12 } }
  }
  return {
    height: props.height,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: t.font, size: 13, color: t.text2 },
    margin: { l: 8, r: 12, t: 8, b: 8 },
    separators: ',.',
    showlegend: false,
    hovermode: 'closest',
    dragmode: false,
    xaxis: { ...axis, showgrid: false },
    yaxis: { ...axis, rangemode: 'tozero', showline: false },
    hoverlabel: { bgcolor: t.surface, bordercolor: t.border, font: { color: t.text, family: t.font, size: 13 } },
    legend: { orientation: 'h', x: 0, y: 1.12, font: { color: t.text2, size: 12 }, bgcolor: 'rgba(0,0,0,0)' },
    barcornerradius: 4,
    bargap: 0.2
  }
}

function merge(a, b) {
  const out = { ...a }
  for (const [k, v] of Object.entries(b || {})) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Date) && a[k] && typeof a[k] === 'object'
      ? merge(a[k], v)
      : v
  }
  return out
}

const config = { displayModeBar: false, responsive: false, scrollZoom: false, doubleClick: false }

watchEffect(() => {
  themeVer.value // abhängig vom Theme
  if (!Plotly.value || !el.value) return
  const t = readTheme()
  const { data, layout } = props.spec(t)
  const r = Plotly.value.react(el.value, data, merge(baseLayout(t), layout), config)
  if (r && r.catch) r.catch((e) => console.warn('Chart konnte nicht gezeichnet werden', e))
})

const onTheme = () => { themeVer.value++ }

onMounted(async () => {
  const mod = await import('plotly.js-basic-dist-min')
  Plotly.value = mod.default || mod
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver(onResize)
    ro.observe(el.value)
  } else {
    window.addEventListener('resize', onResize) // Chrome < 64
  }
  window.addEventListener('themechange', onTheme)
})

onBeforeUnmount(() => {
  clearTimeout(resizeTimer)
  if (ro) ro.disconnect()
  window.removeEventListener('resize', onResize)
  window.removeEventListener('themechange', onTheme)
  if (Plotly.value && el.value) Plotly.value.purge(el.value)
})
</script>

<template>
  <div ref="el" class="plot" role="img" :aria-label="label" :style="{ minHeight: height + 'px' }"></div>
</template>

<style>
.plot { width: 100%; }
.plot .hoverlayer .hovertext path { stroke-width: 1px !important; }
</style>
