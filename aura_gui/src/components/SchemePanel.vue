<template>
  <section class="scheme-panel">
    <button class="scheme-panel__head" @click="toggle" :aria-expanded="openLocal ? 'true' : 'false'">
      <div>
        <span class="scheme-panel__kicker">Section</span>
        <strong class="scheme-panel__title">{{ title }}</strong>
      </div>
      <span class="scheme-panel__toggle">{{ openLocal ? '−' : '+' }}</span>
    </button>

    <Transition @enter="onEnter" @after-enter="onAfterEnter" @leave="onLeave">
      <div v-show="openLocal" class="scheme-panel__body">
        <p v-if="description" class="scheme-panel__desc">{{ description }}</p>
        <slot />
      </div>
    </Transition>
  </section>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  open: { type: Boolean, default: false },
})

const emit = defineEmits(['update:open'])
const openLocal = ref(!!props.open)

watch(() => props.open, (value) => {
  openLocal.value = value
})

function toggle() {
  openLocal.value = !openLocal.value
  emit('update:open', openLocal.value)
}

function onEnter(element) {
  element.style.height = 'auto'
  const height = getComputedStyle(element).height
  element.style.height = '0'
  requestAnimationFrame(() => {
    element.style.height = height
  })
}

function onAfterEnter(element) {
  element.style.height = 'auto'
}

function onLeave(element) {
  element.style.height = getComputedStyle(element).height
  requestAnimationFrame(() => {
    element.style.height = '0'
  })
}
</script>

<style scoped>
.scheme-panel {
  border: 1px solid var(--line);
  background: rgba(12, 30, 46, 0.68);
  clip-path: polygon(16px 0, 100% 0, calc(100% - 16px) 100%, 0 100%);
}

.scheme-panel__head {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.scheme-panel__kicker {
  display: block;
  color: var(--sand);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.scheme-panel__title {
  color: var(--sand-bright);
  font-family: var(--font-display);
  font-size: 22px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.scheme-panel__toggle {
  color: var(--smoke-dim);
  font-size: 20px;
}

.scheme-panel__body {
  overflow: hidden;
  padding: 0 16px 16px;
  border-top: 1px solid var(--line);
}

.scheme-panel__desc {
  margin: 14px 0 0;
  color: var(--smoke-dim);
  font-size: 13px;
  line-height: 1.55;
}
</style>
