<template>
  <canvas ref="cv" class="contour-bg" aria-hidden="true"></canvas>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue';

const props = defineProps({
  scale: { type: Number, default: 40.0 },        // 地形尺度
  spacing: { type: Number, default: 5.0 },     // 等高线密度（越大越密）
  thickness: { type: Number, default: 0.005 },  // 线宽（0~0.3）
  speed: { type: Number, default: 0.02 },       // ⚠️更慢的动画速度
  contrast: { type: Number, default: 0.06 },    // 背景对比微调
  // 可选：扫光强度/稀有度（小=更克制）
  glintStrength: { type: Number, default: 0.45 },
  glintRarity: { type: Number, default: 0.997 }, // 0.997~0.999 稀有
});

const cv = ref(null);
let gl, prog, raf, u = {};

function hexToRgb01(hex){
  const s = hex.trim();
  const m = s.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
  if(!m) return [1,1,1];
  return [parseInt(m[1],16)/255, parseInt(m[2],16)/255, parseInt(m[3],16)/255];
}
function readThemeColors(){
  const rs = getComputedStyle(document.documentElement);
  // 允许通过 --gold-1 / --gold-2 覆盖；否则 fallback 到 surface，再到内置白金色
  const bg1Hex = rs.getPropertyValue('--gold-1') || rs.getPropertyValue('--surface-1') || '#F6F1E1'; // 浅金
  const bg2Hex = rs.getPropertyValue('--gold-2') || rs.getPropertyValue('--surface-2') || '#E7DABC'; // 暖金
  const lineHex = rs.getPropertyValue('--brand-600') || '#AEB6C2'; // 用作银线冷调混色（低权重）

  const bg1  = hexToRgb01(bg1Hex);
  const bg2  = hexToRgb01(bg2Hex);
  const line = hexToRgb01(lineHex);

  gl.uniform3fv(u.u_bg1,  new Float32Array(bg1));
  gl.uniform3fv(u.u_bg2,  new Float32Array(bg2));
  gl.uniform3fv(u.u_line, new Float32Array(line));
}

function createShader(type, src){
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if(!gl.getShaderParameter(s, gl.COMPILE_STATUS)){ console.error(gl.getShaderInfoLog(s)); }
  return s;
}
function createProgram(vsSrc, fsSrc){
  const p = gl.createProgram();
  const vs = createShader(gl.VERTEX_SHADER, vsSrc);
  const fs = createShader(gl.FRAGMENT_SHADER, fsSrc);
  gl.attachShader(p, vs); gl.attachShader(p, fs); gl.linkProgram(p);
  if(!gl.getProgramParameter(p, gl.LINK_STATUS)){ console.error(gl.getProgramInfoLog(p)); }
  return p;
}

const VS = `
attribute vec2 a_pos;
void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }
`;

