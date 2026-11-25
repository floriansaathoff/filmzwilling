// Collapsible filter panel (recommendations, twin page): steppers, reset, close, controller keys.
import { toast } from "./api.js";
import { stepNumber } from "./pad.js";
import { play } from "./sfx.js";

/**
 * @param form the <form class="filters"> panel
 * @param toggle the button that opens/closes it
 * @param onReset called after "Zurücksetzen" (should clear the URL state and reload)
 * @param storageKey sessionStorage key that remembers whether the panel is open
 */
export function setupFilterPanel({ form, toggle, onReset, storageKey }) {
  function show(open, { focus = false } = {}) {
    if (form.hidden === open) play(open ? "open" : "close");
    form.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    sessionStorage.setItem(storageKey, open ? "1" : "0");
    if (open && focus) form.querySelector("input, summary, button")?.focus({ focusVisible: true });
    if (!open && focus) toggle.focus({ focusVisible: true });
  }
  toggle.addEventListener("click", () => show(form.hidden, { focus: document.body.classList.contains("pad-mode") }));
  show(sessionStorage.getItem(storageKey) === "1");
  form.querySelector("#close-filters")?.addEventListener("click", () => show(false, { focus: true }));

  function reset() {
    onReset();
    toast("Filter zurückgesetzt");
  }
  form.querySelector("#reset-filters")?.addEventListener("click", reset);

  // Steppers: big -/+ buttons for number filters (controller friendly; typing still works).
  form.querySelectorAll(".stepper").forEach((box) => {
    const input = box.querySelector("input");
    const opts = { step: Number(box.dataset.step), start: Number(box.dataset.start), min: Number(box.dataset.min), max: Number(box.dataset.max) };
    box.querySelectorAll(".step-btn").forEach((button) =>
      button.addEventListener("click", () => {
        input.value = stepNumber(input.value, Number(button.dataset.dir), opts);
        play("toggle");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }));
  });

  // Controller: Start opens/closes the filters, X inside the filters resets them.
  document.addEventListener("fz:pad", (event) => {
    const { button } = event.detail;
    if (button === "start") {
      event.preventDefault();
      show(form.hidden, { focus: true });
    } else if (button === "x" && !form.hidden && form.contains(document.activeElement)) {
      event.preventDefault();
      reset();
    }
  });
  // Chips and segmented buttons click softly.
  form.addEventListener("change", (event) => { if (event.target.type === "checkbox" || event.target.type === "radio") play("toggle"); });
  return { show };
}
