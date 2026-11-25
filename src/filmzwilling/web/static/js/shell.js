// Loaded on every page: header glass on scroll and controller support.
import "./gamepad.js";

const bar = document.querySelector(".topbar");
const onScroll = () => bar && bar.classList.toggle("scrolled", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();