const FS = `
#ifdef GL_ES
precision highp float;
#endif
#ifdef GL_OES_standard_derivatives
#extension GL_OES_standard_derivatives : enable
#endif

uniform vec2  u_res;
uniform float u_time, u_scale, u_spacing, u_thickness, u_speed, u_contrast, u_relief;
uniform vec3  u_bg1, u_bg2, u_line; // u_line 仅做轻微色温校正

// ---------- 噪声 ----------
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453123); }
float noise(vec2 x){
  vec2 i=floor(x), f=fract(x);
  float a=hash(i);
  float b=hash(i+vec2(1.,0.));
  float c=hash(i+vec2(0.,1.));
  float d=hash(i+vec2(1.,1.));
  vec2 u=f*f*(3.0-2.0*f);
  return mix(a,b,u.x) + (c-a)*u.y*(1.0-u.x) + (d-b)*u.x*u.y;
}
mat2 m2 = mat2(1.6,1.2,-1.2,1.6);
float fbm(vec2 x){ float v=0., a=.5; for(int i=0;i<5;i++){ v+=a*noise(x); x=m2*x; a*=.55; } return v; }
float fbmRidge(vec2 x){
  float v=0., a=.5;
  for(int i=0;i<5;i++){
    float n = noise(x);
    n = 1.0 - abs(n*2.0 - 1.0);
    v += n*a;
    x = m2*x; a *= .55;
  }
  return v;
}

// ---------- 静态地形 ----------
float heightField(vec2 p, float sc){
  vec2 pw = p * sc;
  vec2 w1 = vec2(fbm(pw + vec2(3.11, 5.79)), fbm(pw + vec2(7.23, 2.17)));
  vec2 w2 = vec2(fbm(pw*1.6 - w1 + vec2(1.73, 9.13)),
                 fbm(pw*1.6 + w1 + vec2(4.11,-6.37)));
  return fbmRidge(pw + 1.0*w2);
}
float reliefRemap(float x, float k){ return clamp(0.5 + (x - 0.5) * k, 0.0, 1.0); }

// ---------- 背景（白金静态） ----------
vec3 platinumBG(float h, float contrast){
  vec3 lo = mix(u_bg1, vec3(0.88,0.88,0.86), 0.5);
  vec3 hi = mix(u_bg2, vec3(0.95,0.95,0.93), 0.5);
  vec3 base = mix(lo, hi, smoothstep(0.2,0.8,h));

  float bands = abs(fract(h*4.0) - 0.5);
  #ifdef GL_OES_standard_derivatives
    float aa = 0.75 * fwidth(h*4.0);
    bands = smoothstep(0.22, 0.22 + aa, bands);
  #endif
  base *= (0.965 + (1.0 - bands)*0.05);
  base *= (1.0 + contrast) * mix(0.93, 1.05, h);
  return clamp(base, 0.0, 1.0);
}

// ---------- 金色 ----------
vec3 goldForHeight(float h){
  vec3 shadow    = vec3(0.45, 0.34, 0.11); // #735718
  vec3 mid       = vec3(0.83, 0.69, 0.22); // #D4AF37
  vec3 highlight = vec3(1.00, 0.94, 0.70); // #FFF1B3
  float e = clamp(h, 0.0, 1.0);
  vec3 c = mix(shadow, mid,       smoothstep(0.10,0.70,e));
  c      = mix(c,      highlight, smoothstep(0.60,0.95,e));
  return c;
}

void main(){
  // 屏幕短边归一化坐标
  vec2 p = (gl_FragCoord.xy - 0.5*u_res) / min(u_res.x, u_res.y);

  // 高度场（静态）+ 起伏增强
  float h0 = heightField(p, u_scale);
  float h  = reliefRemap(h0, max(u_relief, 1.0));

  // 背景
  vec3 bg = platinumBG(h, u_contrast);

  // —— 等高线：仅相位漂移（轮廓稳定） ——
  float phase = u_time * u_speed;
  float v = h * u_spacing + phase;     // 等值域
  float saw = abs(fract(v) - 0.5);     // 到线中心的“函数距离”

  // ===== 屏幕空间线宽：fwidth(v) 的安全版本 =====
  float fw;
  #ifdef GL_OES_standard_derivatives
    fw = fwidth(v);
  #else
    // 没有导数扩展时，使用“一像素差分”近似 fwidth(v)
    float e = 1.0 / min(u_res.x, u_res.y);
    // 直接对最终 h 采样（含 relief），得到 ∂h/∂x, ∂h/∂y
    float hC = h;
    float hR = reliefRemap(heightField(p + vec2(e,0.0), u_scale), max(u_relief,1.0));
    float hU = reliefRemap(heightField(p + vec2(0.0,e), u_scale), max(u_relief,1.0));
    float dvx = abs((hR - hC) * u_spacing);
    float dvy = abs((hU - hC) * u_spacing);
    fw = dvx + dvy + 1e-6; // 防止除 0
  #endif

  // 到线中心的像素距离
  float distPx = saw / max(fw, 1e-6);

  // 把 u_thickness 映射为像素线宽（等宽）
  float w_px = 0.5 + clamp(u_thickness, 0.0, 0.2) * 40.0;

  // 线芯 & 外缘凹槽（都按像素控制）
  float lineMask = 1.0 - smoothstep(w_px,       w_px + 1.0, distPx);
  float rimMask  = 1.0 - smoothstep(w_px + 1.5, w_px + 4.0, distPx);

  // 基准粗线（每 5 条加粗 ~0.8px）
  float idx      = floor(v);
  float isIndex5 = 1.0 - step(0.5, mod(idx, 5.0));
  float lineMaskIndex = 1.0 - smoothstep(w_px+0.8, w_px+1.8, distPx);
  lineMask = mix(lineMask, max(lineMask, lineMaskIndex), isIndex5);

  // 金色线条（不做高光/扫光，避免“颜料感”）
  vec3 lineCol = goldForHeight(h);
  lineCol = mix(lineCol, mix(lineCol, u_line, 0.10), 0.10); // 轻微色温校正

  // 带心轻暗化（极弱，防止渗色）
  float vStatic = h * u_spacing;                        // 不随时间
  float mid = 0.5 - abs(fract(vStatic) - 0.5);
  bg *= (1.0 - mid * 0.012);

  // 外缘雕刻感
  bg *= (1.0 - rimMask * 0.06);

  // 直接覆盖（等宽金线）
  vec3 finalColor = mix(bg, lineCol, lineMask);

  gl_FragColor = vec4(finalColor, 1.0);
}



`;

