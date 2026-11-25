// Keyboard mapping for the rating page (no DOM dependency, testable with node --test).

const NON_TEXT_INPUTS = new Set([
  "button", "checkbox", "radio", "range", "color", "file", "image", "reset", "submit",
]);

/** True if keyboard shortcuts must be ignored because the user is typing into `target`. */
export function isEditableTarget(target) {
  if (!target) return false;
  if (target.isContentEditable) return true;
  const tag = String(target.tagName || "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = String(target.type || "text").toLowerCase();
    return !NON_TEXT_INPUTS.has(type);
  }
  return false;
}

/**
 * Map a keydown event (or a plain object with key/code/target/modifiers) to an action:
 * {type: "rate", score}, {type: "not_seen"}, {type: "later"}, {type: "undo"}, {type: "trailer"}
 * or null.
 */
export function keyToAction(event) {
  if (!event || event.ctrlKey || event.metaKey || event.altKey) return null;
  if (isEditableTarget(event.target)) return null;
  const key = event.key;
  const code = event.code || "";
  if (typeof key === "string" && key.length === 1 && key >= "0" && key <= "9") {
    return { type: "rate", score: Number(key) };
  }
  if (key === "+" || code === "NumpadAdd" || key === "z" || key === "Z") {
    return { type: "rate", score: 10 };
  }
  if (key === " " || key === "Spacebar" || code === "Space") return { type: "not_seen" };
  if (key === "s" || key === "S") return { type: "later" };
  if (key === "Backspace") return { type: "undo" };
  if (key === "t" || key === "T") return { type: "trailer" };
  return null;
}
