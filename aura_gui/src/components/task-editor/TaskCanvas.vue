<template>
  <div class="task-canvas" ref="canvasRef" @pointerdown="onPanStart">
    <div class="canvas-pan" :style="panStyle">
      <div class="canvas-content" :style="contentStyle">
        <EdgeLayer :edges="edges" :layout="layout" :nodes="nodes" :gates="gates" @edge-click="onEdgeClick" />

        <svg v-if="linking" class="ghost-layer">
          <line
            :x1="linking.start.x"
            :y1="linking.start.y"
            :x2="pointer.x"
            :y2="pointer.y"
          />
        </svg>

        <NodeCard
          v-for="node in nodeList"
          :key="node.id"
          :node="node"
          :position="layout.nodes[node.id] || { x: 60, y: 60 }"
          :selected="selected?.type === 'node' && selected.id === node.id"
          :zoom="zoom"
          :pan="pan"
          @select="onSelectNode"
          @move="onMoveNode"
          @delete="onRemoveNode"
          @connect-start="onConnectStart"
          @connect-end="onConnectEnd"
        />

        <GateCard
          v-for="gate in gateList"
          :key="gate.id"
          :gate="gate"
          :position="layout.gates[gate.id] || { x: 60, y: 60 }"
          :selected="selected?.type === 'gate' && selected.id === gate.id"
          :zoom="zoom"
          :pan="pan"
          @select="onSelectGate"
          @move="onMoveGate"
          @delete="onRemoveGate"
          @connect-start="onConnectStart"
          @connect-end="onConnectEnd"
        />
      </div>
    </div>

    <div class="connect-hint">
      <span>拖拽端口创建连线，点击连线可删除</span>
    </div>

    <div class="zoom-controls">
      <button class="btn btn-ghost btn-mini" @click="emitZoom('out')">-</button>
      <div class="zoom-label">{{ zoomLabel }}</div>
      <button class="btn btn-ghost btn-mini" @click="emitZoom('in')">+</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'
import { getGuiConfig } from '../../config.js'
import NodeCard from './NodeCard.vue'
import GateCard from './GateCard.vue'
import EdgeLayer from './EdgeLayer.vue'

const props = defineProps({
  nodes: { type: Object, default: () => ({}) },
  gates: { type: Object, default: () => ({}) },
  edges: { type: Array, default: () => [] },
  layout: { type: Object, required: true },
  viewport: { type: Object, default: () => ({ x: 0, y: 0, zoom: 1 }) },
  selected: { type: Object, default: () => ({ type: 'task', id: '' }) }
})

const emit = defineEmits([
  'select-node',
  'select-gate',
  'move-node',
  'move-gate',
  'connect',
  'remove-edge',
  'remove-node',
  'remove-gate',
  'zoom',
  'pan'
])

const nodeList = computed(() => Object.values(props.nodes))
const gateList = computed(() => Object.values(props.gates))

const onSelectNode = (nodeId) => {
  emit('select-node', nodeId)
}

const onSelectGate = (gateId) => {
  emit('select-gate', gateId)
}

const onMoveNode = (payload) => emit('move-node', payload)
const onMoveGate = (payload) => emit('move-gate', payload)
const onRemoveNode = (nodeId) => emit('remove-node', nodeId)
const onRemoveGate = (gateId) => emit('remove-gate', gateId)

const onEdgeClick = (edge) => {
  emit('remove-edge', edge)
}

const canvasRef = ref(null)
const linking = ref(null)
const pointer = ref({ x: 0, y: 0 })
const cfg = getGuiConfig()
const minZoom = cfg?.task_editor?.viewport?.min_zoom || 0.2
const zoom = computed(() => Math.max(minZoom, props.viewport?.zoom || 1))
const pan = computed(() => ({
  x: props.viewport?.x || 0,
  y: props.viewport?.y || 0
}))
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)
const contentStyle = computed(() => ({
  transform: `scale(${zoom.value})`,
  transformOrigin: '0 0'
}))
const panStyle = computed(() => ({
  transform: `translate(${pan.value.x}px, ${pan.value.y}px)`
}))

const NODE_SIZE = { w: 180, h: 64 }
const GATE_SIZE = { w: 90, h: 46 }
const PORT_OFFSET = 4

const getOutputPos = (id) => {
  if (props.layout.nodes[id]) {
    const pos = props.layout.nodes[id]
    return { x: pos.x + NODE_SIZE.w + PORT_OFFSET, y: pos.y + NODE_SIZE.h / 2 }
  }
  if (props.layout.gates[id]) {
    const pos = props.layout.gates[id]
    return { x: pos.x + GATE_SIZE.w + PORT_OFFSET, y: pos.y + GATE_SIZE.h / 2 }
  }
  return null
}

