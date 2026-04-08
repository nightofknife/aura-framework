// 轻量视差倾斜（鼠标跟随，移动端禁用）
export default {
    mounted(el, binding) {
        const max = binding.value?.max ?? 8; // 最大倾斜角
        const damp = binding.value?.damp ?? 0.12; // 阻尼
        let rAF, tx = 0, ty = 0, curX = 0, curY = 0;
        const rect = () => el.getBoundingClientRect();
        const onMove = (e) => {
            if ('ontouchstart' in window) return;
            const b = rect();
            const x = (e.clientX - b.left) / b.width * 2 - 1;
            const y = (e.clientY - b.top) / b.height * 2 - 1;
            tx = -(y * max); ty = x * max;
            if (!rAF) rAF = requestAnimationFrame(tick);
        };
        const onLeave = () => { tx = 0; ty = 0; if (!rAF) rAF = requestAnimationFrame(tick); };
        function tick() {
            curX += (tx - curX) * damp;
            curY += (ty - curY) * damp;
            el.style.transform = `perspective(700px) rotateX(${curX}deg) rotateY(${curY}deg)`;
            if (Math.abs(curX - tx) > .01 || Math.abs(curY - ty) > .01) rAF = requestAnimationFrame(tick);
            else { rAF = null; }
        }
        el.__tiltMove = onMove; el.__tiltLeave = onLeave;
        el.addEventListener('mousemove', onMove);
        el.addEventListener('mouseleave', onLeave);
    },

    unmounted(el) {
        el.removeEventListener('mousemove', el.__tiltMove);
        el.removeEventListener('mouseleave', el.__tiltLeave);
    }
}
