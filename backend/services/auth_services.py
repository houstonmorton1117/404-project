#By Ryan Grimes 2/27/2026
#Register user and validate login
from utils.auth_utils import hash_password, verify_password
from models.admin_model import set_user_active

#added by jasmine mark 11/12/26
HAMPTON_EMAIL_DOMAINS = ("@hamptonu.edu", "@my.hamptonu.edu")

# validate_login() returns this in place of the role when the password is right but an admin has deactivated the account.
ACCOUNT_DEACTIVATED = "deactivated"

# stand-in password rule for the Account Settings change-password form.
# replace with josh's password rules function once his branch is merged
def is_valid_password(pw):
    return isinstance(pw, str) and len(pw) >= 8

#Email validation update (Rochele SOlmon)
class AuthService:
    def register_user(self, username, password, email, db_conn): #Stores a user's unique ID, username, password, and email into the database
        if not email.lower().endswith(("@hamptonu.edu", "@my.hamptonu.edu")): 
            print(f"You Must Use a Hampton University Associated Email") 
            return False, "You Must Use a Hampton University Associated Email"

        hashed_pw = hash_password(password)
        try:
            cur = db_conn.cursor() #Creates a point for data to be entered into database
            query = "INSERT INTO users (username, password, email) VALUES (%s, %s, %s)" #Enters data into SQL database. '%s' prevents SQLi by forcing the database to treat user input strictly as data, not as executable SQL code
            cur.execute(query, (username, hashed_pw, email)) #Inputs data at cursor point
            db_conn.commit() #Saves changes
            cur.close() #Closes cursor
            return True, "Signup Successful"
        except Exception as e:
            print(f"Registration Error: {e}")
            db_conn.rollback() #If connection fails, all changes are voided to prevent saving partial data
            return False, "Signup Failed"
        
    def validate_login(self, username, password, db_conn):
        try: 
            cur = db_conn.cursor() #Creates a pointer
            cur.execute("SELECT password, role, is_active FROM users WHERE username = %s", (username,)) #Has pointer search for occurence of entered credentials
            result = cur.fetchone() #Fetches the row of data that matches the query
            cur.close() #Closes cursor

            if result and verify_password(result[0], password): #If username and password hash match return true
                # Deactivated accounts can't log in, even with the right password - Jasmine Mark 11/12/26
                if not result[2]:
                    return False, ACCOUNT_DEACTIVATED
                return True, result [1]
        
            return False, None
        except Exception as e:
            print(f"Login Error: {e}")
            return False, None
    
    def get_user_cart(self, db_conn, user_id): #Retrieves all items from the persistent database for a specific user.
        try:
            cur = db_conn.cursor()
            cur.execute("""
                SELECT item_id, item_name, price, quantity, size, id
                FROM cart_items WHERE user_id = %s
            """, (user_id,))
            rows = cur.fetchall()
            return [{'id': r[0], 'name': r[1], 'price': float(r[2]), 'quantity': r[3], 'size': r[4], 'cart_item_id': r[5]} for r in rows]
        except Exception as e:
            print(f"Service Error: Could not fetch cart: {e}")
            return []

    def clear_user_cart(self, db_conn, user_id): #Removes all items from the database bag (useful after checkout).
        try:
            cur = db_conn.cursor()
            cur.execute("DELETE FROM cart_items WHERE user_id = %s", (user_id,))
            db_conn.commit()
        except Exception as e:
            print(f"Service Error: Could not clear cart: {e}")

    # Account Settings (Settings tab) - added by Jasmine Mark 11/12/26
    # Both methods take the user_id from the session (never the form), so a user can only change their own account.
    def update_email(self, user_id, new_email, db_conn):
        new_email = (new_email or "").strip()
        if not new_email.lower().endswith(HAMPTON_EMAIL_DOMAINS):
            return False, "You Must Use a Hampton University Associated Email"

        try:
            cur = db_conn.cursor()
            # Same rule as signup: no two users may share an email (checked case-insensitively)
            cur.execute(
                "SELECT 1 FROM users WHERE LOWER(email) = LOWER(%s) AND id <> %s",
                (new_email, user_id),
            )
            if cur.fetchone():
                cur.close()
                return False, "That email is already in use by another account."

            cur.execute("UPDATE users SET email = %s WHERE id = %s", (new_email, user_id))
            updated = cur.rowcount
            db_conn.commit()
            cur.close()
            if not updated:
                return False, "Account not found."
            return True, "Email updated."
        except Exception as e:
            print(f"Update Email Error: {e}")
            db_conn.rollback()
            return False, "Could not update email right now."

    def change_password(self, user_id, current_password, new_password, confirm_password, db_conn):
        if not current_password or not new_password:
            return False, "Please fill in all password fields."
        if new_password != confirm_password:
            return False, "New passwords do not match."
        if not is_valid_password(new_password):
            return False, "New password must be at least 8 characters."

        try:
            cur = db_conn.cursor()
            cur.execute("SELECT password FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            # Require the current password so a stolen session alone can't change it
            if not row or not verify_password(row[0], current_password):
                cur.close()
                return False, "Current password is incorrect."

            cur.execute("UPDATE users SET password = %s WHERE id = %s", (hash_password(new_password), user_id))
            db_conn.commit()
            cur.close()
            return True, "Password updated."
        except Exception as e:
            print(f"Change Password Error: {e}")
            db_conn.rollback()
            return False, "Could not change password right now."

    # Deactivate my account (Settings tab) - added by Jasmine Mark 11/13/26
    # this requires the current password; only an admin can restore the account afterwards.
    def deactivate_own_account(self, user_id, password, db_conn):
        if not password:
            return False, "Please enter your password."

        try:
            cur = db_conn.cursor()
            cur.execute("SELECT password FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
            cur.close()
            if not row or not verify_password(row[0], password):
                return False, "Password is incorrect."

            if not set_user_active(user_id, False):
                return False, "Account not found."
            return True, "Your account has been deactivated."
        except Exception as e:
            print(f"Deactivate Account Error: {e}")
            db_conn.rollback()
            return False, "Could not deactivate your account right now."
