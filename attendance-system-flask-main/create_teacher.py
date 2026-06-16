import sys
import os # Import os to get the directory path
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone
import getpass # For hidden password prompt

# --- TEMPORARY APP SETUP ---
# This script needs to know about our app and database models
# We import the models directly from our main app.py file

# Temporarily add the project directory to the path to find 'app' module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app import app, db, Teacher # Import app, db, and Teacher model
except ImportError as e:
    print(f"Error importing from app.py: {e}")
    print("Please make sure this script is in the same directory as app.py")
    sys.exit(1)

def create_super_admin():
    """
    Creates the initial Super Admin account.
    This account has the 'Admin' role and is pre-approved.
    """
    print("--- Create Super Admin Account ---")
    print("This account will have full administrative privileges.")
    
    with app.app_context():
        # Check if an Admin already exists
        if Teacher.query.filter_by(role='Admin').first():
            print("An Admin account already exists. Aborting.")
            return

        # Get details from user
        username = input("Enter Admin username: ").strip()
        email = input("Enter Admin email: ").strip()
        
        # Get password securely
        password = getpass.getpass("Enter Admin password (min 6 chars): ").strip()
        confirm_password = getpass.getpass("Confirm Admin password: ").strip()

        if password != confirm_password:
            print("Passwords do not match. Aborting.")
            return

        if len(password) < 6:
            print("Password must be at least 6 characters. Aborting.")
            return
            
        if not username or not email:
            print("Username and email cannot be empty. Aborting.")
            return
            
        try:
            # Create the new Admin teacher
            admin_teacher = Teacher(
                username=username,
                email=email,
                role='Admin',
                is_approved=True # Super Admin is approved by default
            )
            admin_teacher.set_password(password) # Hash the password
            
            db.session.add(admin_teacher)
            db.session.commit()
            
            print(f"\nSuccessfully created Admin account for '{username}'.")
            print("You can now run 'python app.py' and log in.")

        except Exception as e:
            db.session.rollback()
            print(f"\nAn error occurred: {e}")
            if "violates unique constraint" in str(e).lower():
                print("This username or email already exists in the database.")
            

if __name__ == "__main__":
    try:
        create_super_admin()
    except Exception as e:
        print(f"A fatal error occurred: {e}")

