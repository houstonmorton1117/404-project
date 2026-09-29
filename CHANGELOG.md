# Changelog

What our team has changed since we took over The Vault, and what it took to get the app running. For step-by-step setup instructions, see the [README](README.md).

---

## Fixed: buyers could set their own prices

*September 23, 2026*

### The problem

When a shopper clicked **Add to Cart**, the browser sent the item's price along with the request, and the server saved whatever price it received. Checkout then added up the prices stored in the cart. Anyone who edited that request, for example with the browser's developer tools, could:

- buy any item for $0.01, or change its name in their order;
- enter a negative quantity and get a negative order total.

Carts are saved in the database and reloaded at login, so a tampered price would stay in the cart until checkout.

### What we changed

| File | Change |
|---|---|
| `backend/controllers/auth_controller.py` | **Add to cart** now looks up the item's title and price in the `listings` table and ignores any name or price the browser sends. It rejects a missing item ID, and quantities that aren't whole numbers of at least 1 (`-3`, `0`, `abc`), with a 400 error. If the database lookup fails, it returns an error instead of adding the item anyway. |
| `backend/models/checkout_model.py` | `check_listing_availability()` now also returns the listing's current title and price. |
| `backend/services/checkout_service.py` | **Checkout** prices every item again from the `listings` table. The order total and each item's `price_at_purchase` use that price, never the price stored in the cart. Items without a listing ID, or with a quantity below 1, are rejected. |
| `static/js/storefront_view.js`, `templates/account.html` | The store page and the wishlist's **+ Cart** button no longer send a price or item name. |
| `backend/tests/test_cart_price.py` | **New.** Automated tests CF-06 to CF-08 (below). |

### How it works now

- The price saved in the cart is copied from the listing when the item is added. It's only used to show the cart.
- Checkout always charges each listing's price **at the moment of checkout**.
- **Known limitation:** if a seller changes a price after someone adds the item, the cart page still shows the old price, but checkout charges the new one.

### How we tested it

Automated tests, which create their own test accounts and listing and then delete them:

```bash
./venv/bin/python -m unittest backend/tests/test_cart_price.py -v      # Mac
venv\Scripts\python -m unittest backend\tests\test_cart_price.py -v    # Windows
```

| Test | What it checks | Result |
|---|---|---|
| CF-06 Price tampering | Adds a $50.00 listing while sending a fake $0.01 price and a fake name. The cart stores the real title and $50.00. | Pass |
| CF-07 Invalid quantity | Quantities of `-3`, `0`, and `abc` are each rejected with a 400 error, and nothing is added. | Pass |
| CF-08 Checkout re-pricing | The cart's stored price is changed to $0.01 and the listing's price to $60.00. Checkout charges $60.00 per item (total $120.00 for 2) and records $60.00 as `price_at_purchase`. | Pass |

We also tested by hand on a local copy using `curl`, including a cart that was tampered with before the fix. It was charged the real price.

### Documentation updated

The team's Word documents aren't stored in this repo. Each one got a new revision-history entry describing the change:

| Document | Revision | Sections updated |
|---|---|---|
| Functional Specifications | 6.0 | 3.1.1.9 Cart Item, 3.1.4 data dictionary (`price_at_purchase`), 4.1.1, 4.1.4.7 |
| Requirements | 6.0 | 1.2.1, 4.1.1, 4.1.4.7 |
| Design Specifications | 6.0 | 2.4, 3.1, 3.3.3.6 (new "Server-side pricing" constraint), 3.5.1, 3.5.3.4 |
| Test Plan | 3.0 | 2.1, 3.2.1.2 (new test file), 3.2.1.3 (test cases CF-06 to CF-08), 3.5 test log |

---

## Getting the app running locally

*September 23, 2026*

The original team ran The Vault on AWS: an RDS database, S3 for images, and Elastic Beanstalk for hosting. We don't have their AWS account, so we set it up to run on our own computers. **The app's code didn't need any changes to run.** Everything below was setup.

| What we needed | Why |
|---|---|
| **Python 3.12** | macOS includes Python 3.9, but two packages in `requirements.txt` (`click` and `python-dotenv`) need Python 3.10 or newer. |
| **PostgreSQL 16 on our own computers** | The original database was on the original team's AWS account, which we can't access. |
| **An empty database named `vault`** | For the app to store its tables in. |
| **A `venv` folder with the packages from `requirements.txt`** | Keeps the app's packages separate from the rest of the computer. |
| **A new `.env` file** | The original `.env` wasn't included. `.env.example` is out of date: its `DATABASE_URL` setting isn't read by the code, which uses `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and `DB_PORT`. |
| **Running `backend/init_db.py`** | Creates the app's 11 tables. |
| **Running `app.py`** | Starts the site at http://127.0.0.1:5000. |

**Still not working locally:** image uploads (listing photos, store logos, return photos). They need an Amazon S3 bucket and keys, which we don't have yet.

---

## Repository setup

*September 23, 2026*

- Uploaded the original project code to this repository.
- Added `.ebextensions/` to `.gitignore`. The original team's copy of that folder contains their deployment settings, including a real database password, and this repository is public.
- Rewrote the README with setup instructions for Mac and Windows, a git workflow for the team, and troubleshooting.
