import { parseTaskFile, stringifyTaskFile } from '../convert/yamlCompiler.js'

export async function loadTaskFile(api, planName, path) {
  const text = await api.getFileContent(planName, path)
  return parseTaskFile(text, path)
}

export async function saveTaskFile(api, planName, path, taskFile) {
  const text = stringifyTaskFile(taskFile)
  await api.saveFileContent(planName, path, text)
  return text
}
