// "Meine Bewertungen": searchable list, editable notes, delete.
import { deleteJSON, el, getJSON, putJSON, toast } from "./api.js";
import { openTrailer } from "./player.js";
import { icon, setAmbient } from "./ui.js";

const body = document.querySelector("#ratings-table tbody");
const search = document.getElementById("rating-search");
const count = document.getElementById("ratings-count");

function row(item) {
  const select = el("select", { "aria-label": `Note für ${item.title}` },
    ...Array.from({ length: 11 }, (_, n) => el("option", { value: n, selected: n === item.score, text: String(n) })));
  select.addEventListener("change", async () => {
    try {
      await putJSON(`/api/ratings/${item.film_id}`, { score: Number(select.value) });
      toast("Gespeichert");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  const remove = el("button", { type: "button", class: "secondary small", text: "Löschen" });
  const trailer = el("button", { type: "button", class: "icon-btn small", title: "Trailer abspielen", onclick: () => openTrailer(item) }, icon("play"), el("span", { text: "Trailer" }));
  const tr = el("tr", {},
    el("td", {}, el("img", { class: "thumb", src: item.poster_url, alt: "", loading: "lazy" })),
    el("td", {}, el("strong", { text: item.title }), item.original_title && item.original_title !== item.title ? el("div", { class: "muted", text: item.original_title }) : null),
    el("td", { text: item.year || "" }),
    el("td", {}, select),
    el("td", { class: "row-actions" }, trailer, " ", remove));
  remove.addEventListener("click", async () => {
    try {
      await deleteJSON(`/api/ratings/${item.film_id}`);
      tr.remove();
      count.textContent = String(Number(count.textContent) - 1);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  return tr;
}

async function load() {
  const q = search.value.trim();
  const data = await getJSON(`/api/ratings${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  body.replaceChildren(...data.items.map(row));
  if (data.items.length) setAmbient(data.items[0].poster_url);
  if (!q) count.textContent = String(data.total);
}

let timer = null;
search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 200); });
load().catch((error) => toast(error.message, "error"));
