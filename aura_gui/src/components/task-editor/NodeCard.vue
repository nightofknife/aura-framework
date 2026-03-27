<template>
  <div
    class="node-card"
    :class="{ selected }"
    :style="style"
    @pointerdown="onPointerDown"
    @click.stop="onSelect"
  >
    <div class="port input" @pointerup.stop="onConnectEnd('input')"></div>
    <div class="port output" @pointerdown.stop="onConnectStart"></div>
    <button class="node-delete" @pointerdown.stop @click.stop="onDelete">×</button>
    <div class="node-title">{{ node.id }}</div>
    <div class="node-action">{{ node.action || '未设置动作' }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  node: { type: Object, required: true },
  position: { type: Object, required: true },
  selected: { type: Boolean, default: false },
  zoom: { type: Number, default: 1 },
  pan: { type: Object, default: () => ({ x: 0, y: 0 }) }
})

const emit = defineEmits(['select', 'move', 'delete', 'connect-start', 'connect-end'])
const dragging = ref(false)
const offset = ref({ x: 0, y: 0 })

const style = computed(() => ({
  transform: `translate(${props.position.x}px, ${props.position.y}px)`
}))

const onSelect = () => emit('select', props.node.id)
const onDelete = () => emit('delete', props.node.id)
const onConnectStart = () => emit('connect-start', { id: props.node.id, port: 'output' })
const onConnectEnd = () => emit('connect-end', { id: props.node.id, port: 'input' })

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
    id: props.node.id,
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
.node-card {
  position: absolute;
  width: 180px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--border-frosted);
  background: rgba(255, 255, 255, 0.85);
  box-shadow: var(--shadow-card);
  cursor: grab;
  user-select: none;
}
.node-delete {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid rgba(220, 38, 38, 0.35);
  background: rgba(220, 38, 38, 0.08);
  color: var(--error);
  font-weight: 700;
  line-height: 18px;
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur) var(--ease);
}
.node-card:hover .node-delete {
  opacity: 1;
  pointer-events: auto;
}
.node-card.selected {
  border-color: var(--primary-accent);
  box-shadow: 0 0 0 2px rgba(88, 101, 242, 0.25);
}
.port {
  position: absolute;
  width: 8px;
  height: 16px;
  background: #fff;
  border: 2px solid rgba(88, 101, 242, 0.7);
}
.port.input {
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
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
.node-title {
  font-size: 12px;
  color: var(--text-secondary);
}
.node-action {
  font-weight: 600;
  margin-top: 4px;
}
</style>
