<template>
  <svg class="edge-layer">
    <defs>
      <marker
        id="edge-arrow"
        markerWidth="10"
        markerHeight="10"
        refX="8"
        refY="3"
        orient="auto"
        markerUnits="strokeWidth"
      >
        <path d="M0,0 L0,6 L8,3 z" fill="currentColor" />
      </marker>
    </defs>
    <line
      v-for="(edge, idx) in drawableEdges"
      :key="`${edge.from}-${edge.to}-${idx}`"
      :x1="edge.x1"
      :y1="edge.y1"
      :x2="edge.x2"
      :y2="edge.y2"
      :class="edge.kind === 'visual_only' ? 'edge visual' : 'edge'"
      :marker-end="edge.kind === 'visual_only' ? '' : 'url(#edge-arrow)'"
      @click.stop="$emit('edge-click', edge)"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  edges: { type: Array, default: () => [] },
  layout: { type: Object, required: true },
  nodes: { type: Object, default: () => ({}) },
  gates: { type: Object, default: () => ({}) }
})

defineEmits(['edge-click'])

const NODE_SIZE = { w: 180, h: 64 }
const GATE_SIZE = { w: 90, h: 46 }
const PORT_OFFSET = 4

const getPort = (id, side, observe = false) => {
  if (props.layout.nodes[id]) {
    const pos = props.layout.nodes[id]
    if (side === 'output') {
      return { x: pos.x + NODE_SIZE.w + PORT_OFFSET, y: pos.y + NODE_SIZE.h / 2 }
    }
    return { x: pos.x - PORT_OFFSET, y: pos.y + NODE_SIZE.h / 2 }
  }
  if (props.layout.gates[id]) {
    const pos = props.layout.gates[id]
    if (side === 'output') {
      return { x: pos.x + GATE_SIZE.w + PORT_OFFSET, y: pos.y + GATE_SIZE.h / 2 }
    }
    if (observe) {
      return { x: pos.x - PORT_OFFSET, y: pos.y + GATE_SIZE.h }
    }
    return { x: pos.x - PORT_OFFSET, y: pos.y + GATE_SIZE.h / 2 }
  }
  return null
}

const drawableEdges = computed(() => {
  return props.edges
    .map((edge) => {
      const isObserve = edge.kind === 'visual_only' && props.gates[edge.to]?.type === 'status'
      const from = getPort(edge.from, 'output')
      const to = getPort(edge.to, 'input', isObserve)
      if (!from || !to) return null
      return { ...edge, x1: from.x, y1: from.y, x2: to.x, y2: to.y }
    })
    .filter(Boolean)
})
</script>

<style scoped>
.edge-layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: auto;
  color: rgba(30, 35, 48, 0.4);
}
.edge {
  stroke: rgba(30, 35, 48, 0.4);
  stroke-width: 2;
  cursor: pointer;
  pointer-events: stroke;
}
.edge.visual {
  stroke-dasharray: 6 4;
  stroke: rgba(30, 35, 48, 0.25);
}
</style>
