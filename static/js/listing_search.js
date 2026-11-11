// static/js/listing_search.js
// Expects this markup somewhere on your listings page (adjust ids/classes):
//
//   <input id="listing-search" type="search" placeholder="Search listings">

const searchInput = document.querySelector("#listing-search");
const sortSelect = document.querySelector("#listing-sort");
const grid = document.querySelector("#listing-grid");
const statusEl = document.querySelector("#listing-status");

let debounceTimer = null;
let controller = null;

// Restore state from the URL so links and the back button work.
const initial = new URLSearchParams(window.location.search);
searchInput.value = initial.get("q") || "";
sortSelect.value = initial.get("sort") || "newest";

function renderListings(items) {
  grid.replaceChildren();
  for (const item of items) {
    const card = document.createElement("div");
    card.className = "listing-card";

    const name = document.createElement("h3");
    name.textContent = item.name; // textContent avoids HTML injection

    const price = document.createElement("p");
    price.textContent = item.price == null ? "Price not set" : `$${item.price.toFixed(2)}`;

    card.append(name, price);
    grid.append(card);
  }
}

async function loadListings() {
  const q = searchInput.value.trim();
  const sort = sortSelect.value;

  // Keep the URL in sync (no page reload).
  const urlParams = new URLSearchParams();
  if (q) urlParams.set("q", q);
  if (sort !== "newest") urlParams.set("sort", sort);
  const qs = urlParams.toString();
  history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);

  // Cancel any in-flight request so a slow old response can't overwrite a newer one.
  if (controller) controller.abort();
  controller = new AbortController();

  statusEl.textContent = "Loading...";
  try {
    const res = await fetch(`/api/listings?${new URLSearchParams({ q, sort })}`, {
      signal: controller.signal,
    });
    if (!res.ok) throw new Error("Request failed");
    const data = await res.json();

    renderListings(data.items);
    statusEl.textContent = data.total === 0 ? "No listings found." : "";
  } catch (err) {
    if (err.name === "AbortError") return; // superseded by a newer request
    statusEl.textContent = "Something went wrong. Please try again.";
  }
}

searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(loadListings, 300);
});
sortSelect.addEventListener("change", loadListings);

loadListings();
