// Loaded on every page: header glass on scroll, sound toggle and controller support.
import "./gamepad.js";
import { setSound, soundOn } from "./sfx.js";

const bar = document.querySelector(".topbar");
const onScroll = () => bar && bar.classList.toggle("scrolled", window.scrollY > 8);
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

const sound = document.getElementById("sound-toggle");
function renderSound() {
  if (!sound) return;
  const on = soundOn();
  sound.setAttribute("aria-pressed", String(on));
  sound.querySelector("use")?.setAttribute("href", `/static/icons.svg#${on ? "volume" : "mute"}`);
}
sound?.addEventListener("click", () => {
  setSound(!soundOn());
  renderSound();
});
renderSound();
