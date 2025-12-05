from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_session import Session
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash
import gspread
import requests
import json
import time
import uuid
import os
import x 
import re
# import dictionary
import io
import csv
from datetime import datetime, timedelta

from oauth2client.service_account import ServiceAccountCredentials
from icecream import ic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Needed for sessions (login, flash messages, etc.)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

@app.route("/")
def landing_page():
    # If user is logged in, redirect to home
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("landing_page.html")


@app.route("/home")
def home():
    """Home page - Twitter + SoundCloud style feed."""
    # Check if user is logged in
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Get posts with user info, ordered by newest first
        cursor.execute("""
            SELECT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at,
                   u.id as user_id, u.name as user_name, u.avatar as user_avatar,
                   (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = %s) as user_liked
            FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 50
        """, (user_id,))
        posts = cursor.fetchall()
        
        # Get user's following count
        cursor.execute("SELECT COUNT(*) as following_count FROM follows WHERE follower_id = %s", (user_id,))
        following = cursor.fetchone()["following_count"]
        
        # Get user's followers count
        cursor.execute("SELECT COUNT(*) as followers_count FROM follows WHERE following_id = %s", (user_id,))
        followers = cursor.fetchone()["followers_count"]
        
        # Get current user's avatar for composer
        cursor.execute("SELECT avatar FROM users WHERE id = %s", (user_id,))
        current_user = cursor.fetchone()
        current_user_avatar = current_user["avatar"] if current_user else None
        
        cursor.close()
        db.close()
        
        return render_template(
            "home.html",
            posts=posts,
            user_name=session["user_name"],
            user_id=user_id,
            following=following,
            followers=followers,
            current_user_avatar=current_user_avatar
        )
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return render_template("home.html", posts=[], user_name=session.get("user_name", ""), error="Error loading feed"), 500


