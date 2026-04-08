import { computed, onMounted, ref } from 'vue'

const themeName = ref('expedition')

function applyTheme() {
  document.documentElement.classList.add('theme-expedition')
  document.documentElement.classList.remove('theme-dark')
}

export function useTheme() {
  onMounted(applyTheme)

  return {
    themeName: computed(() => themeName.value),
    isDark: computed(() => true),
    toggleTheme: () => applyTheme(),
  }
}
