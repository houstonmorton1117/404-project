# By Ryan Grimes - Updated 3/19/2026
# Updated by Jasmine Mark on 10/26/26 to fix redirect log in flow error
from flask import Blueprint, request, session, redirect, url_for, render_template, flash, jsonify
from services.auth_services import AuthService 
from config.db import get_connection
from models.checkout_model import check_listing_availability, OutOfStockError

from services.login_security_service import (
    check_login_lockout,
    record_failed_login,
    reset_failed_logins
)

auth_bp = Blueprint('auth', __name__)
service = AuthService()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')

        conn = get_connection()
        if conn is None:
            return "Database connection failed. <a href='/auth/login'>Try again</a>"

        #try finally loop for login logic - added by Jasmine Mark 9/30/26
        
        try:
            # Check whether this account is temporarily locked
            remaining_seconds = check_login_lockout(conn, user)

            if remaining_seconds > 0:
                return (
                    f"Too many failed login attempts. "
                    f"Please try again in {remaining_seconds} seconds. "
                    "<a href='/auth/login'>Back to Login</a>",
                    429
                )

            success, role = service.validate_login(user, pw, conn)

            if success:
                # Reset failed login attempts after a successful login
                reset_failed_logins(conn, user)

                session['user'] = user
                session['role'] = role

                #store user_id in sesion for storefront ownership checks - added by Day E 4/9/26
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM users WHERE username = %s", (user,))
                    row = cur.fetchone()
                    if row:
                        session['user_id'] = row[0] # Store user_id in session
                        session['cart'] = service.get_user_cart(conn, row[0]) # Load user's cart into session on login
                        cur.close()
                except Exception as e:
                    print(f"Error fetching user_id for session: {e}")

                #return redirect(url_for('auth.listings'))
                # Redirect based on role - added by David Jackson 3/23/2026
                if role and role.lower() == 'admin':
                    return redirect(url_for('admin.admin_dashboard'))

                # If the user got sent here from another page (e.g. clicked
                # Checkout while logged out), return them there instead of
                # always dropping them on the listings page. Only a relative
                # in-site path is honored, to avoid an open-redirect.
                next_url = request.form.get('next')
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect(url_for('auth.listings'))

            # Record an incorrect login attempt
            remaining_attempts = record_failed_login(conn, user)

            if remaining_attempts == 0:
                return (
                    "Too many failed login attempts. "
                    "Your account has been temporarily locked for 60 seconds. "
                    "<a href='/auth/login'>Back to Login</a>",
                    429
                )
            return (
                f"Invalid Credentials. "
                f"You have {remaining_attempts} attempt(s) remaining. "
                "<a href='/auth/login'>Try again</a>",
                401
            )
        
        finally:
            conn.close() # always release the connection after success or failure
    
    return render_template('login.html')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user = request.form.get('username') 
        pw = request.form.get('password')
        email = request.form.get('email')

        conn = get_connection()
        if conn is None:
            return "Database connection failed. <a href='/auth/signup'>Try again</a>"

        success, message = service.register_user(user, pw, email, conn)
        conn.close()

        if success:
            flash("Signup Successful! Please login with your new credentials.", "success")
            return redirect(url_for('auth.login'))
        return f"Signup Failed: {message} <a href='/auth/signup'>Try again</a>"
    
    return render_template('signup.html')

@auth_bp.route('/listings')
def listings():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    return render_template('storefront.html')

@auth_bp.route('/account')
def account():
    if 'user' not in session: 
        return redirect(url_for('auth.login'))
    return render_template('account.html')
    
@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@auth_bp.route('/cart')
def view_cart():
    if 'cart' not in session:
        session['cart'] = []
    return render_template('cart.html')

