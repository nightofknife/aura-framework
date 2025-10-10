<template>
  <div class="topbar">
    <div style="display:flex; align-items:center; gap:12px;">
      <strong style="font-size:16px;">⚙️ Aura Orchestrator</strong>
      <span class="pill" :class="envPillClass">{{ envLabel }}</span>
    </div>

    <div style="display:flex; align-items:center; gap:8px;">
      <input
          class="input"
          v-model="q"
          placeholder="Search… (⌘/Ctrl + K)"
          style="min-width:260px;"
          @keydown.stop="noop"
      />
      <span class="dot" :class="isConnected ? 'ok':'bad'" title="WebSocket"></span>
      <span style="color:var(--text-3); font-size:13px;">{{ isConnected ? 'WS Connected' : 'WS Offline' }}</span>
      <span style="opacity:.4;">|</span>
      <span class="pill" :class="isSystemRunning ? 'pill-green':'pill-red'">
        {{ isSystemRunning ? 'Engine Running' : 'Engine Stopped' }}
      </span>
      <button class="btn btn-outline" :disabled="isSystemRunning" @click="$emit('start')">Start</button>
      <button class="btn btn-primary" :disabled="!isSystemRunning" @click="$emit('stop')">Stop</button>
    </div>
  </div>
</template>

<script setup>
import {ref, computed, onMounted, onUnmounted} from 'vue'

const props = defineProps({
  isConnected: Boolean,
  isSystemRunning: Boolean,
  env: {type: String, default: 'dev'}
})
defineEmits(['start', 'stop', 'open-search'])

const q = ref('')
const noop = () => {
}

const envLabel = computed(() =>
    props.env === 'prod' ? 'PROD' : (props.env === 'staging' ? 'STAGING' : 'DEV')
)
const envPillClass = computed(() =>
    props.env === 'prod' ? 'pill-red' : (props.env === 'staging' ? 'pill-gray' : 'pill-blue')
)

function onKey(e) {
  const key = e.key ? e.key.toLowerCase() : ''
  if ((e.ctrlKey || e.metaKey) && key === 'k') {
    e.preventDefault()
    const box = document.querySelector('.topbar .input')
    if (box && typeof box.focus === 'function') box.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
