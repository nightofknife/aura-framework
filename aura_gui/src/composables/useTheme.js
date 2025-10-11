// === src/composables/useTheme.js ===
import { ref, onMounted, computed } from 'vue';

const THEME_KEY = 'aura_theme';
const isDark = ref(false);

export function useTheme() {
    const applyTheme = (dark) => {
        isDark.value = dark;
        document.documentElement.classList.toggle('theme-dark', dark);
        localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light');
    };

    const toggleTheme = () => {
        applyTheme(!isDark.value);
    };

    onMounted(() => {
        const savedTheme = localStorage.getItem(THEME_KEY);
        if (savedTheme) {
            applyTheme(savedTheme === 'dark');
        } else {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            applyTheme(prefersDark);
        }
    });

    return {
        isDark: computed(() => isDark.value),
        toggleTheme,
    };
}
// === END src/composables/useTheme.js ===
