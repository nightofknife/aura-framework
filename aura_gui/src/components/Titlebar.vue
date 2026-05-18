<template>
  <header class="titlebar" @dblclick="toggleMaximize">
    <div class="titlebar__left">
      <img class="titlebar__logo" :src="logoSrc" alt="Aura" />
      <span class="titlebar__name">Aura</span>
    </div>

    <div v-if="isElectron && !isMac" class="titlebar__controls no-drag">
      <button class="titlebar__btn" aria-label="最小化" @click.stop="minimize">
        <Minus class="icon" />
      </button>
      <button class="titlebar__btn" :aria-label="isMax ? '还原' : '最大化'" @click.stop="toggleMaximize">
        <Copy v-if="isMax" class="icon" />
        <Square v-else class="icon" />
      </button>
      <button class="titlebar__btn titlebar__btn--close" aria-label="关闭" @click.stop="close">
        <X class="icon" />
      </button>
    </div>
  </header>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Copy, Minus, Square, X } from 'lucide-vue-next'

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
  if (typeof off === 'function') off()
})
</script>

<style scoped>
.titlebar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: var(--titlebar-h);
  padding: 0 10px 0 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-sidebar);
  color: var(--text-secondary);
  -webkit-app-region: drag;
}

.titlebar__left {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.titlebar__logo {
  width: 16px;
  height: 16px;
}

.titlebar__name {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 650;
}

.titlebar__controls {
  display: inline-flex;
  gap: 4px;
}

.titlebar__btn {
  display: inline-flex;
  width: 34px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.titlebar__btn:hover {
  background: var(--bg-surface-2);
  color: var(--text-primary);
}

.titlebar__btn--close:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.no-drag {
  -webkit-app-region: no-drag;
}
</style>
