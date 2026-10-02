# By Ryan Grimes - Updated 3/19/2026
from flask import Blueprint, request, session, redirect, url_for, render_template, flash, jsonify
from services.auth_services import AuthService 
from config.db import get_connection
from models.checkout_model import check_listing_availability, OutOfStockError

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
            success, role = service.validate_login(user, pw, conn)

            if success:
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
                else:
                    return redirect(url_for('auth.listings'))

            return "Invalid Credentials. <a href='/auth/login'>Try again</a>"
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
    if 'user_id' not in session:
        flash("Please login to add items to your bag.", "error")
        return redirect(url_for('auth.login'))

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
        """, (session['user_id'], item_id, item_name, price, quantity, size))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error adding to cart: {e}")
        return jsonify({"error": "Unable to add item to cart right now."}), 500

    # Update session for immediate UI feedback
    if 'cart' not in session:
        session['cart'] = []
    
    cart_item = {'id': item_id, 'name': item_name, 'price': float(price), 'quantity': int(quantity), 'size': size}
    temp_cart = session['cart']
    temp_cart.append(cart_item)
    session['cart'] = temp_cart
    session.modified = True

    flash(f"Added {item_name} to your bag!", "success")
    return redirect(url_for('auth.view_cart'))

@auth_bp.route('/remove_from_cart/<int:index>', methods=['POST'])
def remove_from_cart(index):
    if 'cart' in session and 'user_id' in session:
        temp_cart = session['cart']
        if 0 <= index < len(temp_cart):
            removed_item = temp_cart.pop(index)
            
            # REMOVE FROM DATABASE
            try:
                conn = get_connection()
                cur = conn.cursor()
                # We delete one instance of this item for this user
                cur.execute("""
                    DELETE FROM cart_items 
                    WHERE id = (
                        SELECT id FROM cart_items 
                        WHERE user_id = %s AND item_name = %s AND size = %s
                        LIMIT 1
                    )
                """, (session['user_id'], removed_item['name'], removed_item['size']))
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

@auth_bp.route('/debug/session')
def debug_session():
    return jsonify(dict(session))

# Admin login route - added by David Jackson 4/19/26
@auth_bp.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        user = request.form.get('username')
        pw = request.form.get('password')

        # temporary hardcoded admin login for testing
        if user == "admin" and pw == "admin123":
            session['user'] = user
            session['role'] = 'admin'
            return redirect(url_for('admin.admin_dashboard'))

        return "Invalid Admin Credentials. <a href='/auth/admin-login'>Try again</a>"

    return render_template('admin_login.html')