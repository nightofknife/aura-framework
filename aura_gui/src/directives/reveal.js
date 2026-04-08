// 滚动进入视口时加 class=reveal-in
export default {
    mounted(el, binding) {
        el.classList.add('reveal');
        const once = !(binding.value && binding.value.repeat);
        const io = new IntersectionObserver((ents) => {
            ents.forEach(ent => {
                if (ent.isIntersecting) {
                    el.classList.add('reveal-in');
                    if (once) io.disconnect();
                } else if (!once) {
                    el.classList.remove('reveal-in');
                }
            });
        }, { threshold: 0.18 });
        io.observe(el);
        el.__revealIO = io;
    },
    unmounted(el){ el.__revealIO && el.__revealIO.disconnect(); }
}
