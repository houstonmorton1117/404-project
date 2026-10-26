# Seeds demo storefronts and listings using the product photos already in
# static/images/, so the storefront grid has real, visible content without
# needing AWS S3 credentials (which aren't configured for local dev).
#
# Safe to re-run: deletes any previous demo_* users first (cascades to their
# storefronts/listings/images/sizes), then recreates everything fresh.

from db import get_connection
from utils.auth_utils import hash_password

DEMO_PASSWORD = "showtime123"

BRANDS = [
    {
        "username": "demo_nike",
        "email": "demo_nike@hamptonu.edu",
        "brand_name": "Swoosh Collective",
        "bio": "Streetwear essentials with a classic athletic edge.",
        "categories": "Streetwear,Athletic",
        "listings": [
            {
                "title": "Classic Pullover Hoodie",
                "price": 54.00,
                "image": "nikehoodie1.png",
            },
            {
                "title": "Court Jacket",
                "price": 78.00,
                "image": "nikejacket.png",
            },
        ],
    },
    {
        "username": "demo_essentials",
        "email": "demo_essentials@hamptonu.edu",
        "brand_name": "The Essentials Line",
        "bio": "Minimal, everyday staples built to last.",
        "categories": "Minimalist,Basics",
        "listings": [
            {
                "title": "Essential Crewneck",
                "price": 42.00,
                "image": "essentials1.png",
            },
            {
                "title": "Essential Oversized Tee",
                "price": 28.00,
                "image": "essentials3.png",
            },
        ],
    },
    {
        "username": "demo_onyx",
        "email": "demo_onyx@hamptonu.edu",
        "brand_name": "Onyx",
        "bio": "Dark, minimal silhouettes for everyday wear.",
        "categories": "Streetwear,Minimalist",
        "listings": [
            {
                "title": "Onyx Signature Hoodie",
                "price": 60.00,
                "image": "onyxhoodie.png",
            },
        ],
    },
    {
        "username": "demo_vondutch",
        "email": "demo_vondutch@hamptonu.edu",
        "brand_name": "Von Dutch Revival",
        "bio": "Y2K-inspired pieces, made for Hampton's campus.",
        "categories": "Y2K,Streetwear",
        "listings": [
            {
                "title": "Trucker Graphic Tee",
                "price": 36.00,
                "image": "vondutch1.png",
            },
            {
                "title": "Retro Zip Hoodie",
                "price": 58.00,
                "image": "vondutch3.png",
            },
        ],
    },
]

SIZES = [("S", 4), ("M", 6), ("L", 6), ("XL", 3)]


def seed():
    conn = get_connection()
    cur = conn.cursor()

    usernames = [b["username"] for b in BRANDS]
    cur.execute("DELETE FROM users WHERE username = ANY(%s)", (usernames,))
    conn.commit()

    for brand in BRANDS:
        cur.execute(
            "INSERT INTO users (username, password, email, role) VALUES (%s, %s, %s, 'user') RETURNING id",
            (brand["username"], hash_password(DEMO_PASSWORD), brand["email"]),
        )
        user_id = cur.fetchone()[0]

        preview_images = [f"/static/images/{l['image']}" for l in brand["listings"]]
        preview_images += [None] * (4 - len(preview_images))

        cur.execute(
            """
            INSERT INTO storefronts
                (owner_id, brand_name, bio, categories, is_active,
                 preview_image_1, preview_image_2, preview_image_3, preview_image_4)
            VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id, brand["brand_name"], brand["bio"], brand["categories"],
                *preview_images[:4],
            ),
        )
        storefront_id = cur.fetchone()[0]

        for listing in brand["listings"]:
            cur.execute(
                """
                INSERT INTO listings
                    (storefront_id, title, description, price, fulfillment_type,
                     quantity_on_hand, sizes_available, status)
                VALUES (%s, %s, %s, %s, 'IN_STOCK', %s, %s, 'ACTIVE')
                RETURNING id
                """,
                (
                    storefront_id,
                    listing["title"],
                    f"{listing['title']} from {brand['brand_name']}.",
                    listing["price"],
                    sum(q for _, q in SIZES),
                    '["S","M","L","XL"]',
                ),
            )
            listing_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO listing_images (listing_id, image_url, is_primary)
                VALUES (%s, %s, TRUE)
                """,
                (listing_id, f"/static/images/{listing['image']}"),
            )

            for size, qty in SIZES:
                cur.execute(
                    """
                    INSERT INTO listing_sizes (listing_id, size, quantity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (listing_id, size) DO UPDATE SET quantity = EXCLUDED.quantity
                    """,
                    (listing_id, size, qty),
                )

    conn.commit()
    cur.close()
    conn.close()
    print(f"Seeded {len(BRANDS)} storefronts with listings and images.")


if __name__ == "__main__":
    seed()
