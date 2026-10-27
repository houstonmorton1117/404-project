/*
  storefront.js

  The Vault Campus Marketplace
  CSC 405 Sp 26
  Created by Day Ekoi - Iteration 4
  Date: 3/18/2026 - 3/22/2026
  Updated by Day Ekoi - Iteration 5 - 4/20/26 - fetchStorefronts now maps preview_image_1-4 to card carousel; falls back to banner_url if no previews set
  Updated by Day Ekoi - Iteration 5 - 4/20/26 - removed add-to-cart form from storefront cards (size, qty, add to bag); kept version history via comments

  XSS fixes added by Rochele Solmon.
*/

let storefronts = [];

// Get the storefront grid container.
const grid = document.getElementById("storefrontGrid");

// XSS protection added by Rochele Solmon: escape text before HTML insertion.
function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

// XSS protection added by Rochele Solmon: allow only HTTP(S) URLs.
function getSafeUrl(value) {
  if (!value) return "";

  try {
    const url = new URL(String(value), window.location.origin);

    if (url.protocol === "https:" || url.protocol === "http:") {
      return url.href;
    }
  } catch (_error) {}

  return "";
}

// CREATE STOREFRONT CARD
function createCard(store) {
  let index = 0;

  const card = document.createElement("div");
  card.className = "storefront-card";

  const categories = Array.isArray(store.categories)
    ? store.categories
    : [];

  const images = Array.isArray(store.images)
    ? store.images.map(getSafeUrl).filter(Boolean)
    : [];

  const logo = getSafeUrl(store.logo);
  const items = Number(store.items) || 0;
  const itemLabel = `${items} ${items === 1 ? "Item" : "Items"}`;

  const metaLabel = categories.length > 0
    ? `${itemLabel} | ${categories.join(" • ")}`
    : itemLabel;

  // XSS protection added by Rochele Solmon:
  // Escape storefront text and URLs before inserting them into HTML.
  card.innerHTML = `
    <div class="storefront-card-body">
      <div class="storefront-header">
        ${logo
          ? `<img class="storefront-logo" src="${escapeHTML(logo)}" alt="Storefront logo">`
          : `<div class="storefront-logo"></div>`
        }
        <div>
          <h2 class="storefront-name">${escapeHTML(store.name)}</h2>
          <p class="storefront-meta">${escapeHTML(metaLabel)}</p>
        </div>
      </div>

      <div class="carousel-shell">
        <button type="button" class="carousel-btn left" aria-label="Previous image">&#10094;</button>
        ${images.length > 0
          ? `<img class="carousel-image" src="${escapeHTML(images[0])}" alt="${escapeHTML(store.name || "Storefront")} image">`
          : `<div class="carousel-image"></div>`
        }
        <button type="button" class="carousel-btn right" aria-label="Next image">&#10095;</button>
      </div>

      <!-- Removed by Day Ekoi - Iteration 5 - 4/20/26: add-to-cart form removed from storefront cards.
           Cart/size/qty actions belong on the individual listing page, not the storefront browse view.
      <form action="/auth/add_to_cart" method="POST" class="bag-form">
        <input type="hidden" name="item_id" value="${escapeHTML(store.id)}">
        <input type="hidden" name="item_name" value="${escapeHTML(store.name)} Official Item">
        <input type="hidden" name="price" value="45.00">
        <div class="selection-row">
          <select name="size" class="vault-select">
            <option value="S">S</option>
            <option value="M">M</option>
            <option value="L">L</option>
            <option value="XL">XL</option>
          </select>
          <input type="number" name="quantity" value="1" min="1" class="vault-qty">
        </div>
        <button type="submit" class="add-bag-btn">Add to Bag</button>
      </form>
      -->
    </div>

    <div class="storefront-footer">
      <button type="button" class="enter-btn">Enter Storefront</button>
    </div>
  `;

  const img = card.querySelector(".carousel-image");
  const left = card.querySelector(".left");
  const right = card.querySelector(".right");
  const enterBtn = card.querySelector(".enter-btn");

  // Card arrow functionality.
  // Added by Rochele Solmon: avoid errors when there are no images.
  left.addEventListener("click", () => {
    if (!images.length || !img || img.tagName !== "IMG") return;

    index = (index - 1 + images.length) % images.length;
    img.src = images[index];
  });

  right.addEventListener("click", () => {
    if (!images.length || !img || img.tagName !== "IMG") return;

    index = (index + 1) % images.length;
    img.src = images[index];
  });

  // Enter storefront routing.
  enterBtn.addEventListener("click", () => {
    const id = Number(store.id);

    if (Number.isInteger(id) && id > 0) {
      window.location.href = `/storefronts/${id}`;
    }
  });

  // Lightbox: click carousel image to see full preview.
  if (img && img.tagName === "IMG") {
    img.addEventListener("click", () => {
      const overlay = document.getElementById("lightboxOverlay");
      const lightboxImg = document.getElementById("lightboxImg");

      if (!overlay || !lightboxImg) return;

      lightboxImg.src = getSafeUrl(img.src);
      lightboxImg.alt = img.alt;
      overlay.classList.add("active");
    });
  }

  return card;
}

