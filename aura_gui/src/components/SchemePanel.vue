<!-- === src/components/SchemePanel.vue === -->
<template>
  <div class="scheme-panel">
    <button class="scheme-head" @click="toggle" :aria-expanded="openLocal ? 'true' : 'false'">
      <div class="title">
        <span class="chev" :class="{ open: openLocal }" aria-hidden="true">▸</span>
        <strong>{{ title }}</strong>
      </div>
      <div class="desc" v-if="description">{{ description }}</div>
      <div class="actions"><slot name="actions"/></div>
    </button>

    <Transition
        @enter="onEnter"
        @after-enter="onAfterEnter"
        @leave="onLeave"
    >
      <div v-show="openLocal" class="scheme-body">
        <slot/>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue';

const props = defineProps({
  title: String,
  description: String,
  open: { type: Boolean, default: false },
});
const emit = defineEmits(['update:open']);

const openLocal = ref(!!props.open);
watch(() => props.open, v => openLocal.value = v);

function toggle() {
  openLocal.value = !openLocal.value;
  emit('update:open', openLocal.value);
}

// 高度过渡动画
function onEnter(el) {
  el.style.height = 'auto';
  const height = getComputedStyle(el).height;
  el.style.height = '0';
  requestAnimationFrame(() => { el.style.height = height; });
}
function onAfterEnter(el) { el.style.height = 'auto'; }
function onLeave(el) {
  el.style.height = getComputedStyle(el).height;
  requestAnimationFrame(() => { el.style.height = '0'; });
}
</script>

<style scoped>
.scheme-panel {
  backdrop-filter: blur(12px);
  background: var(--bg-surface);
  border: 1px solid var(--border-frosted);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-panel);
  transition: all var(--dur) var(--ease);
}
.scheme-panel:hover {
  border-color: var(--primary-accent);
  box-shadow: var(--shadow-glow), var(--shadow-panel);
}
.scheme-head {
  width: 100%; display: flex; gap: 12px; align-items: center;
  padding: 12px 16px; cursor: pointer; background: transparent; border: none; text-align: left;
  color: var(--text-primary);
}
.title { display: flex; gap: 8px; align-items: center; }
.chev {
  width: 14px; display: inline-block; color: var(--text-secondary);
  transition: transform var(--dur) var(--ease);
}
.chev.open { transform: rotate(90deg); }
.desc { color: var(--text-secondary); font-size: 12px; flex: 1; margin-left: 8px; }
.actions { display: flex; gap: 6px; }

.scheme-body {
  padding: 0 16px 16px;
  border-top: 1px solid var(--border-frosted);
  overflow: hidden;
  transition: height var(--dur) var(--ease);
}
</style>
<!-- === END src/components/SchemePanel.vue === -->
