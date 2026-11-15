import sys
import os
from flask import Flask, render_template, redirect, url_for, session, request
from flask_wtf.csrf import CSRFProtect #Added by rochele solmon
# Added by Joshua Hall on 11/14/2026 - IP-based rate limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend'))) # Updated 3/19/2026 by Ryan Grimes

from controllers.listing_controller import listing_bp
from controllers.storefront_controller import storefront_bp, storefront_pages_bp  # Updated by Day E 3/22/26
from controllers.purchase_controller import purchase_bp
from controllers.wishlist_controller import wishlist_bp
from controllers.admin_controller import admin_bp
from controllers.auth_controller import auth_bp # Updated 3/19/2026 by Ryan Grimes
from controllers.return_controller import returns_bp
from controllers.checkout_controller import checkout_bp
from controllers.notification_controller import notification_bp
from controllers.follow_controller import follow_bp
from controllers.stripe_webhook_controller import stripe_webhook_bp  # Added 11/14/26 - Stripe webhook
from init_db import create_vault_tables
from utils.payments import get_publishable_key
from backend.listing_search import listing_search


def create_app():
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    app.secret_key = os.environ['SECRET_KEY'] # Updated 10/26/26 by Obi Achebe
    csrf = CSRFProtect(app) #added by Rochele Solmon
    # Added by Joshua Hall on 11/14/2026 - Initialize IP-based rate limiting
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri="memory://"
    ) 

     # Secure session cookie settings - Rochele
    app.config.update(
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=os.getenv(
                "SESSION_COOKIE_SECURE", "false"
            ).lower() == "true"
    )

     # Security response headers (Rochele 11/13/2026)
    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https://api.stripe.com; "
            "frame-src https://js.stripe.com https://hooks.stripe.com; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://checkout.stripe.com"
        )
        return response

    # Allow image uploads up to 25MB (4 listing photos per request).
    # Keep in sync with .platform/nginx/conf.d/upload_size.conf
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

    @app.errorhandler(413)
    def request_too_large(_err):
        return {"error": "Image is too large. Total upload size must be under 25 MB."}, 413

    #sign out users whose account was deactivated while they were logged in, on their next request - jasmine Mark 11/12/26
    @app.before_request
    def sign_out_deactivated_users():
        user_id = session.get('user_id')
        if not user_id or request.endpoint == 'static':
            return None
        try:
            from models.admin_model import _is_user_active
            if _is_user_active(user_id) is not False:
                return None
        except Exception as e:
            # Don't take down every page if the lookup fails; the login check still blocks them.
            print(f"[auth] Could not check account status: {e}")
            return None

        session.clear()
        if request.path.startswith('/api/') or request.method != 'GET':
            return {"error": "This account has been deactivated. Contact an administrator."}, 401
        return redirect(url_for('auth.login'))

    # Run DB migrations on every startup so new columns are always present
    # If the database can't be set up, stop with a clear message instead of starting an app that fails later with confusing errors. - added by jasmine mark 11/14/26
    try:
        from init_db import create_vault_tables
        create_vault_tables()
    except Exception as err:
        raise RuntimeError(
            f"Could not set up the database: {str(err).strip()}. "
            "Check DB_HOST, DB_NAME, DB_USER and DB_PASSWORD in .env."
        ) from err

    #The Welcome Screen (Default) Ryan Grimes 3/19/2026
    @app.route('/')
    def index():
        return render_template('index.html')

    # Route to the main storefront page after login - Updated 3/22/2026
    @app.route('/storefront')
    def storefront():
        return render_template('storefront.html')
        
    #Route to the lsiting search - 11/12/2026
    @app.route('/listings')
    def listings_page():
        return render_template('listings.html')

    # Route to the "Create Storefront" form - Updated 3/22/2026
    @app.route('/create-storefront')
    def create_storefront():
        return render_template('create_storefront.html')

    # Route to the "Create Listing" form - Updated 3/24/2026
    @app.route('/create-listing')
    def create_listing():
        return render_template('create_listing.html')

    #Route to the Checkout - Updated 4/22/2026
    @app.route('/checkout')
    def checkout():
        if not session.get("user"):
            return redirect(url_for("auth.login", next=request.path))
        # Stripe.js needs the publishable (browser-safe) key; the secret key never leaves the server.
        return render_template('checkout.html', stripe_publishable_key=get_publishable_key())

    # Route to the Order Confirmation page - Added 4/22/2026
    @app.route('/order-confirmation')
    def order_confirmation():
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return render_template('order_confirmation.html')
    
    # Route to My Storefront dashboard page - Updated 4/9/2026
    @app.route('/my-storefront')
    def my_storefront():
        if not session.get("user"):
            return redirect(url_for("auth.login"))
        return render_template('my_storefront.html')

    # Register Blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    # Added by Joshua Hall on 11/14/2026 - Apply IP rate limits to authentication routes
    app.view_functions["auth.login"] = limiter.limit(
        "5 per minute",
        methods=["POST"]
    )(app.view_functions["auth.login"])

    app.view_functions["auth.signup"] = limiter.limit(
        "3 per hour",
        methods=["POST"]
    )(app.view_functions["auth.signup"])
    app.register_blueprint(listing_bp)
    app.register_blueprint(storefront_bp)
    app.register_blueprint(storefront_pages_bp)  # Updated by Day E 3/22/26
    app.register_blueprint(purchase_bp)
    app.register_blueprint(wishlist_bp)
    app.register_blueprint(admin_bp) # Updated 3/19/2026 by Ryan Grimes
    app.register_blueprint(returns_bp)
    app.register_blueprint(checkout_bp, url_prefix='/api')
    app.register_blueprint(notification_bp)
    app.register_blueprint(follow_bp)
    app.register_blueprint(listing_search)
    # Stripe can't send our CSRF token; webhook requests are verified by Stripe's signature instead.
    app.register_blueprint(stripe_webhook_bp)
    csrf.exempt(stripe_webhook_bp)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
