// Globale Styles zuerst, damit Komponenten-Styles sie überschreiben können
import './styles.css'
import './compat.css'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router.js'
import { connect } from './store.js'
import { applyTheme } from './ui.js'

// Flex-`gap` gibt es erst ab Chrome 84 und lässt sich nicht per @supports prüfen
;(function detectFlexGap() {
  const d = document.createElement('div')
  d.style.cssText = 'display:flex;flex-direction:column;row-gap:1px;position:absolute;visibility:hidden'
  d.appendChild(document.createElement('div'))
  d.appendChild(document.createElement('div'))
  document.body.appendChild(d)
  if (d.scrollHeight !== 1) document.documentElement.classList.add('no-flexgap')
  document.body.removeChild(d)
})()

applyTheme()
connect()
createApp(App).use(router).mount('#app')
