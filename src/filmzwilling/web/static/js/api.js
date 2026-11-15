// Small fetch helpers shared by the page scripts.

export async function api(method, url, body, { keepalive = false } = {}) {
  const options = { method, headers: { Accept: "application/json" }, keepalive };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail : `Fehler ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export const getJSON = (url) => api("GET", url);
export const postJSON = (url, body = {}, options = {}) => api("POST", url, body, options);
export const putJSON = (url, body) => api("PUT", url, body);
export const deleteJSON = (url) => api("DELETE", url);

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function formatNumber(value, digits = 1) {
  return Number(value).toFixed(digits).replace(".", ",");
}

export function toast(message, kind = "info") {
  let box = document.getElementById("toast");
  if (!box) {
    box = el("div", { id: "toast", class: "toast", role: "status" });
    document.body.append(box);
  }
  box.textContent = message;
  box.dataset.kind = kind;
  box.classList.add("visible");
  clearTimeout(box._timer);
  box._timer = setTimeout(() => box.classList.remove("visible"), 3500);
}
