export function autoLayout(graph, layout, options = {}) {
  const spacingX = options.spacingX || 220
  const spacingY = options.spacingY || 120
  const paddingX = options.paddingX ?? 40
  const paddingY = options.paddingY ?? 40
  const width = options.width || 0
  const height = options.height || 0
  const nodeSize = options.nodeSize || { w: 180, h: 64 }
  const gateSize = options.gateSize || { w: 90, h: 46 }
  const maxItemHeight = Math.max(nodeSize.h, gateSize.h)
  const force = options.force === true

  layout.nodes = layout.nodes || {}
  layout.gates = layout.gates || {}

  const nodes = new Set(Object.keys(graph.nodes || {}))
  const gates = new Set(Object.keys(graph.gates || {}))
  const all = new Set([...nodes, ...gates])
  const edges = (graph.edges || []).filter((edge) => edge.kind !== 'visual_only')

  const indegree = {}
  const outgoing = {}
  for (const id of all) {
    indegree[id] = 0
    outgoing[id] = []
  }

  for (const edge of edges) {
    if (!all.has(edge.from) || !all.has(edge.to)) continue
    outgoing[edge.from].push(edge.to)
    indegree[edge.to] += 1
  }

  const queue = []
  for (const id of all) {
    if (indegree[id] === 0) queue.push(id)
  }

  const layer = {}
  for (const id of all) layer[id] = 0

  while (queue.length) {
    const current = queue.shift()
    for (const next of outgoing[current]) {
      layer[next] = Math.max(layer[next], layer[current] + 1)
      indegree[next] -= 1
      if (indegree[next] === 0) queue.push(next)
    }
  }

  const grouped = {}
  for (const id of all) {
    const l = layer[id] || 0
    if (!grouped[l]) grouped[l] = []
    grouped[l].push(id)
  }

  const layers = Object.keys(grouped).map(Number).sort((a, b) => a - b)
  const layerCount = layers.length || 1

  const availableWidth = Math.max(width - paddingX * 2, nodeSize.w)
  const columns = width
    ? Math.max(1, Math.min(layerCount, Math.floor(availableWidth / spacingX) || 1))
    : layerCount

  const layerHeights = {}
  for (const l of layers) {
    const list = grouped[l] || []
    const count = Math.max(list.length, 1)
    layerHeights[l] = (count - 1) * spacingY + maxItemHeight
  }

  const rowCount = Math.ceil(layerCount / columns)
  const rowHeights = new Array(rowCount).fill(maxItemHeight)
  layers.forEach((l, index) => {
    const row = Math.floor(index / columns)
    rowHeights[row] = Math.max(rowHeights[row], layerHeights[l])
  })

  const rowOffsets = []
  let rowCursor = 0
  for (let i = 0; i < rowHeights.length; i += 1) {
    rowOffsets[i] = rowCursor
    rowCursor += rowHeights[i] + spacingY
  }

  const maxY = height ? Math.max(height - paddingY * 2, maxItemHeight) : 0
  const overflowFactor = height && rowCursor > maxY ? maxY / rowCursor : 1

  layers.forEach((l, layerIndex) => {
    const list = grouped[l] || []
    list.sort()
    const col = layerIndex % columns
    const row = Math.floor(layerIndex / columns)
    const x = paddingX + col * spacingX
    const baseY = paddingY + rowOffsets[row] * overflowFactor
    for (let i = 0; i < list.length; i += 1) {
      const id = list[i]
      const y = baseY + i * spacingY * overflowFactor
      if (nodes.has(id)) {
        if (force || !layout.nodes[id]) layout.nodes[id] = { x, y }
      } else if (gates.has(id)) {
        if (force || !layout.gates[id]) layout.gates[id] = { x, y }
      }
    }
  })

  return layout
}
