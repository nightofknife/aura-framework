<template>
  <article class="task-ticket" @click="$emit('select')">
    <span class="task-ticket__serial">{{ mark }}</span>
    <span class="task-ticket__pin" :class="{ 'is-on': starred }" @click.stop="$emit('toggle-fav')">
      {{ starred ? 'PIN' : 'TAG' }}
    </span>

    <div class="task-ticket__paper">
      <span class="task-ticket__plan">{{ plan }}</span>
      <h3 class="task-ticket__title">{{ title }}</h3>
      <p class="task-ticket__desc">{{ description || 'No description available for this task.' }}</p>
    </div>

    <footer class="task-ticket__foot">
      <span v-if="tag" class="pill">{{ tag }}</span>
      <span class="task-ticket__hint">open brief</span>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  plan: { type: String, default: '' },
  tag: { type: String, default: '' },
  starred: Boolean,
})

const mark = computed(() => {
  const source = props.title || props.plan || 'TSK'
  return String(source).replace(/[^A-Za-z0-9]/g, '').slice(0, 3).toUpperCase() || 'TSK'
})
</script>

<style scoped>
.task-ticket {
  position: relative;
  display: flex;
  min-height: 210px;
  flex-direction: column;
  gap: 12px;
  padding: 14px 14px 14px 52px;
  border: 1px solid rgba(224, 214, 186, 0.1);
  background:
    linear-gradient(180deg, rgba(61, 69, 73, 0.9), rgba(39, 47, 50, 0.92));
  box-shadow: var(--shadow-plate), var(--shadow-inset);
  cursor: pointer;
  transition:
    transform var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

.task-ticket:hover {
  transform: translateY(-2px) rotate(-0.4deg);
  border-color: rgba(224, 214, 186, 0.22);
}

.task-ticket__serial {
  position: absolute;
  left: 14px;
  top: 14px;
  bottom: 14px;
  display: flex;
  width: 28px;
  align-items: center;
  justify-content: center;
  background: linear-gradient(180deg, rgba(199, 104, 63, 0.86), rgba(137, 70, 44, 0.92));
  color: #f0e5d2;
  font-family: var(--font-display);
  font-size: 20px;
  letter-spacing: 0.08em;
  writing-mode: vertical-rl;
  text-orientation: mixed;
}

.task-ticket__pin {
  position: absolute;
  top: 12px;
  right: 12px;
  min-height: 22px;
  padding: 0 8px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background: rgba(31, 38, 41, 0.88);
  color: var(--text-soft);
  font-family: var(--font-mono);
  font-size: 9px;
  line-height: 22px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.task-ticket__pin.is-on {
  background: rgba(199, 104, 63, 0.18);
  color: var(--paper-2);
  border-color: rgba(199, 104, 63, 0.22);
}

.task-ticket__paper {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  padding: 12px 12px 10px;
  border: 1px solid rgba(224, 214, 186, 0.12);
  background:
    linear-gradient(180deg, rgba(207, 194, 154, 0.14), rgba(207, 194, 154, 0.07)),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0.025) 1px, transparent 1px, transparent 7px);
}

.task-ticket__plan {
  color: var(--paper);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.task-ticket__title {
  margin: 0;
  color: var(--paper-2);
  font-family: var(--font-display);
  font-size: 30px;
  letter-spacing: 0.08em;
  line-height: 0.9;
  text-transform: uppercase;
}

.task-ticket__desc {
  margin: 0;
  color: var(--text-main);
  font-size: 13px;
  line-height: 1.65;
}

.task-ticket__foot {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.task-ticket__hint {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}
</style>
