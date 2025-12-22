<template>
  <div
    class="gate-card"
    :class="{ selected }"
    :style="style"
    @pointerdown="onPointerDown"
    @click.stop="onSelect"
  >
    <div v-if="showInputPort" class="port input" @pointerup.stop="onConnectEnd('input')"></div>
    <div v-if="showObservePort" class="port observe" @pointerup.stop="onConnectEnd('observe')"></div>
    <div class="port output" @pointerdown.stop="onConnectStart"></div>
    <button class="gate-delete" @pointerdown.stop @click.stop="onDelete">×</button>
    <div class="gate-label">{{ gateLabel }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  gate: { type: Object, required: true },
  position: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  zoom: { type: Number, default: 1 },
  pan: { type: Object, default: () => ({ x: 0, y: 0 }) }
})

const emit = defineEmits(['select', 'move', 'delete', 'connect-start', 'connect-end'])
const dragging = ref(false)
const offset = ref({ x: 0, y: 0 })

const gateLabel = computed(() => {
  const map = {
    and: '并且',
    or: '或者',
    not: '非',
    when: '条件',
    status: '状态'
  }
  return map[props.gate.type] || props.gate.type
})

const showObservePort = computed(() => props.gate.type === 'status')
const showInputPort = computed(() => props.gate.type !== 'status')

const style = computed(() => ({
  transform: `translate(${props.position.x}px, ${props.position.y}px)`
}))

const onSelect = () => emit('select', props.gate.id)
const onDelete = () => emit('delete', props.gate.id)
const onConnectStart = () => emit('connect-start', { id: props.gate.id, port: 'output' })
const onConnectEnd = (port) => emit('connect-end', { id: props.gate.id, port })

const onPointerDown = (event) => {
  if (event.button !== 0) return
  event.stopPropagation()
  dragging.value = true
  offset.value = {
    x: event.clientX - (props.position.x * props.zoom + props.pan.x),
    y: event.clientY - (props.position.y * props.zoom + props.pan.y)
  }
  event.currentTarget.setPointerCapture(event.pointerId)
  event.currentTarget.addEventListener('pointermove', onPointerMove)
  event.currentTarget.addEventListener('pointerup', onPointerUp)
}

const onPointerMove = (event) => {
  if (!dragging.value) return
  emit('move', {
    id: props.gate.id,
    x: (event.clientX - props.pan.x - offset.value.x) / props.zoom,
    y: (event.clientY - props.pan.y - offset.value.y) / props.zoom
  })
}

const onPointerUp = (event) => {
  dragging.value = false
  event.currentTarget.releasePointerCapture(event.pointerId)
  event.currentTarget.removeEventListener('pointermove', onPointerMove)
  event.currentTarget.removeEventListener('pointerup', onPointerUp)
}
</script>

<style scoped>
.gate-card {
  position: absolute;
  width: 90px;
  height: 46px;
  border-radius: 20px;
  border: 1px solid var(--border-frosted);
  background: rgba(8, 217, 214, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-primary);
  cursor: grab;
  user-select: none;
}
.port {
  position: absolute;
  width: 8px;
  height: 16px;
  background: #fff;
  border: 2px solid rgba(8, 217, 214, 0.8);
}
.port.input {
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  border-radius: 999px 0 0 999px;
  border-right: 0;
}
.port.observe {
  left: -8px;
  bottom: -8px;
  border-color: rgba(251, 146, 60, 0.9);
  border-radius: 999px 0 0 999px;
  border-right: 0;
}
.port.output {
  right: -8px;
  top: 50%;
  transform: translateY(-50%);
  cursor: crosshair;
  border-radius: 0 999px 999px 0;
  border-left: 0;
}
.gate-delete {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.08);
  color: var(--error);
  font-weight: 700;
  line-height: 16px;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur) var(--ease);
}
.gate-card:hover .gate-delete {
  opacity: 1;
  pointer-events: auto;
}
.gate-card.selected {
  border-color: var(--secondary-accent);
  box-shadow: 0 0 0 2px rgba(8, 217, 214, 0.2);
}
</style>
