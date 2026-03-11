function getLayoutPathForTaskFile(taskFilePath) {
  const normalized = taskFilePath.replace(/\\/g, '/')
  const trimmed = normalized.startsWith('tasks/') ? normalized.slice('tasks/'.length) : normalized
  const noExt = trimmed.replace(/\.ya?ml$/i, '')
  return `tasks/.ui/${noExt}.layout.json`
}

export async function loadLayout(api, planName, taskFilePath) {
  const path = getLayoutPathForTaskFile(taskFilePath)
  try {
    const raw = await api.getFileContent(planName, path)
    return JSON.parse(raw)
  } catch (err) {
    return { version: 1, file: taskFilePath, tasks: {} }
  }
}

export async function saveLayout(api, planName, taskFilePath, layout) {
  const path = getLayoutPathForTaskFile(taskFilePath)
  const payload = JSON.stringify(layout, null, 2)
  await api.saveFileContent(planName, path, payload)
}

export { getLayoutPathForTaskFile }
