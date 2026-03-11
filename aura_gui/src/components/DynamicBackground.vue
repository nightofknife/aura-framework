<template>
  <canvas ref="canvasEl" class="dynamic-background"></canvas>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getGuiConfig } from '../config.js'

const props = defineProps({
  density: { type: Number, default: 2.0 },
  speed: { type: Number, default: 0.4 },
  strength: { type: Number, default: 0.8 },
  mousePush: { type: Number, default: 30 },
  dust: { type: Number, default: 50 },
})

const canvasEl = ref(null)

const clamp = (value, min, max, fallback) => {
  const num = Number(value)
  if (!Number.isFinite(num)) return fallback
  return Math.min(max, Math.max(min, num))
}

onMounted(() => {
  const cfg = getGuiConfig()
  const settings = {
    density: clamp(cfg?.background?.density, 0.5, 4, props.density),
    speed: clamp(cfg?.background?.speed, 0, 3, props.speed),
    strength: clamp(cfg?.background?.strength, 0, 2, props.strength),
    mousePush: clamp(cfg?.background?.mouse_push, 0, 80, props.mousePush),
    dust: Math.round(clamp(cfg?.background?.dust, 0, 200, props.dust)),
  }

  const cvs = canvasEl.value
  if (!cvs) return
  const ctx = cvs.getContext('2d', { alpha: true })
  if (!ctx) return

  let dpr = 1
  let W = 0
  let H = 0
  let t = 0
  let rafId = 0
  let visible = true

  const pickPalette = () => {
    const dark = document.documentElement.classList.contains('theme-dark')
    const baseHue = (dark ? 236 : 196) + Math.sin(t * 0.12) * 6
    const line = `hsla(${baseHue}, ${dark ? 48 : 42}%, ${dark ? 74 : 54}%, ${dark ? 0.28 : 0.26})`
    const glow = `hsla(${dark ? baseHue - 10 : baseHue + 10}, ${dark ? 70 : 60}%, ${dark ? 58 : 66}%, ${dark ? 0.16 : 0.12})`
    const dust1 = `hsla(${baseHue + 20}, 80%, ${dark ? 74 : 40}%, ${dark ? 0.85 : 0.55})`
    const dust2 = `hsla(${baseHue - 40}, 90%, ${dark ? 70 : 38}%, ${dark ? 0.75 : 0.50})`
    return { line, glow, dust1, dust2 }
  }

  const resize = () => {
    const maxDpr = cfg?.background?.max_dpr || 2
    dpr = Math.max(1, Math.min(maxDpr, window.devicePixelRatio || 1))
    W = cvs.width = Math.floor(window.innerWidth * dpr)
    H = cvs.height = Math.floor(window.innerHeight * dpr)
    cvs.style.width = window.innerWidth + 'px'
    cvs.style.height = window.innerHeight + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  const mouse = { x: window.innerWidth / 2, y: window.innerHeight / 2, tx: null, ty: null, t: 0, active: false }
  const onMove = (e) => {
    mouse.tx = e.clientX
    mouse.ty = e.clientY
    mouse.t = performance.now()
    mouse.active = true
  }
  const onLeave = () => { mouse.active = false }
  window.addEventListener('pointermove', onMove, { passive: true })
  window.addEventListener('pointerleave', onLeave, { passive: true })

  const stars = []
  const initStars = () => {
    stars.length = 0
    for (let i = 0; i < settings.dust; i++) {
      stars.push({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        r: Math.random() < 0.65 ? 1 : 1.6,
        vx: (Math.random() - 0.5) * 0.12,
        vy: (Math.random() - 0.5) * 0.12,
        tw: 0.6 + Math.random() * 1.0,
        ph: Math.random() * Math.PI * 2,
        c: Math.random() < 0.5 ? 'dust1' : 'dust2',
      })
    }
  }

  function drawStars(palette) {
    const vw = window.innerWidth
    const vh = window.innerHeight
    for (const s of stars) {
      s.x += s.vx
      s.y += s.vy
      if (s.x < -2) s.x = vw + 2
      if (s.x > vw + 2) s.x = -2
      if (s.y < -2) s.y = vh + 2
      if (s.y > vh + 2) s.y = -2
      const alpha = 0.5 + 0.5 * Math.sin(t * s.tw + s.ph)
      ctx.globalAlpha = alpha
      ctx.fillStyle = palette[s.c]
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.globalAlpha = 1
  }

  const draw = () => {
    if (!visible) { rafId = requestAnimationFrame(draw); return }
    t += 0.0065 * settings.speed

    if (mouse.tx != null && mouse.ty != null) {
      mouse.x += (mouse.tx - mouse.x) * 0.15
      mouse.y += (mouse.ty - mouse.y) * 0.15
      if (performance.now() - mouse.t > 2000) mouse.active = false
    }

    const { line, glow, dust1, dust2 } = pickPalette()
    const vw = window.innerWidth
    const vh = window.innerHeight

    ctx.clearRect(0, 0, W, H)

    const g = ctx.createRadialGradient(vw / 2, vh / 2, 0, vw / 2, vh / 2, Math.max(vw, vh) * 0.9)
    g.addColorStop(0, glow)
    g.addColorStop(1, 'transparent')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, vw, vh)

    const gap = Math.max(10, 18 / settings.density)
    const rows = Math.ceil(vh / gap) + 12
    const startY = -gap * 6
    const xStep = Math.max(4, 6 / settings.density)
    const A1 = 42 * settings.strength
    const A2 = 22 * settings.strength

    ctx.lineWidth = 1
    ctx.strokeStyle = line

    const R = 140
    const R2 = R * R
    const invSigma = 1 / (R * R * 0.5)

    for (let r = 0; r < rows; r++) {
      const base = startY + r * gap
      const phaseR = r * 0.22
      const ampMod = 0.85 + 0.25 * Math.sin(r * 0.27 + t * 0.6)

      const nearRow = mouse.active && Math.abs(base - mouse.y) <= R * 2

      ctx.beginPath()
      for (let x = -40; x <= vw + 40; x += xStep) {
        let y =
          base
          + Math.sin(x * 0.0030 + t * 1.30 + phaseR) * (A1 * ampMod)
          + Math.cos(x * 0.0012 - t * 1.05 + r * 0.15) * (A2 * 0.6 * ampMod)

        if (nearRow && Math.abs(x - mouse.x) <= R * 2) {
          const dx = x - mouse.x
          const dy = y - mouse.y
          const d2 = dx * dx + dy * dy
          if (d2 < R2 * 4) {
            const influence = Math.exp(-d2 * invSigma)
            const invDist = 1 / Math.sqrt(d2 + 1e-3)
            const push = settings.mousePush * influence
            y += dy * invDist * push
          }
        }

        if (x === -40) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }

      const edgeFade = Math.min(1, Math.min((base + 2 * gap) / (2 * gap), (vh - base + 2 * gap) / (2 * gap)))
      ctx.globalAlpha = 0.85 * Math.pow(edgeFade, 0.9)
      ctx.stroke()
    }
    ctx.globalAlpha = 1

    drawStars({ dust1, dust2 })

    rafId = requestAnimationFrame(draw)
  }

  const onVis = () => { visible = document.visibilityState === 'visible' }
  document.addEventListener('visibilitychange', onVis)
  window.addEventListener('resize', resize, { passive: true })

  resize()
  initStars()
  onVis()
  draw()

  onUnmounted(() => {
    cancelAnimationFrame(rafId)
    window.removeEventListener('resize', resize)
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerleave', onLeave)
    document.removeEventListener('visibilitychange', onVis)
  })
})
</script>

<style scoped>
.dynamic-background{
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}
</style>
