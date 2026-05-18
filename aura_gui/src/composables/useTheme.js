import { computed, onMounted, ref } from 'vue'

const themeName = ref('workbench-dark')

function applyTheme() {
  document.documentElement.classList.add('theme-workbench')
  document.documentElement.classList.add('theme-dark')
  document.documentElement.classList.remove('theme-expedition')
}

export function useTheme() {
  onMounted(applyTheme)

  return {
    themeName: computed(() => themeName.value),
    isDark: computed(() => true),
    toggleTheme: () => applyTheme(),
  }
}
