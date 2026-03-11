import { reactive } from 'vue'

export function useValidationStore() {
  const state = reactive({
    errors: [],
    warnings: []
  })

  const setErrors = (errors) => { state.errors = errors }
  const setWarnings = (warnings) => { state.warnings = warnings }
  const clear = () => { state.errors = []; state.warnings = [] }

  return { state, setErrors, setWarnings, clear }
}
