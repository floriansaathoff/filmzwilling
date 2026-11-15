// "Zuordnung": search TMDB for unmatched import titles, resolve or ignore them.
import { el, getJSON, postJSON, toast } from "./api.js";

for (const li of document.querySelectorAll(".unmatched-item")) {
  const id = li.dataset.id;
  const form = li.querySelector("form");
  const results = li.querySelector(".results");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const q = form.elements.q.value.trim();
    if (!q) return;
    try {
      const data = await getJSON(`/api/tmdb/search?q=${encodeURIComponent(q)}`);
      results.replaceChildren(
        ...data.items.slice(0, 8).map((m) =>
          el("li", { class: "result" },
            m.poster_url ? el("img", { src: m.poster_url, alt: "", loading: "lazy" }) : null,
            el("span", { text: `${m.title}${m.year ? ` (${m.year})` : ""}${m.original_title && m.original_title !== m.title ? ` · ${m.original_title}` : ""}` }),
            el("button", {
              type: "button",
              text: "Diesen Film",
              onclick: async () => {
                try {
                  await postJSON(`/api/unmatched/${id}/resolve`, { tmdb_id: m.tmdb_id });
                  li.remove();
                  toast(`Zugeordnet: ${m.title}`);
                } catch (error) {
                  toast(error.message, "error");
                }
              },
            }))),
      );
      if (!data.items.length) results.append(el("li", { class: "muted", text: "Keine Treffer." }));
    } catch (error) {
      toast(error.message, "error");
    }
  });
  li.querySelector(".ignore").addEventListener("click", async () => {
    try {
      await postJSON(`/api/unmatched/${id}/ignore`);
      li.remove();
    } catch (error) {
      toast(error.message, "error");
    }
  });
}
