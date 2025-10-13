<template>
  <!-- 可调：density 线密度；speed 速度；strength 振幅；mousePush 鼠标扰动强度；dust 星尘数量 -->
  <canvas ref="canvasEl" class="dynamic-background"></canvas>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  density:   { type: Number, default: 2.0 },  // 1.4~2.0 建议，越大越密
  speed:     { type: Number, default: 0.4 }, // 全局速度
  strength:  { type: Number, default: 0.8 }, // 振幅强度
  mousePush: { type: Number, default:30 },   // 鼠标扰动强度（像素级，20~30）
  dust:      { type: Number, default: 50 },   // 星尘数量（50~100 性能更稳）
})

const canvasEl = ref(null)

onMounted(() => {
  const cvs = canvasEl.value
  if (!cvs) return
  const ctx = cvs.getContext('2d', { alpha: true })
  let dpr = 1, W = 0, H = 0, t = 0, rafId = 0, visible = true

  // 主题感知色板（轻微时间漂移）
  const pickPalette = () => {
    const dark = document.documentElement.classList.contains('theme-dark')
    // 基础色相：亮色偏青绿（200~190°），暗色偏蓝紫（230~240°）
    const baseHue = (dark ? 236 : 196) + Math.sin(t * 0.12) * 6 // 轻微漂移 ±6°
    const line = `hsla(${baseHue}, ${dark ? 48 : 42}%, ${dark ? 74 : 54}%, ${dark ? 0.28 : 0.26})`
    const glow = `hsla(${dark ? baseHue - 10 : baseHue + 10}, ${dark ? 70 : 60}%, ${dark ? 58 : 66}%, ${dark ? 0.16 : 0.12})`
    const dust1 = `hsla(${baseHue + 20}, 80%, ${dark ? 74 : 40}%, ${dark ? 0.85 : 0.55})`
    const dust2 = `hsla(${baseHue - 40}, 90%, ${dark ? 70 : 38}%, ${dark ? 0.75 : 0.50})`
    return { line, glow, dust1, dust2 }
  }

  // 画布尺寸
  const resize = () => {
    dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1))
    W = cvs.width  = Math.floor(window.innerWidth  * dpr)
    H = cvs.height = Math.floor(window.innerHeight * dpr)
    cvs.style.width  = window.innerWidth  + 'px'
    cvs.style.height = window.innerHeight + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  // 鼠标扰动（平滑）
  const mouse = { x: window.innerWidth/2, y: window.innerHeight/2, tx: null, ty: null, t: 0, active: false }
  const onMove = (e) => {
    mouse.tx = e.clientX; mouse.ty = e.clientY
    mouse.t = performance.now(); mouse.active = true
  }
  const onLeave = () => { mouse.active = false }
  window.addEventListener('pointermove', onMove, { passive: true })
  window.addEventListener('pointerleave', onLeave, { passive: true })

  // 星尘
  const stars = []
  const initStars = () => {
    stars.length = 0
    for (let i = 0; i < props.dust; i++) {
      stars.push({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        r: Math.random() < 0.65 ? 1 : 1.6,
        vx: (Math.random() - 0.5) * 0.12,
        vy: (Math.random() - 0.5) * 0.12,
        tw: 0.6 + Math.random() * 1.0, // twinkle 速度
        ph: Math.random() * Math.PI * 2, // 相位
        c: Math.random() < 0.5 ? 'dust1' : 'dust2'
      })
    }
  }

  function drawStars(palette) {
    const vw = window.innerWidth, vh = window.innerHeight
    for (const s of stars) {
      // 漂移 + 轻微噪声
      s.x += s.vx; s.y += s.vy
      if (s.x < -2) s.x = vw + 2; if (s.x > vw + 2) s.x = -2
      if (s.y < -2) s.y = vh + 2; if (s.y > vh + 2) s.y = -2
      const alpha = 0.5 + 0.5 * Math.sin(t * s.tw + s.ph)
      ctx.globalAlpha = alpha
      ctx.fillStyle = palette[s.c]
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill()
    }
    ctx.globalAlpha = 1
  }

  // 主绘制
  const draw = () => {
    if (!visible) { rafId = requestAnimationFrame(draw); return }
    t += 0.0065 * props.speed

    // 鼠标平滑（低通滤波）
    if (mouse.tx != null && mouse.ty != null) {
      mouse.x += (mouse.tx - mouse.x) * 0.15
      mouse.y += (mouse.ty - mouse.y) * 0.15
      // 若 2 秒无移动则减弱影响
      if (performance.now() - mouse.t > 2000) mouse.active = false
    }

    const { line, glow, dust1, dust2 } = pickPalette()
    const vw = window.innerWidth, vh = window.innerHeight

    ctx.clearRect(0, 0, W, H)

    // 背景晕光
    const g = ctx.createRadialGradient(vw/2, vh/2, 0, vw/2, vh/2, Math.max(vw, vh) * 0.9)
    g.addColorStop(0, glow); g.addColorStop(1, 'transparent')
    ctx.fillStyle = g; ctx.fillRect(0, 0, vw, vh)

    // 线参数（高密 + 全屏覆盖）
    const gap    = Math.max(10, 18 / props.density)
    const rows   = Math.ceil(vh / gap) + 12
    const startY = -gap * 6
    const xStep  = Math.max(4, 6 / props.density)
    const A1     = 42 * props.strength
    const A2     = 22 * props.strength

    ctx.lineWidth = 1
    ctx.strokeStyle = line

    // 鼠标扰动范围（矩形预裁剪，避免整屏做指数）
    const R = 140 // 影响半径（px）
    const R2 = R * R
    const invSigma = 1 / (R * R * 0.5) // 高斯的 1/(2σ^2)

    for (let r = 0; r < rows; r++) {
      const base = startY + r * gap
      const phaseR = r * 0.22
      const ampMod = 0.85 + 0.25 * Math.sin(r * 0.27 + t * 0.6)

      const nearRow = mouse.active && Math.abs(base - mouse.y) <= R * 2

      ctx.beginPath()
      for (let x = -40; x <= vw + 40; x += xStep) {
        // 原始线
        let y =
            base
            + Math.sin(x * 0.0030 + t * 1.30 + phaseR) * (A1 * ampMod)
            + Math.cos(x * 0.0012 - t * 1.05 + r * 0.15) * (A2 * 0.6 * ampMod)

        // 鼠标扰动：仅在鼠标附近做运算
        if (nearRow && Math.abs(x - mouse.x) <= R * 2) {
          const dx = x - mouse.x
          const dy = y - mouse.y
          const d2 = dx*dx + dy*dy
          if (d2 < R2 * 4) {
            // 高斯衰减（越近越大），沿径向“外推”
            const influence = Math.exp(-d2 * invSigma)
            const invDist = 1 / Math.sqrt(d2 + 1e-3)
            const push = props.mousePush * influence
            y += dy * invDist * push // 垂直位移足够表现“鼓起”
          }
        }

        if (x === -40) ctx.moveTo(x, y); else ctx.lineTo(x, y)
      }

      // 顶/底渐隐，避免边缘突兀
      const edgeFade = Math.min(1, Math.min((base + 2*gap) / (2*gap), (vh - base + 2*gap) / (2*gap)))
      ctx.globalAlpha = 0.85 * Math.pow(edgeFade, 0.9)
      ctx.stroke()
    }
    ctx.globalAlpha = 1

    // 画星尘
    drawStars({ dust1, dust2 })

    rafId = requestAnimationFrame(draw)
  }

  // 初始与生命周期
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
  z-index: 0;          /* .topbar/.sidebar/.main 在其上方即可 */
  pointer-events: none;
}
</style>
