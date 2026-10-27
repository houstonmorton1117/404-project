/*
    my_storefront.js

    The Vault Campus Marketplace
    CSC 405 Sp 26'
    Created by Day Ekoi - Iteration 4 - 3/22/2026
    Implemented & Updated by Day Ekoi - Iteration 5 - 4/9/2026
    Updated by Day Ekoi - Iteration 5 - 4/20/26

    XSS fixes added by Rochele Solmon.
*/

// Get references
const pageTitle = document.getElementById("pageTitle");
const storeDescription = document.getElementById("storeDescription");
const contactInfo = document.getElementById("contactInfo");
const bannerBox = document.getElementById("bannerBox");
const bannerFallback = document.getElementById("bannerFallback");
const logoImg = document.getElementById("logoImg");
const logoFallback = document.getElementById("logoFallback");
const listingGrid = document.getElementById("listingGrid");
const storefrontStatusBanner = document.getElementById("storefrontStatusBanner");
const editStorefrontBtn = document.getElementById("editStorefrontBtn");
const createListingBtn = document.getElementById("createListingBtn");
const viewStorefrontBtn = document.getElementById("viewStorefrontBtn");
const deactivateStorefrontBtn = document.getElementById("deactivateStorefrontBtn");

let storefrontId = null;
let currentUser = null;

// XSS protection added by Rochele Solmon:
// Validate URLs before using them in image sources or CSS.
function getSafeUrl(value) {
    if (!value) return "";

    try {
        const url = new URL(String(value), window.location.origin);

        if (url.protocol === "http:" || url.protocol === "https:") {
            return url.href;
        }
    } catch (_error) {}

    return "";
}

// Render an empty state using textContent instead of HTML.
function renderEmpty(message) {
    // XSS protection added by Rochele Solmon.
    if (!listingGrid) return;

    const paragraph = document.createElement("p");
    paragraph.style.color = "#888";
    paragraph.style.fontStyle = "italic";
    paragraph.style.gridColumn = "1/-1";
    paragraph.style.textAlign = "center";
    paragraph.textContent = message;

    listingGrid.replaceChildren(paragraph);
}

function closeListingMenus() {
    document.querySelectorAll(".listing-menu-dropdown.active").forEach((menu) => {
        menu.classList.remove("active");
    });
}

function setButtonDisabledState(button, disabled) {
    if (!button) return;

    button.disabled = disabled;
    button.classList.toggle("is-disabled", disabled);
}