// Close lightbox when clicking the overlay.
document.addEventListener("DOMContentLoaded", () => {
  const overlay = document.getElementById("lightboxOverlay");

  if (overlay) {
    overlay.addEventListener("click", () => {
      overlay.classList.remove("active");
    });
  }
});

// Render all storefront cards.
function renderStorefronts() {
  if (!grid) return;

  grid.replaceChildren();

  storefronts.forEach(store => {
    const card = createCard(store);
    grid.appendChild(card);
  });
}

// FETCH STOREFRONTS FROM FLASK API
async function fetchStorefronts() {
  try {
    const response = await fetch("/api/storefronts");

    if (!response.ok) {
      throw new Error(`HTTP error! Status: ${response.status}`);
    }

    const data = await response.json();
    const storefrontArray = Array.isArray(data) ? data : [data];

    storefronts = storefrontArray.map(store => {
      const previewImages = [
        store.preview_image_1,
        store.preview_image_2,
        store.preview_image_3,
        store.preview_image_4
      ].map(getSafeUrl).filter(Boolean);

      return {
        id: store.id,
        name: store.brand_name || "Unnamed Storefront",
        categories: Array.isArray(store.categories)
          ? store.categories
          : String(store.categories || "")
              .split(",")
              .map(category => category.trim())
              .filter(Boolean),
        items: store.item_count || 0,
        logo: getSafeUrl(store.logo_url) || null,
        images: previewImages.length > 0
          ? previewImages
          : (getSafeUrl(store.banner_url)
              ? [getSafeUrl(store.banner_url)]
              : [])
      };
    });

    renderStorefronts();
  } catch (error) {
    console.error("Error fetching storefronts from Flask API:", error);

    // XSS protection added by Rochele Solmon: use textContent instead of HTML.
    if (grid) {
      const message = document.createElement("p");
      message.style.color = "#888";
      message.style.fontStyle = "italic";
      message.style.textAlign = "center";
      message.style.gridColumn = "1/-1";
      message.style.padding = "2rem";
      message.textContent = "Could not load storefronts. Please try again.";
      grid.replaceChildren(message);
    }
  }
}

// Navigation pane functionality.
const menuBtn = document.querySelector(".menu-btn");
const navPane = document.getElementById("navPane");
const navOverlay = document.getElementById("navOverlay");

// Open menu.
if (menuBtn && navPane && navOverlay) {
  menuBtn.addEventListener("click", () => {
    navPane.classList.toggle("active");
    navOverlay.classList.toggle("active");
  });
}

// Close menu when clicking overlay.
if (navOverlay && navPane) {
  navOverlay.addEventListener("click", () => {
    navPane.classList.remove("active");
    navOverlay.classList.remove("active");
  });
}

// SEARCH BAR FUNCTIONALITY
const searchInput = document.getElementById("searchInput");

function filterStorefronts(query) {
  const filtered = storefronts.filter(store =>
    String(store.name || "").toLowerCase().includes(query.toLowerCase())
  );

  if (!grid) return;

  grid.replaceChildren();

  if (!filtered.length) {
    // XSS protection added by Rochele Solmon: search text is inserted as text.
    const message = document.createElement("p");
    message.style.color = "#c9c9c9";
    message.style.fontStyle = "italic";
    message.style.textAlign = "center";
    message.style.gridColumn = "1/-1";
    message.style.padding = "2rem";
    message.textContent = `No storefronts found for "${query}"`;
    grid.appendChild(message);
    return;
  }

  filtered.forEach(store => {
    const card = createCard(store);
    grid.appendChild(card);
  });
}

// Filter storefronts as the user types.
if (searchInput) {
  searchInput.addEventListener("input", () => {
    const query = searchInput.value.trim();

    if (!query) {
      renderStorefronts();
    } else {
      filterStorefronts(query);
    }
  });
}

// Initial render of storefront cards.
fetchStorefronts();