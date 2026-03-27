import { createApp } from 'vue'
import { createPinia } from 'pinia'
import VueVirtualScroller from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'

import App from './App.vue'
import { loadGuiConfig } from './config.js'
import ripple from './directives/ripple.js'
import tilt from './directives/tilt.js'
import reveal from './directives/reveal.js'

import './styles/aetherium-theme.css'
import './style.css'

async function bootstrap() {
  await loadGuiConfig()

  const app = createApp(App)
  app.use(createPinia())
  app.use(VueVirtualScroller)
  app.directive('ripple', ripple)
  app.directive('tilt', tilt)
  app.directive('reveal', reveal)
  app.mount('#app')
}

bootstrap()