// Builds a single listing card.
function createListingCard(item) {
    const card = document.createElement("div");
    card.className = "listing-card";

    const title = item.title || item.name || "Untitled";
    const price = `$${Number(item.price || 0).toFixed(2)}`;
    const imageUrl = getSafeUrl(item.image_url);
    const status = item.status || "ACTIVE";

    const stateActionLabel = status === "DELETED"
        ? "Restore Listing"
        : (status === "INACTIVE" ? "Reactivate Listing" : "Deactivate Listing");

    // XSS protection added by Rochele Solmon:
    // Escape backend values before inserting them into HTML.
    const safeTitle = String(title).replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);

    const safeStatus = String(status).replace(/[&<>"']/g, character => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[character]);

    card.innerHTML = `
        ${imageUrl
            ? `<img class="listing-card-image" src="${safeTitle && imageUrl ? imageUrl.replace(/&/g, "&amp;").replace(/"/g, "&quot;") : ""}" alt="${safeTitle}">`
            : `<div class="listing-card-image listing-card-image--empty"></div>`
        }
        <div class="listing-card-body">
            <p class="listing-card-title">${safeTitle}</p>
            <p class="listing-card-price">${price}</p>
            <p class="listing-card-meta">Status: ${safeStatus}</p>
            <div class="listing-menu-wrap">
                <button type="button" class="listing-menu-trigger" aria-label="Open listing actions">...</button>
                <div class="listing-menu-dropdown">
                    <button type="button" class="listing-menu-item listing-menu-edit">Edit Listing</button>
                    <button type="button" class="listing-menu-item listing-menu-toggle">${stateActionLabel}</button>
                    <button type="button" class="listing-menu-item listing-menu-delete">Delete Listing</button>
                </div>
            </div>
        </div>
    `;

    const trigger = card.querySelector(".listing-menu-trigger");
    const dropdown = card.querySelector(".listing-menu-dropdown");
    const editBtn = card.querySelector(".listing-menu-edit");
    const toggleBtn = card.querySelector(".listing-menu-toggle");
    const deleteBtn = card.querySelector(".listing-menu-delete");

    trigger.addEventListener("click", (event) => {
        event.stopPropagation();

        const isActive = dropdown.classList.contains("active");
        closeListingMenus();
        dropdown.classList.toggle("active", !isActive);
    });

    editBtn.addEventListener("click", () => {
        if (status === "DELETED") return;

        const id = Number(item.id);
        if (Number.isInteger(id) && id > 0) {
            window.location.href = `/listings/${id}/edit`;
        }
    });

    toggleBtn.addEventListener("click", async () => {
        const endpoint = status === "DELETED"
            ? "restore"
            : (status === "INACTIVE" ? "reactivate" : "deactivate");

        const actionLabel = endpoint;
        const id = Number(item.id);

        if (!Number.isInteger(id) || id <= 0) return;

        const confirmed = window.confirm(
            `Are you sure you want to ${actionLabel} this listing?`
        );

        if (!confirmed) return;

        try {
            const response = await fetch(`/api/listings/${id}/${endpoint}`, {
                method: "PATCH",
                headers: {
                    "X-User-Id": currentUser?.id || "",
                    "X-User-Role": currentUser?.role || "user",

                    // CSRF protection added by Rochele Solmon
                    "X-CSRFToken":
                        document.querySelector('meta[name="csrf-token"]')?.content
                        || document.querySelector('input[name="csrf_token"]')?.value
                }
            });

            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(result.error || `Failed to ${actionLabel} listing.`);
            }

            await loadMyStorefront();
        } catch (error) {
            alert(error.message || `Unable to ${actionLabel} listing.`);
        }
    });

    deleteBtn.addEventListener("click", async () => {
        if (status === "DELETED") return;

        const id = Number(item.id);
        if (!Number.isInteger(id) || id <= 0) return;

        const confirmed = window.confirm("Are you sure you want to delete this listing?");
        if (!confirmed) return;

        try {
            const response = await fetch(`/api/listings/${id}`, {
                method: "DELETE",
                headers: {
                    "X-User-Id": currentUser?.id || "",
                    "X-User-Role": currentUser?.role || "user",

                    // CSRF protection added by Rochele Solmon
                    "X-CSRFToken":
                        document.querySelector('meta[name="csrf-token"]')?.content
                        || document.querySelector('input[name="csrf_token"]')?.value
                }
            });

            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(result.error || "Failed to delete listing.");
            }

            await loadMyStorefront();
        } catch (error) {
            alert(error.message || "Unable to delete listing.");
        }
    });

    if (status === "DELETED") {
        editBtn.disabled = true;
        deleteBtn.disabled = true;
        editBtn.classList.add("is-disabled");
        deleteBtn.classList.add("is-disabled");
    }

    return card;
}

// Fetches the storefront and listings and renders the page.
async function loadMyStorefront() {
    try {
        const userRes = await fetch("/auth/api/auth/me");

        if (!userRes.ok) {
            window.location.href = "/auth/login";
            return;
        }

        const user = await userRes.json();
        currentUser = user;

        const sfRes = await fetch("/api/storefronts/me", {
            headers: {
                "X-User-Id": user.id,
                "X-User-Role": user.role
            }
        });

        if (!sfRes.ok) {
            if (pageTitle) pageTitle.textContent = "No Storefront Found";

            // XSS protection added by Rochele Solmon:
            // Build the empty state with DOM elements instead of HTML strings.
            if (listingGrid) {
                const wrapper = document.createElement("div");
                wrapper.style.textAlign = "center";
                wrapper.style.padding = "2rem";

                const message = document.createElement("p");
                message.style.color = "#888";
                message.style.fontStyle = "italic";
                message.style.marginBottom = "1rem";
                message.textContent = "You don't have a storefront yet.";

                const link = document.createElement("a");
                link.href = "/storefronts/create";

                const button = document.createElement("button");
                button.className = "action-btn";
                button.textContent = "Create Your Storefront";

                link.appendChild(button);
                wrapper.appendChild(message);
                wrapper.appendChild(link);
                listingGrid.replaceChildren(wrapper);
            }

            return;
        }

        const storefront = await sfRes.json();
        storefrontId = storefront.id;
        const storefrontIsActive = storefront.is_active !== false;

        if (pageTitle) {
            pageTitle.textContent = storefront.brand_name || "My Storefront";
        }

        if (contactInfo) {
            contactInfo.textContent = storefront.contact_info || "";
        }

        if (storeDescription) {
            storeDescription.textContent = storefront.bio || "";
        }

        if (storefrontStatusBanner) {
            storefrontStatusBanner.style.display = storefrontIsActive ? "none" : "block";
        }

        // XSS protection added by Rochele Solmon: validate banner URL.
        const bannerUrl = getSafeUrl(storefront.banner_url);

        if (bannerUrl && bannerBox) {
            // Use CSS URL escaping to prevent breaking out of the url() value.
            const escapedBannerUrl = bannerUrl.replace(/["\\\n\r]/g, character =>
                "\\" + character
            );

            bannerBox.style.backgroundImage = `url("${escapedBannerUrl}")`;
            bannerBox.style.backgroundSize = "cover";
            bannerBox.style.backgroundPosition = "center";

            if (bannerFallback) {
                bannerFallback.style.display = "none";
            }
        }

        // XSS protection added by Rochele Solmon: validate logo URL.
        const logoUrl = getSafeUrl(storefront.logo_url);

        if (logoUrl && logoImg) {
            logoImg.src = logoUrl;
            logoImg.style.display = "block";

            if (logoFallback) {
                logoFallback.style.display = "none";
            }
        }

        // Wire up buttons now that we have the storefront ID.
        const safeStorefrontId = Number(storefrontId);

        if (editStorefrontBtn) {
            editStorefrontBtn.onclick = () => {
                if (Number.isInteger(safeStorefrontId) && safeStorefrontId > 0) {
                    window.location.href = `/storefronts/${safeStorefrontId}/edit`;
                }
            };
        }

        if (viewStorefrontBtn) {
            setButtonDisabledState(viewStorefrontBtn, !storefrontIsActive);

            viewStorefrontBtn.onclick = storefrontIsActive
                ? () => {
                    if (Number.isInteger(safeStorefrontId) && safeStorefrontId > 0) {
                        window.location.href = `/storefronts/${safeStorefrontId}`;
                    }
                }
                : null;
        }

        if (createListingBtn) {
            setButtonDisabledState(createListingBtn, !storefrontIsActive);

            createListingBtn.onclick = storefrontIsActive
                ? () => {
                    window.location.href = "/listings/create";
                }
                : null;
        }

        if (deactivateStorefrontBtn) {
            deactivateStorefrontBtn.onclick = async () => {
                const confirmed = confirm(
                    "Are you sure you want to deactivate your storefront?\n\nIt will be hidden from the marketplace. You can reactivate it later by contacting support."
                );

                if (!confirmed) return;

                try {
                    const res = await fetch(
                        `/api/storefronts/${safeStorefrontId}/deactivate`,
                        {
                            method: "PATCH",
                            headers: {
                                "X-User-Id": user.id,
                                "X-User-Role": user.role,

                                // CSRF protection added by Rochele Solmon
                                "X-CSRFToken":
                                    document.querySelector('meta[name="csrf-token"]')?.content
                                    || document.querySelector('input[name="csrf_token"]')?.value
                            }
                        }
                    );

                    if (res.ok) {
                        alert("Your storefront has been deactivated.");
                        window.location.href = "/storefronts";
                    } else {
                        const err = await res.json().catch(() => ({}));
                        alert("Could not deactivate: " + (err.error || "Unknown error"));
                    }
                } catch (_error) {
                    alert("Something went wrong. Please try again.");
                }
            };
        }

        // Fetch listings.
        const listRes = await fetch("/api/listings/my?include_deleted=1", {
            headers: {
                "X-User-Id": user.id,
                "X-User-Role": user.role
            }
        });

        if (!listRes.ok) {
            renderEmpty("Could not load listings.");
            return;
        }

        const listings = await listRes.json();

        const visibleListings = Array.isArray(listings)
            ? listings.filter(item => item.status !== "DELETED")
            : [];

        if (!listingGrid) return;

        listingGrid.replaceChildren();

        if (!visibleListings.length) {
            renderEmpty("No listings yet. Create your first listing!");
            return;
        }

        visibleListings.forEach(item => {
            listingGrid.appendChild(createListingCard(item));
        });

    } catch (error) {
        console.error("Error loading my storefront:", error);

        if (pageTitle) {
            pageTitle.textContent = "Could not load storefront.";
        }

        renderEmpty("Something went wrong.");
    }
}

// Run on page load.
loadMyStorefront();

document.addEventListener("click", () => {
    closeListingMenus();
});