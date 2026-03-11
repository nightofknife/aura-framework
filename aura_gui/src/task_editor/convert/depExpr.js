export const DepTypes = Object.freeze({
  NODE: 'node',
  WHEN: 'when',
  STATUS: 'status',
  AND: 'and',
  OR: 'or',
  NOT: 'not'
})

export function parseDependsOn(struct) {
  if (struct == null) {
    return { type: DepTypes.AND, children: [] }
  }

  if (typeof struct === 'string') {
    const trimmed = struct.trim()
    if (trimmed.startsWith('when:')) {
      const expr = trimmed.slice(5).trim()
      return { type: DepTypes.WHEN, expr }
    }
    return { type: DepTypes.NODE, nodeId: struct }
  }

  if (Array.isArray(struct)) {
    return { type: DepTypes.AND, children: struct.map(parseDependsOn) }
  }

  if (typeof struct === 'object') {
    if (struct.and) {
      return { type: DepTypes.AND, children: struct.and.map(parseDependsOn) }
    }
    if (struct.or) {
      return { type: DepTypes.OR, children: struct.or.map(parseDependsOn) }
    }
    if (struct.not) {
      return { type: DepTypes.NOT, child: parseDependsOn(struct.not) }
    }
    const keys = Object.keys(struct)
    if (keys.length === 1) {
      const nodeId = keys[0]
      const raw = String(struct[nodeId] ?? '')
      const statuses = raw.split('|').map((s) => s.trim()).filter(Boolean)
      return { type: DepTypes.STATUS, nodeId, statuses }
    }
  }

  throw new Error('Invalid depends_on structure')
}

export function normalizeDep(expr) {
  if (!expr || typeof expr !== 'object') {
    return expr
  }

  if (expr.type === DepTypes.AND || expr.type === DepTypes.OR) {
    const children = expr.children
      .map(normalizeDep)
      .filter(Boolean)
      .flatMap((child) => {
        if (child && child.type === expr.type) {
          return child.children || []
        }
        return [child]
      })

    if (children.length === 1) {
      return children[0]
    }
    return { ...expr, children }
  }

  if (expr.type === DepTypes.NOT) {
    return { ...expr, child: normalizeDep(expr.child) }
  }

  return expr
}

export function serializeDependsOn(expr) {
  const normalized = normalizeDep(expr)
  if (!normalized) {
    return undefined
  }

  if (normalized.type === DepTypes.AND && (!normalized.children || normalized.children.length === 0)) {
    return undefined
  }

  switch (normalized.type) {
    case DepTypes.NODE:
      return normalized.nodeId
    case DepTypes.WHEN:
      return `when: ${normalized.expr}`
    case DepTypes.STATUS:
      return { [normalized.nodeId]: normalized.statuses.join('|') }
    case DepTypes.AND:
      return { and: normalized.children.map(serializeDependsOn).filter(Boolean) }
    case DepTypes.OR:
      return { or: normalized.children.map(serializeDependsOn).filter(Boolean) }
    case DepTypes.NOT:
      return { not: serializeDependsOn(normalized.child) }
    default:
      return undefined
  }
}