const getInputPos = (id, port) => {
  if (props.layout.nodes[id]) {
    const pos = props.layout.nodes[id]
    return { x: pos.x - PORT_OFFSET, y: pos.y + NODE_SIZE.h / 2 }
  }
  if (props.layout.gates[id]) {
    const pos = props.layout.gates[id]
    if (port === 'observe') {
      return { x: pos.x - PORT_OFFSET, y: pos.y + GATE_SIZE.h }
    }
    return { x: pos.x - PORT_OFFSET, y: pos.y + GATE_SIZE.h / 2 }
  }
  return null
}

const getSourceType = (id) => {
  if (props.nodes[id]) return 'node'
  if (props.gates[id]) return 'gate'
  return 'unknown'
}

const onConnectStart = ({ id }) => {
  const start = getOutputPos(id)
  if (!start) return
  linking.value = { from: id, start, type: getSourceType(id) }
  pointer.value = { ...start }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', cancelLink)
}

const onConnectEnd = ({ id, port }) => {
  if (!linking.value) return
  const target = getInputPos(id, port)
  if (!target) {
    cancelLink()
    return
  }
  if (port === 'observe' && linking.value.type !== 'node') {
    cancelLink()
    return
  }
  const payload = { from: linking.value.from, to: id }
  if (port === 'observe') {
    payload.kind = 'visual_only'
  }
  emit('connect', payload)
  cancelLink()
}

const onPointerMove = (event) => {
  if (!linking.value || !canvasRef.value) return
  const rect = canvasRef.value.getBoundingClientRect()
  pointer.value = {
    x: (event.clientX - rect.left - pan.value.x) / zoom.value,
    y: (event.clientY - rect.top - pan.value.y) / zoom.value
  }
}

const cancelLink = () => {
  linking.value = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', cancelLink)
}

const emitZoom = (action) => emit('zoom', action)

const panState = ref(null)
const isInteractiveTarget = (event) => {
  const target = event.target
  if (!(target instanceof Element)) return false
  if (target.closest('.node-card, .gate-card, .port, .node-delete, .gate-delete, .zoom-controls, .connect-hint')) {
    return true
  }
  if (target.classList?.contains('edge')) return true
  return false
}

const onPanStart = (event) => {
  if (event.button !== 0) return
  if (isInteractiveTarget(event)) return
  panState.value = {
    startX: event.clientX,
    startY: event.clientY,
    originX: pan.value.x,
    originY: pan.value.y
  }
  event.currentTarget.setPointerCapture(event.pointerId)
  window.addEventListener('pointermove', onPanMove)
  window.addEventListener('pointerup', onPanEnd)
}

const onPanMove = (event) => {
  if (!panState.value) return
  const dx = event.clientX - panState.value.startX
  const dy = event.clientY - panState.value.startY
  emit('pan', { x: panState.value.originX + dx, y: panState.value.originY + dy })
}

const onPanEnd = () => {
  panState.value = null
  window.removeEventListener('pointermove', onPanMove)
  window.removeEventListener('pointerup', onPanEnd)
}

const getCanvasRect = () => canvasRef.value?.getBoundingClientRect() || null

defineExpose({ getCanvasRect })

onBeforeUnmount(() => {
  cancelLink()
  onPanEnd()
})
</script>

<style scoped>
.task-canvas {
  position: relative;
  min-height: 560px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-frosted);
  background: rgba(255, 255, 255, 0.6);
  overflow: hidden;
}
.canvas-content {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.canvas-pan {
  position: absolute;
  inset: 0;
}
.ghost-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.ghost-layer line {
  stroke: rgba(88, 101, 242, 0.6);
  stroke-width: 2;
  stroke-dasharray: 6 4;
}
.connect-hint {
  position: absolute;
  bottom: 12px;
  right: 16px;
  background: rgba(88, 101, 242, 0.1);
  border: 1px solid rgba(88, 101, 242, 0.2);
  color: var(--text-secondary);
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
}
.zoom-controls {
  position: absolute;
  left: 12px;
  bottom: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid var(--border-frosted);
  border-radius: 999px;
  padding: 4px 6px;
}
.zoom-label {
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 44px;
  text-align: center;
}
.btn-mini {
  padding: 2px 8px;
  font-size: 12px;
}
</style>
