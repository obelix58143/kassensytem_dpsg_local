<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import { state } from './store.js'
import { toasts, dismiss, dialog, closeDialog } from './ui.js'

const route = useRoute()
const kiosk = computed(() => route.meta.kiosk)

// Offline-Banner erst nach 3 s zeigen (kurze Reconnects nicht aufblinken lassen)
const offline = ref(false)
let offlineTimer = null
watch(() => state.connected, (c) => {
  clearTimeout(offlineTimer)
  if (c) offline.value = false
  else offlineTimer = setTimeout(() => { offline.value = true }, 3000)
}, { immediate: true })

const dialogEl = ref(null)
const typed = ref('')
const canConfirm = computed(() => !dialog.requireText || typed.value.trim() === dialog.requireText)
watch(() => dialog.open, async (open) => {
  await nextTick()
  if (!dialogEl.value) return
  if (open) {
    typed.value = ''
    dialogEl.value.showModal()
  } else if (dialogEl.value.open) {
    dialogEl.value.close()
  }
})
function onDialogClose() {
  if (dialog.open) closeDialog(false)
}
</script>

<template>
  <AppHeader v-if="!kiosk" />
  <div v-if="offline" class="offline" role="alert">
    <strong>Keine Verbindung zum Server.</strong> Anzeige ist evtl. veraltet – verbinde neu …
  </div>

  <div v-if="!state.loaded" class="loading">
    <div class="spinner" aria-hidden="true"></div>
    <p>Verbinde mit Kasse …</p>
  </div>
  <router-view v-else />

  <div class="toasts" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="'toast-' + t.type">
        <span class="toast-icon" aria-hidden="true">{{ t.type === 'error' ? '!' : t.type === 'warn' ? '!' : '✓' }}</span>
        <span class="toast-text">{{ t.text }}</span>
        <button v-if="t.action" class="btn btn-sm" @click="t.action.run(); dismiss(t.id)">{{ t.action.label }}</button>
        <button class="toast-x" aria-label="Schließen" @click="dismiss(t.id)">×</button>
      </div>
    </TransitionGroup>
  </div>

  <dialog ref="dialogEl" class="dialog" @close="onDialogClose" @cancel.prevent="closeDialog(false)">
    <form method="dialog" class="stack" @submit.prevent="canConfirm && closeDialog(true)">
      <h2>{{ dialog.title }}</h2>
      <p v-if="dialog.text" class="text-2">{{ dialog.text }}</p>
      <label v-if="dialog.requireText" class="field">
        Zum Bestätigen „{{ dialog.requireText }}" eintippen
        <input v-model="typed" autocomplete="off" autofocus>
      </label>
      <div class="row" style="justify-content: flex-end; margin-top: 8px">
        <button type="button" class="btn" @click="closeDialog(false)">Abbrechen</button>
        <button type="submit" class="btn" :class="dialog.danger ? 'btn-danger-solid' : 'btn-primary'" :disabled="!canConfirm">
          {{ dialog.confirmText }}
        </button>
      </div>
    </form>
  </dialog>
</template>

<style>
.offline {
  position: sticky; top: 0; z-index: 50;
  background: var(--danger); color: #fff;
  padding: 10px 16px; text-align: center; font-size: .95rem;
}
.loading { display: flex; flex-direction: column; align-items: center; gap: 14px; padding: 18vh 16px; color: var(--muted); }
.spinner { width: 34px; height: 34px; border-radius: 50%; border: 3px solid var(--surface-3); border-top-color: var(--primary); animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.toasts { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); z-index: 100; display: flex; flex-direction: column; gap: 8px; width: calc(100vw - 32px); max-width: 520px; pointer-events: none; }
.toast {
  pointer-events: auto;
  display: flex; align-items: center; gap: 12px;
  background: var(--text); color: var(--bg);
  border-radius: 12px; padding: 10px 10px 10px 14px;
  box-shadow: var(--shadow-lg);
  font-weight: 600;
}
.toast .btn { background: transparent; color: inherit; border-color: var(--toast-btn-border); }
.toast-icon { flex: none; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: .85rem; font-weight: 800; background: var(--ok); color: #fff; }
.toast-error .toast-icon { background: var(--danger); }
.toast-warn .toast-icon { background: var(--warn); color: #000; }
.toast-text { flex: 1; }
.toast-x { background: none; border: 0; color: inherit; opacity: .6; font-size: 1.4rem; cursor: pointer; width: 32px; height: 32px; }
.toast-enter-active, .toast-leave-active { transition: all .2s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(10px); }

.dialog {
  border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); color: var(--text);
  padding: 22px; width: calc(100vw - 32px); max-width: 440px;
  box-shadow: var(--shadow-lg);
}
.dialog::backdrop { background: rgba(0, 0, 0, .45); }
</style>