let t0;
function init(){
  gl = cv.value.getContext('webgl', { premultipliedAlpha:false, alpha:false, antialias:true });
  if(!gl){ console.warn('WebGL unavailable'); return; }

  prog = createProgram(VS, FS);
  gl.useProgram(prog);

  // 全屏三角形
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a_pos');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  // uniforms
  u.u_res       = gl.getUniformLocation(prog, 'u_res');
  u.u_time      = gl.getUniformLocation(prog, 'u_time');
  u.u_scale     = gl.getUniformLocation(prog, 'u_scale');
  u.u_spacing   = gl.getUniformLocation(prog, 'u_spacing');
  u.u_thickness = gl.getUniformLocation(prog, 'u_thickness');
  u.u_speed     = gl.getUniformLocation(prog, 'u_speed');
  u.u_contrast  = gl.getUniformLocation(prog, 'u_contrast');
  u.u_bg1       = gl.getUniformLocation(prog, 'u_bg1');
  u.u_bg2       = gl.getUniformLocation(prog, 'u_bg2');
  u.u_line      = gl.getUniformLocation(prog, 'u_line');
  u.u_glintStrength = gl.getUniformLocation(prog, 'u_glintStrength');
  u.u_glintRarity   = gl.getUniformLocation(prog, 'u_glintRarity');

  gl.uniform1f(u.u_scale,        props.scale);
  gl.uniform1f(u.u_spacing,      props.spacing);
  gl.uniform1f(u.u_thickness,    props.thickness);
  gl.uniform1f(u.u_speed,        props.speed);
  gl.uniform1f(u.u_contrast,     props.contrast);
  gl.uniform1f(u.u_glintStrength,props.glintStrength);
  gl.uniform1f(u.u_glintRarity,  props.glintRarity);

  readThemeColors();
  onResize();
  t0 = undefined;
  loop(0);
}

function onResize(){
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.floor(window.innerWidth  * dpr);
  const h = Math.floor(window.innerHeight * dpr);
  if (cv.value.width !== w || cv.value.height !== h){
    cv.value.width = w;
    cv.value.height = h;
    gl.viewport(0,0,w,h);
    gl.uniform2f(u.u_res, w, h);
  }
}

function loop(ts){
  if(!t0) t0 = ts;
  const t = (ts - t0) / 1000.0;
  gl.uniform1f(u.u_time, t);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  raf = requestAnimationFrame(loop);
}

onMounted(()=>{
  init();
  window.addEventListener('resize', onResize);
});
onBeforeUnmount(()=>{
  cancelAnimationFrame(raf);
  window.removeEventListener('resize', onResize);
});
</script>

<style scoped>
.contour-bg{
  position: fixed;
  inset: 0;
  z-index: 0;        /* 背景层。前景容器 z-index:1 */
  pointer-events: none;
}
</style>
