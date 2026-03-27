// src/main.js
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { loadGuiConfig } from './config.js'

// directives
import ripple from './directives/ripple.js'
import tilt   from './directives/tilt.js'
import reveal from './directives/reveal.js'

// virtual scroller
import VueVirtualScroller from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

// styles
import './styles/aetherium-theme.css'

async function bootstrap() {
  await loadGuiConfig()
  const app = createApp(App)
  const pinia = createPinia()

  app.use(pinia)
  app.use(VueVirtualScroller)
  app.directive('ripple', ripple)
  app.directive('tilt', tilt)
  app.directive('reveal', reveal)
  app.mount('#app')
}

bootstrap()
