// === src/composables/useTheme.js ===
import { ref, onMounted, computed } from 'vue';
import { getGuiConfig } from '../config.js';

const cfg = getGuiConfig();
const THEME_KEY = cfg?.theme?.storage_key || 'aura_theme';
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
            const pref = (cfg?.theme?.default || 'system').toLowerCase();
            if (pref === 'dark') {
                applyTheme(true);
            } else if (pref === 'light') {
                applyTheme(false);
            } else {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                applyTheme(prefersDark);
            }
        }
    });

    return {
        isDark: computed(() => isDark.value),
        toggleTheme,
    };
}
// === END src/composables/useTheme.js ===
