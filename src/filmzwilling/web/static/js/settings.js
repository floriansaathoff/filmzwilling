// Settings: own profiles, own providers, queue size, self-test and recomputation.
import { el, formatNumber, getJSON, postJSON, putJSON, toast } from "./api.js";

const form = document.getElementById("settings-form");
const status = document.getElementById("settings-status");

function checkbox(name, value, label, checked, logo) {
  return el("label", { class: "check" },
    el("input", { type: "checkbox", name, value, checked }),
    logo ? el("img", { src: logo, alt: "", loading: "lazy" }) : null,
    label);
}

async function load() {
  const data = await getJSON("/api/settings");
  const profiles = document.getElementById("profiles");
  profiles.replaceChildren(
    ...(data.all_profiles.length
      ? data.all_profiles.map((p) => checkbox("profiles", p, p, data.my_profiles.includes(p)))
      : [el("p", { class: "muted", text: "Noch keine Sehverläufe importiert." })]),
  );
  const mine = new Set(data.my_providers);
  const providers = document.getElementById("providers");
  providers.replaceChildren(
    ...(data.providers.length
      ? data.providers.map((p) => checkbox("providers", p.id, p.name, mine.has(p.id), p.logo_url))
      : [el("p", { class: "muted", text: "Noch keine Anbieterliste (mit 'filmzwilling tmdb-sync' laden)." })]),
  );
  document.getElementById("queue-size").value = data.queue_size;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    my_profiles: [...form.querySelectorAll('input[name="profiles"]:checked')].map((b) => b.value),
    queue_size: Number(document.getElementById("queue-size").value || 0),
  };
  const providerBoxes = [...form.querySelectorAll('input[name="providers"]')];
  if (providerBoxes.length) body.my_providers = providerBoxes.filter((b) => b.checked).map((b) => Number(b.value));
  try {
    await putJSON("/api/settings", body);
    status.textContent = "Gespeichert.";
  } catch (error) {
    status.textContent = error.message;
  }
});

document.getElementById("run-evaluate").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const r = await postJSON("/api/evaluate");
    document.getElementById("evaluation").replaceChildren(
      el("p", {
        text: `5-fache Kreuzvalidierung über ${r.n_ratings} eigene Bewertungen: RMSE ${formatNumber(r.rmse, 2)} ` +
          `(Filmdurchschnitt: ${formatNumber(r.baseline_rmse, 2)}), Spearman ${formatNumber(r.spearman, 2)} ` +
          `(Filmdurchschnitt: ${formatNumber(r.baseline_spearman, 2)}).`,
      }),
    );
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

document.getElementById("recompute").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const r = await postJSON("/api/recompute");
    document.getElementById("recs-info").textContent =
      `Gerade berechnet: ${r.count} Empfehlungen aus ${r.rating_count} Bewertungen in ${formatNumber(r.duration, 1)} s.`;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

load().catch((error) => toast(error.message, "error"));
