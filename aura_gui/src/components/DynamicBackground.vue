<template>
  <div class="desk-bg" aria-hidden="true">
    <div class="desk-bg__base"></div>
    <div class="desk-bg__grain"></div>
    <div class="desk-bg__marks"></div>
    <div class="desk-bg__paper desk-bg__paper--a"></div>
    <div class="desk-bg__paper desk-bg__paper--b"></div>
  </div>
</template>

<style scoped>
.desk-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.desk-bg__base {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 12%),
    linear-gradient(180deg, rgba(38, 46, 49, 0.92), rgba(23, 29, 31, 0.96));
}

.desk-bg__grain {
  position: absolute;
  inset: 0;
  background:
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.008), rgba(255, 255, 255, 0.008) 1px, transparent 1px, transparent 4px),
    repeating-linear-gradient(90deg, rgba(0, 0, 0, 0.05), rgba(0, 0, 0, 0.05) 1px, transparent 1px, transparent 12px);
  opacity: 0.42;
}

.desk-bg__marks {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(114deg, transparent 0 24%, rgba(201, 187, 149, 0.03) 24% 24.4%, transparent 24.4% 100%),
    linear-gradient(164deg, transparent 0 74%, rgba(199, 104, 63, 0.035) 74% 74.2%, transparent 74.2% 100%);
}

.desk-bg__paper {
  position: absolute;
  border: 1px solid rgba(201, 187, 149, 0.08);
  background:
    repeating-linear-gradient(0deg, rgba(201, 187, 149, 0.04), rgba(201, 187, 149, 0.04) 1px, transparent 1px, transparent 6px),
    rgba(201, 187, 149, 0.035);
  box-shadow: 0 18px 32px rgba(0, 0, 0, 0.12);
}

.desk-bg__paper--a {
  top: -10vh;
  right: -6vw;
  width: 24vw;
  height: 48vh;
  transform: rotate(8deg);
}

.desk-bg__paper--b {
  left: -8vw;
  bottom: -14vh;
  width: 30vw;
  height: 34vh;
  transform: rotate(-6deg);
}
</style>
