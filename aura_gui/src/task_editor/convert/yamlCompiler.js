import YAML from 'yaml'
import { parseDependsOn, serializeDependsOn, DepTypes } from './depExpr.js'

export function parseTaskFile(yamlText, filePath) {
  const raw = YAML.parse(yamlText || '') || {}
  const tasks = {}

  for (const [taskKey, taskDef] of Object.entries(raw)) {
    if (!taskDef || typeof taskDef !== 'object') {
      continue
    }
    const steps = taskDef.steps || {}
    const nodeOrder = Object.keys(steps)
    const nodes = {}

    for (const [nodeId, nodeDef] of Object.entries(steps)) {
      const dependsOn = nodeDef.depends_on ? parseDependsOn(nodeDef.depends_on) : { type: DepTypes.AND, children: [] }
      nodes[nodeId] = {
        id: nodeId,
        action: nodeDef.action || '',
        params: nodeDef.params,
        loop: nodeDef.loop,
        outputs: nodeDef.outputs,
        retry: nodeDef.retry,
        depends_on: dependsOn
      }
    }

    tasks[taskKey] = {
      meta: taskDef.meta || {},
      execution_mode: taskDef.execution_mode,
      returns: taskDef.returns,
      steps: nodes,
      nodeOrder
    }
  }

  return { path: filePath, tasks }
}

export function stringifyTaskFile(taskFile) {
  const output = {}
  for (const [taskKey, taskDef] of Object.entries(taskFile.tasks || {})) {
    const steps = {}
    const ordered = taskDef.nodeOrder && taskDef.nodeOrder.length
      ? taskDef.nodeOrder
      : Object.keys(taskDef.steps || {})

    for (const nodeId of ordered) {
      const node = taskDef.steps[nodeId]
      if (!node) {
        continue
      }
      const entry = {}
      if (node.action) entry.action = node.action
      if (node.params) entry.params = node.params
      if (node.loop) entry.loop = node.loop
      if (node.outputs) entry.outputs = node.outputs
      if (node.retry) entry.retry = node.retry
      const dependsOn = serializeDependsOn(node.depends_on)
      if (dependsOn !== undefined) {
        entry.depends_on = dependsOn
      }
      steps[nodeId] = entry
    }

    const taskOut = {}
    if (taskDef.meta && Object.keys(taskDef.meta).length) taskOut.meta = taskDef.meta
    if (taskDef.execution_mode) taskOut.execution_mode = taskDef.execution_mode
    if (taskDef.returns !== undefined) taskOut.returns = taskDef.returns
    taskOut.steps = steps
    output[taskKey] = taskOut
  }

  return YAML.stringify(output)
}
