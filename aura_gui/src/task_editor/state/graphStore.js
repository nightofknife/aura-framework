import { reactive } from 'vue'

export function useGraphStore() {
  const state = reactive({
    gates: {},
    edges: [],
    selectedEdge: null
  })

  const setGraph = (graph) => {
    state.gates = graph.gates || {}
    state.edges = graph.edges || []
  }

  const addGate = (gate) => {
    state.gates[gate.id] = gate
  }

  const updateGate = (gateId, patch) => {
    if (!state.gates[gateId]) return
    state.gates[gateId] = { ...state.gates[gateId], ...patch }
  }

  const removeGate = (gateId) => {
    delete state.gates[gateId]
    state.edges = state.edges.filter((edge) => edge.from !== gateId && edge.to !== gateId)
  }

  const addEdge = (edge) => {
    const exists = state.edges.some((e) => e.from === edge.from && e.to === edge.to && e.kind === edge.kind)
    if (!exists) state.edges.push(edge)
  }

  const removeEdge = (edge) => {
    state.edges = state.edges.filter((e) => !(e.from === edge.from && e.to === edge.to && e.kind === edge.kind))
  }

  const removeEdgesForNode = (nodeId) => {
    state.edges = state.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId)
  }

  const removeEdgesTo = (targetId, kind = null) => {
    state.edges = state.edges.filter((edge) => {
      if (edge.to !== targetId) return true
      if (!kind) return false
      return edge.kind !== kind
    })
  }

  const clearGateNodeRefs = (nodeId) => {
    for (const gate of Object.values(state.gates)) {
      if (gate.type === 'status' && gate.node_id === nodeId) {
        gate.node_id = ''
      }
    }
  }

  const clearGraph = () => {
    state.gates = {}
    state.edges = []
  }

  return {
    state,
    setGraph,
    addGate,
    updateGate,
    removeGate,
    addEdge,
    removeEdge,
    removeEdgesForNode,
    removeEdgesTo,
    clearGateNodeRefs,
    clearGraph
  }
}
