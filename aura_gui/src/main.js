// src/main.js
import { createApp } from 'vue'
import App from './App.vue'

// directives
import ripple from './directives/ripple.js'
import tilt   from './directives/tilt.js'
import reveal from './directives/reveal.js'

// styles
import './styles/aetherium-theme.css'

const app = createApp(App)
app.directive('ripple', ripple)
app.directive('tilt', tilt)
app.directive('reveal', reveal)

app.mount('#app')
