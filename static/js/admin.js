/* File Created By David Jackson */

// XSS protection added by Rochele Solmon
// Display values as text instead of interpreting them as HTML.
function addTextCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value ?? "";
    row.appendChild(cell);
}

// USERS SECTION

/*
 * Fetch all users from backend and display them in table
 * Calls: GET /admin/users
 */
async function loadUsers() {
    const response = await fetch('/admin/users');
    const users = await response.json();

    const table = document.querySelector('#usersTable tbody');
    table.replaceChildren();

    users.forEach(user => {
        const row = document.createElement("tr");

        addTextCell(row, user.id);
        addTextCell(row, user.username || "");
        addTextCell(row, user.email);
        addTextCell(row, user.role || "user");
        addTextCell(row, user.created_at || "");

        const actionCell = document.createElement("td");
        const button = document.createElement("button");
        button.className = "delete";
        button.textContent = "Delete";
        button.addEventListener("click", () => deleteUser(user.id));
        actionCell.appendChild(button);
        row.appendChild(actionCell);

        table.appendChild(row);
    });
}

/*
 * Delete a user by ID
 * Calls: DELETE /admin/users/<id>
 */
async function deleteUser(userId) {
    await fetch(`/admin/users/${encodeURIComponent(userId)}`, {
        method: 'DELETE',
        headers: {
            // CSRF protection added by Rochele Solmon
            "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content
                || document.querySelector('input[name="csrf_token"]')?.value
        }
    });

    loadUsers();
}


// LISTINGS SECTION

/*
 * Fetch all listings and display them
 * Calls: GET /admin/listings
 */
async function loadListings() {
    const response = await fetch('/admin/listings');
    const listings = await response.json();

    const table = document.querySelector('#listingsTable tbody');
    table.replaceChildren();

    listings.forEach(listing => {
        const row = document.createElement("tr");

        addTextCell(row, listing.id);
        addTextCell(row, listing.storefront_id);
        addTextCell(row, listing.title);
        addTextCell(row, listing.price);
        addTextCell(row, listing.quantity_on_hand);
        addTextCell(row, listing.status || "ACTIVE");
        addTextCell(row, listing.fulfillment_type || "");
        addTextCell(row, listing.created_at || "");

        const actionCell = document.createElement("td");
        const button = document.createElement("button");
        button.className = "delete";
        button.textContent = "Delete";
        button.addEventListener("click", () => deleteListing(listing.id));
        actionCell.appendChild(button);
        row.appendChild(actionCell);

        table.appendChild(row);
    });
}

/*
 * Delete a listing by ID
 * Calls: DELETE /admin/listings/<id>
 */
async function deleteListing(listingId) {
    await fetch(`/admin/listings/${encodeURIComponent(listingId)}`, {
        method: 'DELETE',
        headers: {
            // CSRF protection added by Rochele Solmon
            "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content
                || document.querySelector('input[name="csrf_token"]')?.value
        }
    });

    loadListings();
}


// STOREFRONTS SECTION

/*
 * Fetch all storefronts
 * Calls: GET /admin/storefronts
 */
async function loadStorefronts() {
    const response = await fetch('/admin/storefronts');
    const stores = await response.json();

    const table = document.querySelector('#storefrontsTable tbody');
    table.replaceChildren();

    stores.forEach(store => {
        const row = document.createElement("tr");

        addTextCell(row, store.id);
        addTextCell(row, store.brand_name || store.name || "");
        addTextCell(row, store.owner_id);

        const actionCell = document.createElement("td");
        const button = document.createElement("button");
        button.className = "delete";
        button.textContent = "Delete";
        button.addEventListener("click", () => deleteStorefront(store.id));
        actionCell.appendChild(button);
        row.appendChild(actionCell);

        table.appendChild(row);
    });
}

/*
 * Delete a storefront by ID
 * Calls: DELETE /admin/storefronts/<id>
 */
async function deleteStorefront(storeId) {
    await fetch(`/admin/storefronts/${encodeURIComponent(storeId)}`, {
        method: 'DELETE',
        headers: {
            // CSRF protection added by Rochele Solmon
            "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content
                || document.querySelector('input[name="csrf_token"]')?.value
        }
    });

    loadStorefronts();
}


// RETURNS SECTION

async function loadReturns() {
    const response = await fetch('/admin/returns');
    const returns = await response.json();

    const table = document.querySelector('#returnsTable tbody');
    table.replaceChildren();

    returns.forEach(item => {
        const row = document.createElement("tr");

        addTextCell(row, item.id);

        const userCell = document.createElement("td");
        userCell.appendChild(document.createTextNode(item.username || ""));

        const email = document.createElement("small");
        email.textContent = item.email || "";
        userCell.appendChild(document.createElement("br"));
        userCell.appendChild(email);
        row.appendChild(userCell);

        addTextCell(row, item.order_number);
        addTextCell(row, item.has_damage ? "Yes" : "No");

        const imageCell = document.createElement("td");

        // Added by Rochele Solmon: only allow safe HTTP(S) image links.
        if (item.damage_image_url) {
            try {
                const imageUrl = new URL(item.damage_image_url, window.location.origin);

                if (imageUrl.protocol === "https:" || imageUrl.protocol === "http:") {
                    const link = document.createElement("a");
                    link.href = imageUrl.href;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    link.textContent = "View";
                    imageCell.appendChild(link);
                } else {
                    imageCell.textContent = "Unavailable";
                }
            } catch {
                imageCell.textContent = "Unavailable";
            }
        } else {
            imageCell.textContent = "—";
        }

        row.appendChild(imageCell);

        const statusCell = document.createElement("td");
        const select = document.createElement("select");
        select.dataset.returnId = item.id;

        // Added by Rochele Solmon: build options safely without HTML interpolation.
        ["pending", "reviewed", "resolved"].forEach(status => {
            const option = document.createElement("option");
            option.value = status;
            option.textContent = status.charAt(0).toUpperCase() + status.slice(1);
            option.selected = item.status === status;
            select.appendChild(option);
        });

        statusCell.appendChild(select);

        const button = document.createElement("button");
        button.textContent = "Save";
        button.addEventListener("click", () => saveReturnStatus(item.id));
        statusCell.appendChild(button);

        row.appendChild(statusCell);

        addTextCell(row, item.reason);

        table.appendChild(row);
    });
}

async function saveReturnStatus(returnId) {
    const select = document.querySelector(
        `select[data-return-id="${CSS.escape(String(returnId))}"]`
    );

    if (!select) return;

    const response = await fetch(`/admin/returns/${encodeURIComponent(returnId)}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
            // CSRF protection added by Rochele Solmon
            "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content
                || document.querySelector('input[name="csrf_token"]')?.value
        },
        body: JSON.stringify({ status: select.value })
    });

    if (!response.ok) {
        alert("Failed to update return status.");
        return;
    }

    loadReturns();
}