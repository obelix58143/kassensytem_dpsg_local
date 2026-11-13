import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'
import autoprefixer from 'autoprefixer'
import { fileURLToPath, URL } from 'node:url'

// Entwicklung: `npm run dev` – API und WebSocket werden an Flask weitergereicht.
const backend = process.env.BACKEND_URL || 'http://localhost:5000'

// Ziel: auch alte Tablets (LineageOS 14.1 / Android 7.1, WebView ab Chrome 53).
const TARGETS = ['chrome >= 53', 'android >= 7']

// Chrome 57–65 kennt für Grid nur `grid-gap`, nicht `gap`
const gridGapFallback = {
  postcssPlugin: 'grid-gap-fallback',
  Declaration: {
    gap(decl) {
      if (!decl.parent.some(d => d.prop === 'grid-gap')) decl.cloneBefore({ prop: 'grid-gap' })
    }
  }
}

export default defineConfig({
  plugins: [
    vue(),
    legacy({
      targets: TARGETS,
      // Nur ein Bundle (SystemJS + Polyfills) für alle Geräte: ein Codepfad,
      // den wir testen – moderne Browser laden einfach dasselbe.
      renderModernChunks: false
    })
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  css: {
    postcss: { plugins: [gridGapFallback, autoprefixer({ overrideBrowserslist: TARGETS })] }
  },
  server: {
    host: true,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true }
    }
  },
  build: {
    cssTarget: 'chrome53',
    chunkSizeWarningLimit: 4000
  }
})
