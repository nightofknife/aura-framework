export default {
    mounted(el) {
        // 只给按钮/可点击元素加定位与裁切
        const style = getComputedStyle(el);
        if (style.position === 'static') el.style.position = 'relative';
        el.style.overflow = 'hidden';

        function onClick(e) {
            const rect = el.getBoundingClientRect();
            const d = Math.max(rect.width, rect.height);
            const span = document.createElement('span');
            span.className = 'ripple';
            span.style.width = span.style.height = d + 'px';
            span.style.left = (e.clientX - rect.left - d / 2) + 'px';
            span.style.top  = (e.clientY - rect.top  - d / 2) + 'px';
            el.appendChild(span);
            span.addEventListener('animationend', () => span.remove());
        }
        el.__rippleHandler = onClick;
        el.addEventListener('click', onClick);
    },
    unmounted(el) {
        el.removeEventListener('click', el.__rippleHandler);
        delete el.__rippleHandler;
    }
}
