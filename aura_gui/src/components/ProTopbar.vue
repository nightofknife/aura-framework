<!-- === src/components/ProTopbar.vue (FIXED) === -->
<template>
  <header class="topbar">
    <!-- Topbar内容保持不变，为了简洁省略 -->
    <div class="left-group">
      <!-- ... -->
    </div>
    <div class="right-group">
      <input
          class="input search-input"
          v-model="q"
          placeholder="Search… (⌘/Ctrl + K)"
          @keydown.stop="noop"
      />
      <div class="status-group">
        <span class="dot" :class="isConnected ? 'ok':'bad'" title="WebSocket"></span>
        <span class="status-text">{{ isConnected ? 'Connected' : 'Offline' }}</span>
        <div class="separator"></div>
        <span class="pill" :class="[isSystemRunning ? 'pill-green pulse' : 'pill-red']">
          {{ isSystemRunning ? 'Engine Running' : 'Engine Stopped' }}
        </span>
      </div>
      <button class="btn btn-ghost" :disabled="isSystemRunning" @click="$emit('start')">Start</button>
      <button class="btn btn-primary" :disabled="!isSystemRunning" @click="$emit('stop')">Stop</button>
      <button class="btn btn-ghost theme-toggle" @click="toggleTheme"
              :title="isDark ? 'Switch to Light Mode' : 'Switch to Dark Mode'">
        {{ isDark ? '🌙' : '☀️' }}
      </button>
    </div>
  </header>
</template>

<script setup>
import {ref, computed, onMounted, onUnmounted} from 'vue';
import {useTheme} from '../composables/useTheme.js';

const {isDark, toggleTheme} = useTheme();

// FIX: defineProps must be called to access props
const props = defineProps({
  isConnected: Boolean,
  isSystemRunning: Boolean,
  env: {type: String, default: 'dev'}
});
defineEmits(['start', 'stop']);

const q = ref('');
const noop = () => {
};

const envLabel = computed(() =>
    props.env === 'prod' ? 'PROD' : (props.env === 'staging' ? 'STAGING' : 'DEV')
);
const envPillClass = computed(() =>
    props.env === 'prod' ? 'pill-red' : (props.env === 'staging' ? '' : 'pill-blue')
);

function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    document.querySelector('.search-input')?.focus();
  }
}

onMounted(() => window.addEventListener('keydown', onKey));
onUnmounted(() => window.removeEventListener('keydown', onKey));
</script>

<style scoped>
/* Topbar的局部样式保持不变，为了简洁省略 */
.left-group, .right-group, .status-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  font-size: 16px;
  color: var(--text-primary);
}

.search-input {
  min-width: 260px;
}

.status-text {
  color: var(--text-secondary);
  font-size: 13px;
}

.separator {
  width: 1px;
  height: 16px;
  background: var(--border-frosted);
}

.theme-toggle {
  padding: 8px;
  font-size: 16px;
}
</style>
<!-- === END src/components/ProTopbar.vue (FIXED) === -->
