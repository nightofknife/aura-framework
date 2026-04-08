<template>
  <header class="titlebar" @dblclick="toggleMaximize">
    <div class="titlebar__left">
      <img class="titlebar__logo" :src="logoSrc" alt="Aura" />
      <span class="titlebar__name">Aura</span>
      <span class="titlebar__mode">Expedition Orchestrator</span>
    </div>

    <div v-if="isElectron && !isMac" class="titlebar__controls no-drag">
      <button class="titlebar__btn" @click.stop="minimize" aria-label="Minimize">
        <svg viewBox="0 0 24 24"><path d="M5 12h14" /></svg>
      </button>
      <button class="titlebar__btn" @click.stop="toggleMaximize" :aria-label="isMax ? 'Restore' : 'Maximize'">
        <svg v-if="!isMax" viewBox="0 0 24 24"><path d="M7 7h10v10H7z" /></svg>
        <svg v-else viewBox="0 0 24 24"><path d="M8 10V8h8v8h-2" /><path d="M8 8h8" /><path d="M8 8v8h8" /></svg>
      </button>
      <button class="titlebar__btn titlebar__btn--close" @click.stop="close" aria-label="Close">
        <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>
  </header>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  logo: { type: String, default: './favicon.svg' },
})

const logoSrc = props.logo
const isElectron = !!window.AURA?.isElectron
const isMac = (window.AURA?.platform || navigator.platform || '').toLowerCase().includes('mac')
const isMax = ref(false)

function minimize() {
  window.AURA?.windowControls?.minimize?.()
}

function toggleMaximize() {
  window.AURA?.windowControls?.toggleMaximize?.()
}

function close() {
  window.AURA?.windowControls?.close?.()
}

let off = null

onMounted(() => {
  off = window.AURA?.windowControls?.onMaximizedChange?.((value) => {
    isMax.value = !!value
  })
})

onBeforeUnmount(() => {
  if (typeof off === 'function') {
    off()
  }
})
</script>

<style scoped>
.titlebar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  height: var(--titlebar-h);
  padding: 0 12px 0 14px;
  border-bottom: 1px solid rgba(137, 160, 177, 0.14);
  background: rgba(6, 16, 27, 0.78);
  color: var(--smoke);
  backdrop-filter: blur(10px);
  -webkit-app-region: drag;
}

.titlebar__left {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.titlebar__logo {
  width: 16px;
  height: 16px;
}

.titlebar__name,
.titlebar__mode {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.titlebar__name {
  color: var(--sand-bright);
}

.titlebar__mode {
  color: var(--smoke-dim);
}

.titlebar__controls {
  display: inline-flex;
  gap: 6px;
}

.titlebar__btn {
  display: inline-flex;
  width: 38px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  background: transparent;
  color: var(--smoke-dim);
  cursor: pointer;
  clip-path: polygon(8px 0, 100% 0, calc(100% - 8px) 100%, 0 100%);
}

.titlebar__btn:hover {
  border-color: var(--line);
  background: rgba(18, 42, 62, 0.9);
  color: var(--sand-bright);
}

.titlebar__btn--close:hover {
  border-color: rgba(218, 100, 88, 0.28);
  background: rgba(218, 100, 88, 0.18);
  color: #ffd7d0;
}

.titlebar__btn svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.no-drag {
  -webkit-app-region: no-drag;
}
</style>
