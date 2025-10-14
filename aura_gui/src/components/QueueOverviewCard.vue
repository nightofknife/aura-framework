<template>
  <div class="kpi">
    <div class="card">
      <div class="title">Ready</div>
      <div class="num">{{ overview?.ready_length ?? '—' }}</div>
    </div>
    <div class="card">
      <div class="title">Delayed</div>
      <div class="num">{{ overview?.delayed_length ?? '—' }}</div>
    </div>
    <div class="card">
      <div class="title">Avg Wait</div>
      <div class="num">{{ fmtSec(overview?.avg_wait_sec) }}</div>
    </div>
    <div class="card">
      <div class="title">P95 Wait</div>
      <div class="num">{{ fmtSec(overview?.p95_wait_sec) }}</div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  overview: {type: Object, default: () => ({})},
  loading: Boolean,
});

function fmtSec(s) {
  if (s == null) return '—';
  const sec = Math.round(s);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), rs = sec % 60;
  return `${m}m ${rs}s`;
}
</script>
