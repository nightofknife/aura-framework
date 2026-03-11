import { DepTypes } from './depExpr.js'

export function createEmptyGraph() {
  return { gates: {}, edges: [] }
}

export function depExprToGraph(nodeId, expr, graph, gateIdFactory) {
  const emit = (current, parentId) => {
    if (!current) {
      return
    }

    if (current.type === DepTypes.NODE) {
      graph.edges.push({ from: current.nodeId, to: parentId })
      return
    }

    if (current.type === DepTypes.WHEN) {
      const gateId = gateIdFactory('when')
      graph.gates[gateId] = { id: gateId, type: 'when', expr: current.expr }
      graph.edges.push({ from: gateId, to: parentId })
      return
    }

    if (current.type === DepTypes.STATUS) {
      const gateId = gateIdFactory('status')
      graph.gates[gateId] = {
        id: gateId,
        type: 'status',
        node_id: current.nodeId,
        statuses: current.statuses
      }
      graph.edges.push({ from: gateId, to: parentId })
      graph.edges.push({ from: current.nodeId, to: gateId, kind: 'visual_only' })
      return
    }

    if (current.type === DepTypes.NOT) {
      const gateId = gateIdFactory('not')
      graph.gates[gateId] = { id: gateId, type: 'not' }
      graph.edges.push({ from: gateId, to: parentId })
      emit(current.child, gateId)
      return
    }

    if (current.type === DepTypes.AND || current.type === DepTypes.OR) {
      const gateId = gateIdFactory(current.type)
      graph.gates[gateId] = { id: gateId, type: current.type }
      graph.edges.push({ from: gateId, to: parentId })
      for (const child of current.children || []) {
        emit(child, gateId)
      }
      return
    }
  }

  const root = expr
  if (!root) {
    return
  }

  if (root.type === DepTypes.AND && (!root.children || root.children.length === 0)) {
    return
  }

  emit(root, nodeId)
}

export function buildDepExprFromGraph(nodeId, graph) {
  const incoming = graph.edges.filter((edge) => edge.to === nodeId && edge.kind !== 'visual_only')
  if (incoming.length === 0) {
    return { type: DepTypes.AND, children: [] }
  }

  const roots = incoming.map((edge) => edge.from)
  const exprs = roots.map((rootId) => rootToExpr(rootId, graph))

  if (exprs.length === 1) {
    return exprs[0]
  }

  return { type: DepTypes.AND, children: exprs }
}

function rootToExpr(rootId, graph) {
  if (graph.gates[rootId]) {
    return gateToExpr(rootId, graph)
  }
  return { type: DepTypes.NODE, nodeId: rootId }
}

function gateToExpr(gateId, graph) {
  const gate = graph.gates[gateId]
  if (!gate) {
    return { type: DepTypes.NODE, nodeId: gateId }
  }

  if (gate.type === 'when') {
    return { type: DepTypes.WHEN, expr: gate.expr || '' }
  }

  if (gate.type === 'status') {
    return { type: DepTypes.STATUS, nodeId: gate.node_id || '', statuses: gate.statuses || [] }
  }

  const inputs = graph.edges.filter((edge) => edge.to === gateId && edge.kind !== 'visual_only')
  const children = inputs.map((edge) => rootToExpr(edge.from, graph))

  if (gate.type === 'not') {
    return { type: DepTypes.NOT, child: children[0] }
  }

  if (gate.type === 'or') {
    return { type: DepTypes.OR, children }
  }

  return { type: DepTypes.AND, children }
}