@auth_bp.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    # Called via fetch(), so always answer with JSON: a redirect here would be followed
    # silently and the caller would see the login page as a 200 "success".
    if 'user_id' not in session:
        return jsonify({
            "error": "Please login to add items to your bag.",
            "login_url": url_for('auth.login'),
        }), 401

    # Price and name come from the listings table, never from the client, so they can't be tampered with.
    item_id = request.form.get('item_id', type=int)
    quantity = request.form.get('quantity', type=int) if 'quantity' in request.form else 1
    size = request.form.get('size')

    if item_id is None:
        return jsonify({"error": "A valid item is required."}), 400
    if quantity is None or quantity < 1:
        return jsonify({"error": "Quantity must be a whole number of at least 1."}), 400

    # Count what's already in the bag so repeated adds can't go past the available stock.
    already_in_cart = sum(
        int(i.get('quantity', 1)) for i in session.get('cart', [])
        if i.get('id') == item_id and i.get('size') == size
    )

    try:
        item_name, price, _ = check_listing_availability(item_id, quantity + already_in_cart, size)
    except OutOfStockError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        print(f"DB Error checking listing availability: {e}")
        return jsonify({"error": "Unable to add item to cart right now."}), 500

    # PERSIST TO DATABASE
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cart_items (user_id, item_id, item_name, price, quantity, size)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (session['user_id'], item_id, item_name, price, quantity, size))
        cart_item_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error adding to cart: {e}")
        return jsonify({"error": "Unable to add item to cart right now."}), 500

    # Update session for immediate UI feedback
    if 'cart' not in session:
        session['cart'] = []

    cart_item = {'id': item_id, 'name': item_name, 'price': float(price), 'quantity': int(quantity), 'size': size, 'cart_item_id': cart_item_id}
    temp_cart = session['cart']
    temp_cart.append(cart_item)
    session['cart'] = temp_cart
    session.modified = True

    return jsonify({
        "message": f"Added {item_name} to your bag!",
        "cart_count": len(temp_cart),
    }), 200

@auth_bp.route('/remove_from_cart/<int:index>', methods=['POST'])
def remove_from_cart(index):
    if 'cart' in session and 'user_id' in session:
        temp_cart = session['cart']
        if 0 <= index < len(temp_cart):
            removed_item = temp_cart.pop(index)
            
            # REMOVE FROM DATABASE
            # Deletes by the cart row's own primary key (not name+size, which could
            # match the wrong row when the same item/size was added as two separate
            # cart rows). user_id is still checked so a user can only delete their own.
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute("""
                    DELETE FROM cart_items
                    WHERE id = %s AND user_id = %s
                """, (removed_item.get('cart_item_id'), session['user_id']))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"DB Error removing item: {e}")
            
            session['cart'] = temp_cart
            session.modified = True
            flash(f"Removed {removed_item['name']} from bag.", "info")
    return redirect(url_for('auth.view_cart'))

# Added by Day E 4/9/26 - returns current session user info for frontend auth checks
@auth_bp.route('/api/auth/me')
def get_current_session_user():
    if 'user' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users WHERE username = %s", (session['user'],))
        user = cur.fetchone()
        conn.close()

        if not user:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "id": user[0],
            "username": user[1],
            "role": user[2]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@auth_bp.route('/cart/json')
def get_cart_json():
    return jsonify(session.get('cart', []))


# Admin login route - added by David Jackson 4/19/26
@auth_bp.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')

        # Edited by rochele solmon: removed hardcoded admin credentials.
        # Admin authentication is now checked against the database.
        conn = get_connection()
        if conn is None:
            return "Database connection failed. <a href='/auth/admin-login'>Try again</a>"

       
        try:
            # Check if the account is temporarily locked
            remaining_seconds = check_login_lockout(conn, user)

            if remaining_seconds > 0:
                return (
                    f"Too many failed login attempts. "
                    f"Please try again in {remaining_seconds} seconds. "
                    "<a href='/auth/admin-login'>Back to Admin Login</a>",
                    429
                )

            success, role = service.validate_login(user, pw, conn)


            # Edited by rochele solmon: verify that the authenticated account
            # has an admin role before granting admin access.
            if success and role and role.lower() == 'admin':
                # Reset failed attempts after a successful admin login
                reset_failed_logins(conn, user)

                session['user'] = user
                session['role'] = role

                # Edited by rochele solmon: store the authenticated user's ID
                # in the server-side session for ownership checks.
                cur = conn.cursor()
                cur.execute("SELECT id FROM users WHERE username = %s", (user,))
                row = cur.fetchone()
                cur.close()

                if row:
                    session['user_id'] = row[0]

                return redirect(url_for('admin.admin_dashboard'))

            
            # Only count an incorrect password, not a valid non-admin login
            if not success:
                remaining_attempts = record_failed_login(conn, user)

                if remaining_attempts == 0:
                    return (
                        "Too many failed login attempts. "
                        "Your account has been locked for 60 seconds. "
                        "<a href='/auth/admin-login'>Back to Admin Login</a>",
                        429
                    )

                return (
                    f"Invalid Admin Credentials. "
                    f"You have {remaining_attempts} attempt(s) remaining. "
                    "<a href='/auth/admin-login'>Try again</a>",
                    401
                )

            return (
                "This account does not have administrator access. "
                "<a href='/auth/admin-login'>Back to Admin Login</a>",
                403
            )

        finally:
            conn.close()

    return render_template('admin_login.html')