@app.route("/signup", methods=["GET", "POST"])
@app.route("/signup/<lan>", methods=["GET", "POST"])
def signup(lan="english"):

    if lan not in x.allowed_languages:
        lan = "english"
    x.default_language = lan

    if request.method == "GET":
        return render_template("signup.html", lan=lan)



    try:
        # use shared validation helpers from x.py
        user_email = x.validate_user_email()
        user_password = x.validate_user_password()
        user_username = x.validate_user_username()
        user_first_name = x.validate_user_first_name()

        # map your validated fields into the current users schema
        # users: id(INT AI), name, email, password_hash, avatar, bio, role, is_verified, is_blocked, ...
        user_name = user_username  # store username in the name column
        user_avatar = "https://avatar.iran.liara.run/public/40"
        user_bio = user_first_name  # simple example: keep first name in bio

        db, cursor = x.db()

        # Check if email already exists
        cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
        if cursor.fetchone():
            raise Exception("An account with this email already exists.", 400)

        password_hash = generate_password_hash(user_password)
        
        # Generate verification token
        verification_token = uuid.uuid4().hex
        
        # Insert user (is_verified defaults to FALSE)
        cursor.execute(
            """
            INSERT INTO users (name, email, password_hash, avatar, bio, is_verified)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            """,
            (user_name, user_email, password_hash, user_avatar, user_bio),
        )
        db.commit()
        user_id = cursor.lastrowid
        
        # Store verification token (expires in 24 hours)
        expires_at = datetime.now() + timedelta(hours=24)
        cursor.execute(
            """
            INSERT INTO email_verification_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, verification_token, expires_at),
        )
        db.commit()
        
        # Send verification email using x.send_email() (professor's pattern)
        verification_url = request.url_root.rstrip('/') + url_for('verify_account', key=verification_token)
        email_template = render_template("_email_verify_account.html", user_verification_key=verification_token, verification_url=verification_url)
        ic(email_template)
        x.send_email(user_email, "Verify your account", email_template)
        
        # Redirect to verification page showing "check your email" message
        return redirect(url_for("verify_account", email=user_email))

    except Exception as ex:
        ic(ex)

        # default error
        message = "System under maintenance"
        status = 500

        # user-level validation errors from x.validate_* (Exception(msg, 400))
        if len(ex.args) >= 2 and ex.args[1] == 400:
            message = ex.args[0]
            status = 400
        # DB duplicate checks
        elif "Duplicate entry" in str(ex) and user_email and user_email in str(ex):
            message = "Email already registered"
            status = 400
        elif "Duplicate entry" in str(ex) and user_username and user_username in str(ex):
            message = "Username already registered"
            status = 400

        return render_template(
            "signup.html",
            error=message,
            lan=lan,
        ), status

    finally:
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()

    error = None
    if not re.match(x.REGEX_EMAIL, email):
        error = "Please enter a valid email address."
    elif not password:
        error = "Password is required."

    if error:
        return render_template("login.html", error=error, email=email), 400

    try:
        db, cursor = x.db()
        cursor.execute(
            "SELECT id, name, password_hash, is_verified FROM users WHERE email = %s", (email,)
        )
        user = cursor.fetchone()
        cursor.close()
        db.close()

        if not user or not check_password_hash(user["password_hash"], password):
            return render_template(
                "login.html",
                error="Invalid email or password.",
                email=email,
            ), 400

        if not user["is_verified"]:
            return render_template(
                "login.html",
                error="Please verify your email address before logging in. Check your inbox for the verification link.",
                email=email,
            ), 400

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("home"))
    except Exception as e:
        print(e, flush=True)
        return render_template(
            "login.html",
            error="Something went wrong while logging you in. Please try again.",
            email=email,
        ), 500
    
    finally:
            if "cursor" in locals(): cursor.close()
            if "db" in locals(): db.close()


@app.route("/verify-account", methods=["GET"])
def verify_account():
    """Verify user's email address using the key from the email (professor's pattern)."""
    email = request.args.get("email", "")
    email_type = request.args.get("type", "verification")  # 'verification' or 'password_reset'
    
    # If no key provided, just show "check your email" message (after signup)
    if not request.args.get("key"):
        if email_type == "password_reset":
            message = f"We've sent a password reset email to {email}. Please click the link in the email to reset your password."
        elif email_type == "password_change":
            message = f"We've sent a password change email to {email}. Please click the link in the email to change your password."
        elif email_type == "email_change":
            message = f"We've sent a verification email to {email}. Please click the link in the email to verify your new email address."
        else:
            message = f"We've sent a verification email to {email}. Please click the link in the email to verify your account."
        return render_template("verify_email.html", success=False, message=message, email=email, email_type=email_type)
    
    try:
        # Validate the verification key using professor's validation function
        user_verification_key = x.validate_uuid4_without_dashes(request.args.get("key", ""))
        
        db, cursor = x.db()
        
        # Find the token and check if it's valid and not expired
        cursor.execute(
            """
            SELECT user_id 
            FROM email_verification_tokens 
            WHERE token = %s AND expires_at > NOW()
            """,
            (user_verification_key,)
        )
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid key", 400)
        
        user_id = token_data["user_id"]
        
        # Update user to verified and update created_at timestamp (professor's pattern adapted)
        cursor.execute(
            """
            UPDATE users 
            SET is_verified = TRUE, 
                created_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (user_id,)
        )
        db.commit()
        
        if cursor.rowcount != 1:
            raise Exception("Invalid key", 400)
        
        # Delete the used token
        cursor.execute(
            "DELETE FROM email_verification_tokens WHERE token = %s",
            (user_verification_key,)
        )
        db.commit()
        
        cursor.close()
        db.close()
        
        return redirect(url_for('login'))
        
    except Exception as ex:
        ic(ex)
        if "db" in locals():
            db.rollback()
        
        # User errors
        if len(ex.args) >= 2 and ex.args[1] == 400:
            message = ex.args[0] if ex.args[0] else "Invalid verification key."
            return render_template("verify_email.html", success=False, message=message, email=email), 400
        
        # System or developer error
        return render_template("verify_email.html", success=False, message="Cannot verify user", email=email), 500
    
    finally:
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()


