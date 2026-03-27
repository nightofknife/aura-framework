import { reactive } from 'vue'
import { getGuiConfig } from '../../config.js'

export function useLayoutStore() {
  const cfg = getGuiConfig()
  const defaultZoom = cfg?.task_editor?.viewport?.default_zoom || 1

  const state = reactive({
    nodes: {},
    gates: {},
    viewport: { x: 0, y: 0, zoom: defaultZoom }
  })

  const setLayout = (layout) => {
    state.nodes = layout.nodes || {}
    state.gates = layout.gates || {}
    state.viewport = layout.viewport || { x: 0, y: 0, zoom: defaultZoom }
  }

  const ensureNode = (id, x = 80, y = 80) => {
    if (!state.nodes[id]) state.nodes[id] = { x, y }
  }

  const ensureGate = (id, x = 80, y = 80) => {
    if (!state.gates[id]) state.gates[id] = { x, y }
  }

  const updateNodePos = (id, pos) => {
    state.nodes[id] = { ...(state.nodes[id] || {}), ...pos }
  }

  const updateGatePos = (id, pos) => {
    state.gates[id] = { ...(state.gates[id] || {}), ...pos }
  }

  const updateViewport = (patch) => {
    state.viewport = { ...(state.viewport || { x: 0, y: 0, zoom: defaultZoom }), ...patch }
  }

  const removeNode = (id) => {
    delete state.nodes[id]
  }

  const removeGate = (id) => {
    delete state.gates[id]
  }

  return {
    state,
    setLayout,
    ensureNode,
    ensureGate,
    updateNodePos,
    updateGatePos,
    updateViewport,
    removeNode,
    removeGate
  }
}
