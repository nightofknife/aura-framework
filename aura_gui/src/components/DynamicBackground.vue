<template>
  <!-- 可调：density=密度, speed=速度, strength=振幅强度(0.6~1.6) -->
  <canvas ref="canvasEl" class="dynamic-background"></canvas>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  density: { type: Number, default: 1.25 },   // ↑ 更大 = 更多线条（1.0~2.0 建议）
  speed:   { type: Number, default: 1.0 },    // 动画速度
  strength:{ type: Number, default: 1.0 },    // 波动振幅倍率
})

const canvasEl = ref(null)

onMounted(() => {
  const cvs = canvasEl.value
  if (!cvs) return
  const ctx = cvs.getContext('2d', { alpha: true })
  let dpr = 1, W = 0, H = 0, t = 0, rafId = 0
  let visible = true

  const pickColors = () => {
    const dark = document.documentElement.classList.contains('theme-dark')
    return {
      // 基础线色 + 轻微发光
      line: dark ? 'rgba(150, 160, 200, 0.22)' : 'rgba(120, 130, 170, 0.22)',
      glow: dark ? 'rgba(88, 101, 242, 0.16)' : 'rgba(88, 101, 242, 0.12)',
      haze: dark ? 'rgba(18, 25, 42, 0.75)'   : 'rgba(255, 255, 255, 0.60)',
    }
  }

  const resize = () => {
    dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1))
    W = cvs.width = Math.floor(innerWidth  * dpr)
    H = cvs.height= Math.floor(innerHeight * dpr)
    cvs.style.width  = innerWidth  + 'px'
    cvs.style.height = innerHeight + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  const draw = () => {
    if (!visible) { rafId = requestAnimationFrame(draw); return }
    const { line, glow, haze } = pickColors()
    t += 0.0065 * props.speed

    // 背景微光
    ctx.clearRect(0, 0, W, H)
    const g = ctx.createRadialGradient(W/2, H/2, 0, W/2, H/2, Math.max(W,H)*0.9)
    g.addColorStop(0, glow); g.addColorStop(1, 'transparent')
    ctx.fillStyle = g; ctx.fillRect(0,0,W,H)

    // 线条参数（高密度 + 全屏覆盖）
    const gap   = Math.max(10, 18 / props.density)                 // 行距
    const rows  = Math.ceil(innerHeight / gap) + 12                // 额外溢出保证顶/底覆盖
    const startY= -gap * 6                                         // 从视口上方开始
    const xStep = Math.max(3, 6 / props.density)                   // X 采样更细 = 曲线更顺
    const A1    = 42 * props.strength
    const A2    = 22 * props.strength

    ctx.lineWidth = 1
    ctx.strokeStyle = line

    for (let r = 0; r < rows; r++) {
      const base = startY + r * gap
      // 按行相位/振幅微差，避免完全平行
      const phaseR = r * 0.22
      const ampMod = 0.85 + 0.25 * Math.sin(r * 0.27 + t * 0.6)

      ctx.beginPath()
      for (let x = -40; x <= innerWidth + 40; x += xStep) {
        const y =
            base
            + Math.sin(x * 0.0030 + t * 1.30 + phaseR) * (A1 * ampMod)
            + Math.cos(x * 0.0012 - t * 1.05 + r * 0.15) * (A2 * 0.6 * ampMod)

        if (x === -40) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      // 顶/底渐隐，避免边缘突兀，同时让线“看起来”延伸到最上/最下
      const edgeFade = Math.min(
          1,
          Math.min((base + 2*gap) / (2*gap), (innerHeight - base + 2*gap) / (2*gap))
      )
      ctx.globalAlpha = 0.75 * Math.pow(edgeFade, 0.9)
      ctx.stroke()
    }

    // 轻雾叠层（让线条更融合）
    const v = ctx.createLinearGradient(0,0,0,innerHeight)
    v.addColorStop(0,   'rgba(0,0,0,0)')        // 顶部透明
    v.addColorStop(0.5, 'rgba(0,0,0,0)')        // 中间透明
    v.addColorStop(1,   'rgba(0,0,0,0.02)')     // 底部极轻雾
    ctx.globalAlpha = 1
    ctx.fillStyle = v
    ctx.fillRect(0,0,innerWidth,innerHeight)

    rafId = requestAnimationFrame(draw)
  }

  // 仅在标签可见时绘制，省电
  const onVis = () => { visible = document.visibilityState === 'visible' }
  document.addEventListener('visibilitychange', onVis)

  window.addEventListener('resize', resize, { passive: true })
  resize()
  onVis()
  draw()

  onUnmounted(() => {
    cancelAnimationFrame(rafId)
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', onVis)
  })
})
</script>

<style scoped>
.dynamic-background{
  position: fixed;
  inset: 0;
  z-index: 0;            /* 内容均在其上方 */
  pointer-events: none;
}
</style>