@app.route("/post", methods=["POST"])
def create_post():
    """Create a new post."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        content = request.form.get("content", "").strip()
        audio_file = request.files.get("audio_file")
        
        if not content and not audio_file:
            return redirect(url_for("home"))
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        media_path = None
        media_type = None
        
        if audio_file and audio_file.filename:
            # Save audio file (simplified - you'll need proper file handling)
            filename = f"{user_id}_{uuid.uuid4().hex}_{audio_file.filename}"
            upload_path = os.path.join("static", "uploads", filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            audio_file.save(upload_path)
            media_path = filename
            media_type = "audio"
        
        cursor.execute(
            """
            INSERT INTO posts (user_id, content, media_path, media_type)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, content if content else None, media_path, media_type)
        )
        db.commit()
        cursor.close()
        db.close()
        
        return redirect(url_for("home"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("home"))


@app.route("/like/<int:post_id>", methods=["POST"])
def toggle_like(post_id):
    """Toggle like on a post."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Check if already liked
        cursor.execute(
            "SELECT id FROM likes WHERE user_id = %s AND post_id = %s",
            (user_id, post_id)
        )
        existing_like = cursor.fetchone()
        
        if existing_like:
            # Unlike
            cursor.execute(
                "DELETE FROM likes WHERE user_id = %s AND post_id = %s",
                (user_id, post_id)
            )
            cursor.execute(
                "UPDATE posts SET total_likes = total_likes - 1 WHERE id = %s",
                (post_id,)
            )
        else:
            # Like
            cursor.execute(
                "INSERT INTO likes (user_id, post_id) VALUES (%s, %s)",
                (user_id, post_id)
            )
            cursor.execute(
                "UPDATE posts SET total_likes = total_likes + 1 WHERE id = %s",
                (post_id,)
            )
        
        db.commit()
        cursor.close()
        db.close()
        
        return redirect(url_for("home"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("home"))


@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    """Add a comment to a post."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        content = request.form.get("content", "").strip()
        if not content:
            return redirect(url_for("home"))
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        cursor.execute(
            "INSERT INTO comments (user_id, post_id, content) VALUES (%s, %s, %s)",
            (user_id, post_id, content)
        )
        db.commit()
        cursor.close()
        db.close()
        
        return redirect(url_for("home"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("home"))


@app.route("/search")
def search():
    """Search for users and posts."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    query = request.args.get("q", "").strip()
    if not query:
        return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        
        # Search users
        cursor.execute(
            "SELECT id, name, email, avatar FROM users WHERE name LIKE %s OR email LIKE %s LIMIT 10",
            (f"%{query}%", f"%{query}%")
        )
        users = cursor.fetchall()
        
        # Search posts
        cursor.execute(
            """
            SELECT p.id, p.content, p.created_at, u.name as user_name, u.avatar as user_avatar
            FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.content LIKE %s
            ORDER BY p.created_at DESC
            LIMIT 20
            """,
            (f"%{query}%",)
        )
        posts = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template("search.html", query=query, users=users, posts=posts)
    except Exception as e:
        ic(e)
        return redirect(url_for("home"))


@app.route("/follow/<int:user_id>", methods=["POST"])
def toggle_follow(user_id):
    """Follow/unfollow a user."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    if user_id == session["user_id"]:
        return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        follower_id = session["user_id"]
        
        # Check if already following
        cursor.execute(
            "SELECT id FROM follows WHERE follower_id = %s AND following_id = %s",
            (follower_id, user_id)
        )
        existing_follow = cursor.fetchone()
        
        if existing_follow:
            # Unfollow
            cursor.execute(
                "DELETE FROM follows WHERE follower_id = %s AND following_id = %s",
                (follower_id, user_id)
            )
        else:
            # Follow
            cursor.execute(
                "INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)",
                (follower_id, user_id)
            )
        
        db.commit()
        cursor.close()
        db.close()
        
        return redirect(request.referrer or url_for("home"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("home"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Forgot password - send reset email."""
    if request.method == "GET":
        return render_template("forgot_password.html")
    
    try:
        email = request.form.get("email", "").strip().lower()
        
        if not re.match(x.REGEX_EMAIL, email):
            return render_template(
                "forgot_password.html",
                error="Please enter a valid email address.",
                email=email
            ), 400
        
        db, cursor = x.db()
        
        # Check if user exists
        cursor.execute("SELECT id, name FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if not user:
            # Don't reveal if email exists (security best practice)
            cursor.close()
            db.close()
            return redirect(url_for("verify_email", email=email, type="password_reset"))
        
        user_id = user["id"]
        user_name = user["name"]
        
        # Generate reset token
        reset_token = uuid.uuid4().hex
        
        # Store reset token (expires in 1 hour)
        expires_at = datetime.now() + timedelta(hours=1)
        cursor.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, reset_token, expires_at)
        )
        db.commit()
        
        # Send password reset email
        reset_url = request.url_root.rstrip('/') + url_for('reset_password', key=reset_token)
        email_template = render_template(
            "_email_reset_password.html",
            user_name=user_name,
            reset_url=reset_url
        )
        ic(email_template)
        x.send_email(email, "Reset your EchoVerse password", email_template)
        
        cursor.close()
        db.close()
        
        # Redirect to verify_email page showing "check your email" message
        return redirect(url_for("verify_email", email=email, type="password_reset"))
        
    except Exception as ex:
        ic(ex)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return render_template(
            "forgot_password.html",
            error="An error occurred. Please try again.",
            email=email if "email" in locals() else ""
        ), 500


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    """Reset password using token from email."""
    key = request.args.get("key", "") or request.form.get("key", "")
    
    if request.method == "GET":
        if not key:
            return render_template("reset_password.html", error="Invalid reset link.")
        return render_template("reset_password.html", key=key)
    
    # POST - process password reset
    try:
        reset_token = x.validate_uuid4_without_dashes(key)
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        
        # Validate password
        if not re.match(x.REGEX_USER_PASSWORD, password):
            return render_template(
                "reset_password.html",
                key=key,
                error="Invalid password. Password must be between 6 and 50 characters."
            ), 400
        
        if password != password_confirm:
            return render_template(
                "reset_password.html",
                key=key,
                error="Passwords do not match."
            ), 400
        
        db, cursor = x.db()
        
        # Find valid reset token
        cursor.execute(
            """
            SELECT user_id 
            FROM password_reset_tokens 
            WHERE token = %s AND expires_at > NOW()
            """,
            (reset_token,)
        )
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid or expired reset link", 400)
        
        user_id = token_data["user_id"]
        
        # Update password
        password_hash = generate_password_hash(password)
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id)
        )
        db.commit()
        
        if cursor.rowcount != 1:
            raise Exception("Invalid reset link", 400)
        
        # Delete used token
        cursor.execute(
            "DELETE FROM password_reset_tokens WHERE token = %s",
            (reset_token,)
        )
        db.commit()
        
        cursor.close()
        db.close()
        
        # Show success message
        return render_template("reset_password.html", success=True, message="Password reset successfully! You can now log in.")
        
    except Exception as ex:
        ic(ex)
        if "db" in locals():
            db.rollback()
        
        message = "An error occurred during password reset."
        if len(ex.args) >= 2 and ex.args[1] == 400:
            message = ex.args[0] if ex.args[0] else "Invalid or expired reset link."
        
        return render_template(
            "reset_password.html",
            key=key if "key" in locals() else "",
            error=message
        ), 400
    
    finally:
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()


@app.route("/profile")
def profile():
    """User profile page."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Get user info
        cursor.execute(
            "SELECT id, name, email, avatar, bio, created_at FROM users WHERE id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
        
        # Get user stats
        cursor.execute("SELECT COUNT(*) as post_count FROM posts WHERE user_id = %s", (user_id,))
        post_count = cursor.fetchone()["post_count"]
        
        cursor.execute("SELECT COUNT(*) as following_count FROM follows WHERE follower_id = %s", (user_id,))
        following = cursor.fetchone()["following_count"]
        
        cursor.execute("SELECT COUNT(*) as followers_count FROM follows WHERE following_id = %s", (user_id,))
        followers = cursor.fetchone()["followers_count"]
        
        # Get user's posts
        cursor.execute("""
            SELECT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at
            FROM posts p
            WHERE p.user_id = %s
            ORDER BY p.created_at DESC
            LIMIT 50
        """, (user_id,))
        posts = cursor.fetchall()
        
        cursor.close()
        db.close()
        
        return render_template(
            "profile.html",
            user=user,
            post_count=post_count,
            following=following,
            followers=followers,
            posts=posts
        )
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("home"))


@app.route("/profile/update-name", methods=["POST"])
def update_name():
    """Update user's name."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        new_name = request.form.get("name", "").strip()
        
        if not new_name or len(new_name) < 2 or len(new_name) > 100:
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        cursor.execute(
            "UPDATE users SET name = %s, updated_at = NOW() WHERE id = %s",
            (new_name, user_id)
        )
        db.commit()
        
        session["user_name"] = new_name
        
        cursor.close()
        db.close()
        
        return redirect(url_for("profile"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("profile"))


@app.route("/profile/update-email", methods=["POST"])
def update_email():
    """Update user's email (requires verification)."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        new_email = request.form.get("email", "").strip().lower()
        
        if not re.match(x.REGEX_EMAIL, new_email):
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Check if email already exists
        cursor.execute("SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id))
        if cursor.fetchone():
            cursor.close()
            db.close()
            return redirect(url_for("profile"))
        
        # Generate verification token for email change
        verification_token = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(hours=24)
        
        # Store token temporarily (we'll verify before updating)
        cursor.execute(
            """
            INSERT INTO email_verification_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, verification_token, expires_at)
        )
        db.commit()
        
        # Send verification email
        verification_url = request.url_root.rstrip('/') + url_for('verify_email_change', key=verification_token, email=new_email)
        email_template = render_template(
            "_email_verify_email_change.html",
            user_name=session["user_name"],
            new_email=new_email,
            verification_url=verification_url
        )
        x.send_email(new_email, "Verify your new email address", email_template)
        
        cursor.close()
        db.close()
        
        return redirect(url_for("verify_email", email=new_email, type="email_change"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("profile"))


@app.route("/profile/update-avatar", methods=["POST"])
def update_avatar():
    """Update user's avatar (file upload)."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        avatar_file = request.files.get("avatar_file")
        
        if not avatar_file or not avatar_file.filename:
            return redirect(url_for("profile"))
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_ext = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else ''
        
        if file_ext not in allowed_extensions:
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Save avatar file
        filename = f"avatar_{user_id}_{uuid.uuid4().hex}.{file_ext}"
        upload_path = os.path.join("static", "uploads", "avatars", filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        avatar_file.save(upload_path)
        
        # Store relative path in database
        avatar_path = f"uploads/avatars/{filename}"
        
        cursor.execute(
            "UPDATE users SET avatar = %s, updated_at = NOW() WHERE id = %s",
            (avatar_path, user_id)
        )
        db.commit()
        
        cursor.close()
        db.close()
        
        return redirect(url_for("profile"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("profile"))


@app.route("/profile/update-bio", methods=["POST"])
def update_bio():
    """Update user's bio."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        bio = request.form.get("bio", "").strip()
        
        # Limit bio length
        if len(bio) > 500:
            bio = bio[:500]
        
        db, cursor = x.db()
        user_id = session["user_id"]
        
        cursor.execute(
            "UPDATE users SET bio = %s, updated_at = NOW() WHERE id = %s",
            (bio if bio else None, user_id)
        )
        db.commit()
        
        cursor.close()
        db.close()
        
        return redirect(url_for("profile"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("profile"))


@app.route("/profile/change-password", methods=["POST"])
def change_password():
    """Request password change (sends verification email)."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        user_id = session["user_id"]
        
        # Get user email
        cursor.execute("SELECT email, name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        # Generate password change token
        change_token = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(hours=1)
        
        # Store token in password_reset_tokens table
        cursor.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
            """,
            (user_id, change_token, expires_at)
        )
        db.commit()
        
        # Send password change email
        change_url = request.url_root.rstrip('/') + url_for('reset_password', key=change_token)
        email_template = render_template(
            "_email_reset_password.html",
            user_name=user["name"],
            reset_url=change_url
        )
        x.send_email(user["email"], "Change your EchoVerse password", email_template)
        
        cursor.close()
        db.close()
        
        return redirect(url_for("verify_email", email=user["email"], type="password_change"))
    except Exception as e:
        ic(e)
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()
        return redirect(url_for("profile"))


@app.route("/verify-email-change", methods=["GET"])
def verify_email_change():
    """Verify email change using token."""
    try:
        key = request.args.get("key", "")
        new_email = request.args.get("email", "")
        
        if not key or not new_email:
            return render_template("verify_email.html", success=False, message="Invalid verification link.")
        
        reset_token = x.validate_uuid4_without_dashes(key)
        
        db, cursor = x.db()
        
        # Find valid token
        cursor.execute(
            """
            SELECT user_id 
            FROM email_verification_tokens 
            WHERE token = %s AND expires_at > NOW()
            """,
            (reset_token,)
        )
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid or expired verification link", 400)
        
        user_id = token_data["user_id"]
        
        # Check if new email already exists
        cursor.execute("SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id))
        if cursor.fetchone():
            raise Exception("Email already in use", 400)
        
        # Update email
        cursor.execute(
            "UPDATE users SET email = %s, updated_at = NOW() WHERE id = %s",
            (new_email, user_id)
        )
        db.commit()
        
        if cursor.rowcount != 1:
            raise Exception("Invalid verification link", 400)
        
        # Delete used token
        cursor.execute(
            "DELETE FROM email_verification_tokens WHERE token = %s",
            (reset_token,)
        )
        db.commit()
        
        cursor.close()
        db.close()
        
        return render_template("verify_email.html", success=True, message="Your email has been updated successfully!")
        
    except Exception as ex:
        ic(ex)
        if "db" in locals():
            db.rollback()
        
        message = "An error occurred during email verification."
        if len(ex.args) >= 2 and ex.args[1] == 400:
            message = ex.args[0] if ex.args[0] else "Invalid or expired verification link."
        
        return render_template("verify_email.html", success=False, message=message), 400
    
    finally:
        if "cursor" in locals():
            cursor.close()
        if "db" in locals():
            db.close()


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing_page"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)