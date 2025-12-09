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
import dictionary
import re
import io
import csv
from datetime import datetime, timedelta

from oauth2client.service_account import ServiceAccountCredentials
from icecream import ic
ic.configureOutput(prefix=f'----- | ', includeContext=True)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024

app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

##############################
@app.context_processor
def global_variables():
    def get_language_url(language):
        """Generate URL for current page with different language"""
        endpoint = request.endpoint
        view_args = dict(request.view_args) if request.view_args else {}
        query_args = dict(request.args)
        
        # Add/update language parameter
        query_args['lan'] = language
        
        # Handle special cases
        if endpoint == 'home':
            return url_for('home', lan=language)
        elif endpoint == 'profile':
            profile_user_id = view_args.get('profile_user_id')
            if profile_user_id:
                return url_for('profile', profile_user_id=profile_user_id) + f'?lan={language}'
            else:
                return url_for('profile') + f'?lan={language}'
        elif endpoint == 'explore':
            tag_name = request.args.get('tag_name')
            query_string = f'?lan={language}'
            if tag_name:
                query_string += f'&tag_name={tag_name}'
            return url_for('explore') + query_string
        elif endpoint in ['login', 'signup']:
            return url_for(endpoint, lan=language)
        else:
            # For other endpoints, fallback to home with language
            return url_for('home', lan=language)
    
    return dict(
        dictionary = dictionary,
        x = x,
        is_admin = is_admin(),
        get_language_url = get_language_url,
        current_language = getattr(x, 'default_language', 'english')
    )

##############################
def get_user():
    user = session.get("user")
    if user: return user
    if "user_id" in session:
        return {"id": session["user_id"], "name": session.get("user_name", "")}
    return None

def get_user_id():
    user = get_user()
    return user.get("id") if user else None

def is_admin():
    """Check if current user is an admin."""
    user_id = get_user_id()
    if not user_id:
        return False
    try:
        db, cursor = x.db()
        q = "SELECT role FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user = cursor.fetchone()
        return user and user.get("role") == "admin"
    except Exception as ex:
        ic(ex)
        return False
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)

def require_admin():
    """Decorator to require admin access."""
    user = get_user()
    if not user or not is_admin():
        return redirect(url_for("home"))
    return None

def is_ajax():
    return (request.is_json or 
            request.headers.get('Content-Type') == 'application/json' or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest')

def json_response(data, status=200):
    return jsonify(data), status

def cleanup_db(cursor=None, db=None):
    if cursor: cursor.close()
    if db: db.close()

@app.route("/")
@app.route("/<lan>")
def landing_page(lan="english"):
    if get_user(): return redirect(url_for("home"))
    if lan not in x.allowed_languages: lan = "english"
    x.default_language = lan
    return render_template("landing_page.html", lan=lan)


@app.route("/home")
@app.route("/home/<lan>")
@x.no_cache
def home(lan=None):
    user = get_user()
    if not user: return redirect(url_for("login"))
    
    # Handle language parameter
    if lan:
        if lan not in x.allowed_languages: lan = "english"
        x.default_language = lan
    else:
        # Default to english if no language specified
        lan = x.default_language if hasattr(x, 'default_language') else "english"
        x.default_language = lan
    
    try:
        db, cursor = x.db()
        user_id = user["id"]
        
        # Check if user is blocked
        q = "SELECT is_blocked FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user_data = cursor.fetchone()
        if user_data and user_data.get("is_blocked"):
            session.clear()
            return redirect(url_for("login"))
        
        q = """
            SELECT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at,
                   u.id as user_id, u.name as user_name, u.avatar as user_avatar, p.user_id as post_owner_id,
                   (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = %s) as user_liked,
                   (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comment_count,
                   GROUP_CONCAT(DISTINCT t.name ORDER BY t.name SEPARATOR ', ') as tags
            FROM posts p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN post_tags pt ON p.id = pt.post_id
            LEFT JOIN tags t ON pt.tag_id = t.id
            WHERE p.is_blocked = FALSE 
            AND u.is_blocked = FALSE
            AND u.id NOT IN (
                SELECT blocked_id FROM user_blocks WHERE blocker_id = %s
                UNION
                SELECT blocker_id FROM user_blocks WHERE blocked_id = %s
            )
            GROUP BY p.id
            ORDER BY p.created_at DESC
            LIMIT 50
        """
        cursor.execute(q, (user_id, user_id, user_id))
        posts = cursor.fetchall()
        
        for post in posts:
            q = """
                SELECT c.id, c.content, c.created_at, u.name as user_name, u.avatar as user_avatar
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.post_id = %s
                ORDER BY c.created_at ASC
            """
            cursor.execute(q, (post["id"],))
            post["comments"] = cursor.fetchall()
        
        q = "SELECT COUNT(*) as following_count FROM follows WHERE follower_id = %s"
        cursor.execute(q, (user_id,))
        following = cursor.fetchone()["following_count"]
        
        q = "SELECT COUNT(*) as followers_count FROM follows WHERE following_id = %s"
        cursor.execute(q, (user_id,))
        followers = cursor.fetchone()["followers_count"]
        
        q = "SELECT avatar FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        current_user = cursor.fetchone()
        current_user_avatar = current_user["avatar"] if current_user else None
        
        # Get trending tags (tags used in most posts in last 7 days, randomized)
        q = """
            SELECT t.name, COUNT(pt.post_id) as post_count
            FROM tags t
            JOIN post_tags pt ON t.id = pt.tag_id
            JOIN posts p ON pt.post_id = p.id
            WHERE p.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            AND p.is_blocked = FALSE
            GROUP BY t.id, t.name
            ORDER BY post_count DESC, RAND()
            LIMIT 5
        """
        cursor.execute(q)
        trending_tags = cursor.fetchall()
        
        # If not enough recent tags, get overall trending tags
        if len(trending_tags) < 3:
            q = """
                SELECT t.name, COUNT(pt.post_id) as post_count
                FROM tags t
                JOIN post_tags pt ON t.id = pt.tag_id
                JOIN posts p ON pt.post_id = p.id
                WHERE p.is_blocked = FALSE
                GROUP BY t.id, t.name
                ORDER BY post_count DESC, RAND()
                LIMIT 5
            """
            cursor.execute(q)
            trending_tags = cursor.fetchall()
        
        return render_template(
            "home.html",
            posts=posts,
            user_name=user.get("name", ""),
            user_id=user_id,
            following=following,
            followers=followers,
            current_user_avatar=current_user_avatar,
            trending_tags=trending_tags,
            is_admin=is_admin(),
            lan=lan
        )
    except Exception as ex:
        ic(ex)
        return render_template("home.html", posts=[], user_name=user.get("name", ""), error="Error loading feed", lan=lan if 'lan' in locals() else "english"), 500
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/signup", methods=["GET", "POST"])
@app.route("/signup/<lan>", methods=["GET", "POST"])
def signup(lan="english"):
    if lan not in x.allowed_languages: lan = "english"
    x.default_language = lan

    if request.method == "GET":
        return render_template("signup.html", lan=lan)

    if request.method == "POST":
        try:
            user_email = x.validate_user_email(lan)
            user_password = x.validate_user_password(lan)
            user_password_confirm = request.form.get("user_password_confirm", "").strip()
            if not user_password_confirm:
                user_password_confirm = request.form.get("password_confirm", "").strip()
            
            if user_password != user_password_confirm:
                raise Exception("Passwords do not match", 400)
            
            user_username = x.validate_user_username()
            user_first_name = x.validate_user_first_name()

            user_name = user_username
            user_avatar = None  # Will use default avatar from template
            user_bio = user_first_name

            db, cursor = x.db()
            q = "SELECT id FROM users WHERE email = %s"
            cursor.execute(q, (user_email,))
            if cursor.fetchone():
                raise Exception("An account with this email already exists.", 400)

            password_hash = generate_password_hash(user_password)
            verification_token = uuid.uuid4().hex
            
            q = """
                INSERT INTO users (name, email, password_hash, avatar, bio, is_verified)
                VALUES (%s, %s, %s, %s, %s, FALSE)
            """
            cursor.execute(q, (user_name, user_email, password_hash, user_avatar, user_bio))
            db.commit()
            user_id = cursor.lastrowid
            
            expires_at = datetime.now() + timedelta(hours=24)
            q = """
                INSERT INTO email_verification_tokens (user_id, token, expires_at)
                VALUES (%s, %s, %s)
            """
            cursor.execute(q, (user_id, verification_token, expires_at))
            db.commit()
            
            verification_url = request.url_root.rstrip('/') + url_for('verify_account', key=verification_token)
            email_template = render_template("_email_verify_account.html", user_verification_key=verification_token, verification_url=verification_url)
            x.send_email(user_email, "Verify your account", email_template)
            
            return redirect(url_for("verify_account", email=user_email))

        except Exception as ex:
            ic(ex)
            if len(ex.args) >= 2 and ex.args[1] == 400:
                return render_template("signup.html", error=ex.args[0], email=user_email if "user_email" in locals() else "", name=user_username if "user_username" in locals() else "", lan=lan), 400
            
            if "Duplicate entry" in str(ex) and "user_email" in locals() and user_email in str(ex):
                return render_template("signup.html", error="Email already registered", email=user_email, lan=lan), 400
            if "Duplicate entry" in str(ex) and "user_username" in locals() and user_username in str(ex):
                return render_template("signup.html", error="Username already registered", name=user_username, lan=lan), 400

            return render_template("signup.html", error="System under maintenance", lan=lan), 500

        finally:
            cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/login", methods=["GET", "POST"])
@app.route("/login/<lan>", methods=["GET", "POST"])
@x.no_cache
def login(lan="english"):
    if lan not in x.allowed_languages: lan = "english"
    x.default_language = lan
    
    if request.method == "GET":
        if get_user(): return redirect(url_for("home"))
        return render_template("login.html", lan=lan)

    if request.method == "POST":
        try:
            lang_code = x.language_code_map.get(lan, "en")
            user_email = x.validate_user_email(lan)
            user_password = x.validate_user_password(lan)
            
            q = "SELECT id, name, password_hash, is_verified, is_blocked FROM users WHERE email = %s"
            db, cursor = x.db()
            cursor.execute(q, (user_email,))
            user = cursor.fetchone()
            
            if not user: raise Exception(dictionary.user_not_found[lang_code], 400)
            if not check_password_hash(user["password_hash"], user_password):
                raise Exception(dictionary.invalid_credentials[lang_code], 400)
            if not user["is_verified"]:
                raise Exception(dictionary.user_not_verified[lang_code], 400)
            if user.get("is_blocked"):
                raise Exception("Your account has been blocked. Please contact support.", 400)

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user"] = {"id": user["id"], "name": user["name"]}
            
            return redirect(url_for("home"))
            
        except Exception as ex:
            ic(ex)
            if len(ex.args) >= 2 and ex.args[1] == 400:
                return render_template("login.html", error=ex.args[0], email=user_email if "user_email" in locals() else "", lan=lan), 400
            return render_template("login.html", error="System under maintenance", email="", lan=lan), 500
    
        finally:
            cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/verify-account", methods=["GET"])
def verify_account():
    email = request.args.get("email", "")
    email_type = request.args.get("type", "verification")
    
    if not request.args.get("key"):
        messages = {
            "password_reset": f"We've sent a password reset email to {email}. Please click the link in the email to reset your password.",
            "password_change": f"We've sent a password change email to {email}. Please click the link in the email to change your password.",
            "email_change": f"We've sent a verification email to {email}. Please click the link in the email to verify your new email address."
        }
        message = messages.get(email_type, f"We've sent a verification email to {email}. Please click the link in the email to verify your account.")
        return render_template("verify_email.html", success=False, message=message, email=email, email_type=email_type)
    
    try:
        user_verification_key = x.validate_uuid4_without_dashes(request.args.get("key", ""))
        db, cursor = x.db()
        
        q = """
            SELECT user_id 
            FROM email_verification_tokens 
            WHERE token = %s AND expires_at > NOW()
        """
        cursor.execute(q, (user_verification_key,))
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid key", 400)
        
        user_id = token_data["user_id"]
        q = """
            UPDATE users 
            SET is_verified = TRUE, 
                created_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """
        cursor.execute(q, (user_id,))
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Invalid key", 400)
        
        q = "DELETE FROM email_verification_tokens WHERE token = %s"
        cursor.execute(q, (user_verification_key,))
        db.commit()
        
        return redirect(url_for('login'))
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        message = ex.args[0] if len(ex.args) >= 2 and ex.args[1] == 400 else "Cannot verify user"
        return render_template("verify_email.html", success=False, message=message, email=email), 400 if len(ex.args) >= 2 and ex.args[1] == 400 else 500
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/post", methods=["POST"])
def create_post():
    user_id = get_user_id()
    if not user_id:
        return json_response({"error": "Not authenticated"}, 401) if is_ajax() else redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        
        # Verify user exists and is not blocked
        q = "SELECT id, is_blocked FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user = cursor.fetchone()
        
        if not user:
            session.clear()
            return json_response({"error": "User not found"}, 404) if is_ajax() else redirect(url_for("login"))
        
        if user.get("is_blocked"):
            session.clear()
            return json_response({"error": "Account is blocked"}, 403) if is_ajax() else redirect(url_for("login"))
        
        content = request.form.get("content", "").strip()
        audio_file = request.files.get("audio_file")
        tags_input = request.form.get("tags", "").strip()
        
        if not content and (not audio_file or not audio_file.filename):
            return json_response({"error": "Please enter content or upload an audio file"}, 400) if is_ajax() else redirect(url_for("home"))
        if content and len(content) > 500:
            return json_response({"error": "Content must be 500 characters or less"}, 400) if is_ajax() else redirect(url_for("home"))
        
        media_path = None
        media_type = None
        
        if audio_file and audio_file.filename:
            allowed_extensions = {'mp3', 'wav', 'ogg', 'm4a', 'aac'}
            file_ext = audio_file.filename.rsplit('.', 1)[1].lower() if '.' in audio_file.filename else ''
            if file_ext not in allowed_extensions:
                return json_response({"error": "Invalid audio file format"}, 400) if is_ajax() else redirect(url_for("home"))
            
            filename = f"{user_id}_{uuid.uuid4().hex}_{audio_file.filename}"
            upload_path = os.path.join("static", "uploads", filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            audio_file.save(upload_path)
            media_path = filename
            media_type = "audio"
        
        q = """
            INSERT INTO posts (user_id, content, media_path, media_type)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(q, (user_id, content if content else None, media_path, media_type))
        post_id = cursor.lastrowid
        
        # Process tags
        if tags_input:
            # Parse tags (comma-separated, remove # if present, trim whitespace)
            tag_names = [tag.strip().lstrip('#') for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tag_names:
                if tag_name and len(tag_name) <= 100:  # Validate tag length
                    # Get or create tag
                    q = "SELECT id FROM tags WHERE name = %s"
                    cursor.execute(q, (tag_name.lower(),))
                    tag = cursor.fetchone()
                    
                    if not tag:
                        q = "INSERT INTO tags (name) VALUES (%s)"
                        cursor.execute(q, (tag_name.lower(),))
                        tag_id = cursor.lastrowid
                    else:
                        tag_id = tag["id"]
                    
                    # Link tag to post
                    q = "INSERT IGNORE INTO post_tags (post_id, tag_id) VALUES (%s, %s)"
                    cursor.execute(q, (post_id, tag_id))
        
        db.commit()
        
        return json_response({"success": True, "message": "Post created"}) if is_ajax() else redirect(url_for("home"))
    except Exception as ex:
        ic(ex)
        return json_response({"error": "Failed to create post"}, 500) if is_ajax() else redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/like/<int:post_id>", methods=["POST"])
def toggle_like(post_id):
    user_id = get_user_id()
    if not user_id:
        return json_response({"error": "Not authenticated"}, 401) if is_ajax() else redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        q = "SELECT id FROM likes WHERE user_id = %s AND post_id = %s"
        cursor.execute(q, (user_id, post_id))
        existing_like = cursor.fetchone()
        
        if existing_like:
            q = "DELETE FROM likes WHERE user_id = %s AND post_id = %s"
            cursor.execute(q, (user_id, post_id))
            q = "UPDATE posts SET total_likes = total_likes - 1 WHERE id = %s"
            cursor.execute(q, (post_id,))
            liked = False
        else:
            q = "INSERT INTO likes (user_id, post_id) VALUES (%s, %s)"
            cursor.execute(q, (user_id, post_id))
            q = "UPDATE posts SET total_likes = total_likes + 1 WHERE id = %s"
            cursor.execute(q, (post_id,))
            liked = True
        
        q = "SELECT total_likes FROM posts WHERE id = %s"
        cursor.execute(q, (post_id,))
        total_likes = cursor.fetchone()["total_likes"]
        db.commit()
        
        return json_response({"liked": liked, "total_likes": total_likes}) if is_ajax() else redirect(url_for("home"))
    except Exception as ex:
        ic(ex)
        return json_response({"error": "Failed to toggle like"}, 500) if is_ajax() else redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    user_id = get_user_id()
    if not user_id:
        return json_response({"error": "Not authenticated"}, 401) if is_ajax() else redirect(url_for("login"))
    
    try:
        content = request.form.get("content", "").strip()
        if not content:
            return json_response({"error": "Comment cannot be empty"}, 400) if is_ajax() else redirect(url_for("home"))
        if len(content) > 500:
            return json_response({"error": "Comment too long (max 500 characters)"}, 400) if is_ajax() else redirect(url_for("home"))
        
        db, cursor = x.db()
        q = "INSERT INTO comments (user_id, post_id, content) VALUES (%s, %s, %s)"
        cursor.execute(q, (user_id, post_id, content))
        comment_id = cursor.lastrowid
        
        # Fetch the newly created comment with user info for AJAX response
        if is_ajax():
            q = """
                SELECT c.id, c.content, c.created_at, u.name as user_name, u.avatar as user_avatar
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.id = %s
            """
            cursor.execute(q, (comment_id,))
            comment = cursor.fetchone()
        
        db.commit()
        
        if is_ajax():
            return json_response({
                "success": True, 
                "message": "Comment added",
                "comment": {
                    "id": comment["id"],
                    "content": comment["content"],
                    "created_at": comment["created_at"].strftime('%b %d') if comment["created_at"] else '',
                    "user_name": comment["user_name"],
                    "user_avatar": comment["user_avatar"] or None
                }
            })
        else:
            return redirect(url_for("home"))
    except Exception as ex:
        ic(ex)
        return json_response({"error": "Failed to add comment"}, 500) if is_ajax() else redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/post/<int:post_id>/edit", methods=["POST"])
def edit_post(post_id):
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        q = "SELECT id, content, media_path, media_type, user_id FROM posts WHERE id = %s"
        cursor.execute(q, (post_id,))
        post = cursor.fetchone()
        
        if not post or post["user_id"] != user_id:
            return redirect(url_for("home"))
        
        content = request.form.get("content", "").strip()
        if content and len(content) > 500:
            content = content[:500]
        
        tags_input = request.form.get("tags", "").strip()
        
        media_path = post["media_path"]
        media_type = post["media_type"]
        audio_file = request.files.get("audio_file")
        
        if audio_file and audio_file.filename:
            allowed_extensions = {'mp3', 'wav', 'ogg', 'm4a', 'aac'}
            file_ext = audio_file.filename.rsplit('.', 1)[1].lower() if '.' in audio_file.filename else ''
            if file_ext not in allowed_extensions:
                return redirect(url_for("home"))
            
            if media_path:
                old_file_path = os.path.join("static", "uploads", media_path)
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
            
            filename = f"{user_id}_{uuid.uuid4().hex}_{audio_file.filename}"
            upload_path = os.path.join("static", "uploads", filename)
            os.makedirs(os.path.dirname(upload_path), exist_ok=True)
            audio_file.save(upload_path)
            media_path = filename
            media_type = "audio"
        
        q = """
            UPDATE posts 
            SET content = %s, media_path = %s, media_type = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """
        cursor.execute(q, (content if content else None, media_path, media_type, post_id, user_id))
        
        # Update tags
        # Remove all existing tags for this post
        q = "DELETE FROM post_tags WHERE post_id = %s"
        cursor.execute(q, (post_id,))
        
        # Add new tags
        if tags_input:
            tag_names = [tag.strip().lstrip('#') for tag in tags_input.split(',') if tag.strip()]
            for tag_name in tag_names:
                if tag_name and len(tag_name) <= 100:
                    # Get or create tag
                    q = "SELECT id FROM tags WHERE name = %s"
                    cursor.execute(q, (tag_name.lower(),))
                    tag = cursor.fetchone()
                    
                    if not tag:
                        q = "INSERT INTO tags (name) VALUES (%s)"
                        cursor.execute(q, (tag_name.lower(),))
                        tag_id = cursor.lastrowid
                    else:
                        tag_id = tag["id"]
                    
                    # Link tag to post
                    q = "INSERT IGNORE INTO post_tags (post_id, tag_id) VALUES (%s, %s)"
                    cursor.execute(q, (post_id, tag_id))
        
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Failed to update post", 400)
        
        return redirect(url_for("home"))
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/post/<int:post_id>/delete", methods=["POST"])
def delete_post(post_id):
    user_id = get_user_id()
    if not user_id:
        return json_response({"error": "Not authenticated"}, 401) if is_ajax() else redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        q = "SELECT id, media_path, user_id FROM posts WHERE id = %s"
        cursor.execute(q, (post_id,))
        post = cursor.fetchone()
        
        if not post:
            return json_response({"error": "Post not found"}, 404) if is_ajax() else redirect(url_for("home"))
        if post["user_id"] != user_id:
            return json_response({"error": "Unauthorized"}, 403) if is_ajax() else redirect(url_for("home"))
        
        if post["media_path"]:
            file_path = os.path.join("static", "uploads", post["media_path"])
            if os.path.exists(file_path):
                os.remove(file_path)
        
        q = "DELETE FROM posts WHERE id = %s AND user_id = %s"
        cursor.execute(q, (post_id, user_id))
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Failed to delete post", 400)
        
        return json_response({"success": True, "message": "Post deleted"}) if is_ajax() else redirect(url_for("home"))
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        return json_response({"error": "Failed to delete post"}, 500) if is_ajax() else redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/search")
def search():
    user = get_user()
    if not user: return redirect(url_for("login"))
    
    query = request.args.get("q", "").strip()
    if not query: return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        user_id = user["id"]
        search_pattern = f"%{query}%"
        
        # Get users, excluding those blocked by or blocking the current user
        q = """
            SELECT u.id, u.name, u.email, u.avatar 
            FROM users u
            WHERE (u.name LIKE %s OR u.email LIKE %s) 
            AND u.is_blocked = FALSE
            AND u.id NOT IN (
                SELECT blocked_id FROM user_blocks WHERE blocker_id = %s
                UNION
                SELECT blocker_id FROM user_blocks WHERE blocked_id = %s
            )
            LIMIT 10
        """
        cursor.execute(q, (search_pattern, search_pattern, user_id, user_id))
        users = cursor.fetchall()
        
        for user_item in users:
            if user_item["id"] != user_id:
                q = "SELECT id FROM follows WHERE follower_id = %s AND following_id = %s"
                cursor.execute(q, (user_id, user_item["id"]))
                user_item["is_following"] = cursor.fetchone() is not None
        
        # Search posts by content OR tags
        q = """
            SELECT DISTINCT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at, 
                   u.name as user_name, u.avatar as user_avatar, u.id as user_id
            FROM posts p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN post_tags pt ON p.id = pt.post_id
            LEFT JOIN tags t ON pt.tag_id = t.id
            WHERE (p.content LIKE %s OR t.name LIKE %s)
            AND p.is_blocked = FALSE 
            AND u.is_blocked = FALSE
            AND u.id NOT IN (
                SELECT blocked_id FROM user_blocks WHERE blocker_id = %s
                UNION
                SELECT blocker_id FROM user_blocks WHERE blocked_id = %s
            )
            ORDER BY p.created_at DESC
            LIMIT 20
        """
        cursor.execute(q, (search_pattern, search_pattern, user_id, user_id))
        posts = cursor.fetchall()
        
        q = """
            SELECT s.id, s.title, s.description, s.file_path, s.total_likes, s.created_at,
                   u.name as user_name, u.avatar as user_avatar, u.id as user_id
            FROM songs s
            JOIN users u ON s.user_id = u.id
            WHERE (s.title LIKE %s OR s.description LIKE %s)
            AND u.is_blocked = FALSE
            AND u.id NOT IN (
                SELECT blocked_id FROM user_blocks WHERE blocker_id = %s
                UNION
                SELECT blocker_id FROM user_blocks WHERE blocked_id = %s
            )
            ORDER BY s.created_at DESC
            LIMIT 20
        """
        cursor.execute(q, (search_pattern, search_pattern, user_id, user_id))
        songs = cursor.fetchall()
        
        # Search tags
        q = """
            SELECT DISTINCT t.id, t.name, COUNT(pt.post_id) as post_count
            FROM tags t
            LEFT JOIN post_tags pt ON t.id = pt.tag_id
            LEFT JOIN posts p ON pt.post_id = p.id
            WHERE t.name LIKE %s
            AND (p.id IS NULL OR p.is_blocked = FALSE)
            GROUP BY t.id, t.name
            ORDER BY post_count DESC
            LIMIT 10
        """
        cursor.execute(q, (search_pattern,))
        tags = cursor.fetchall()
        
        # Return JSON if AJAX request, otherwise render template
        if is_ajax():
            return json_response({
                "success": True,
                "query": query,
                "users": users,
                "posts": posts,
                "songs": songs,
                "tags": tags,
                "current_user_id": user_id
            })
        
        return render_template("search.html", query=query, users=users, posts=posts, songs=songs, tags=tags, current_user_id=user_id)
    except Exception as ex:
        ic(ex)
        if is_ajax():
            return json_response({"error": "Search failed"}, 500)
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/follow/<int:user_id>", methods=["POST"])
def toggle_follow(user_id):
    follower_id = get_user_id()
    if not follower_id: return redirect(url_for("login"))
    if user_id == follower_id: return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        
        # Check if either user is blocked
        q = "SELECT id FROM user_blocks WHERE (blocker_id = %s AND blocked_id = %s) OR (blocker_id = %s AND blocked_id = %s)"
        cursor.execute(q, (user_id, follower_id, follower_id, user_id))
        if cursor.fetchone():
            return redirect(request.referrer or url_for("home"))
        
        q = "SELECT id FROM follows WHERE follower_id = %s AND following_id = %s"
        cursor.execute(q, (follower_id, user_id))
        existing_follow = cursor.fetchone()
        
        if existing_follow:
            q = "DELETE FROM follows WHERE follower_id = %s AND following_id = %s"
            cursor.execute(q, (follower_id, user_id))
        else:
            q = "INSERT INTO follows (follower_id, following_id) VALUES (%s, %s)"
            cursor.execute(q, (follower_id, user_id))
        
        db.commit()
        return redirect(request.referrer or url_for("home"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/explore")
def explore():
    """Explore page - browse posts by tags"""
    user = get_user()
    if not user: return redirect(url_for("login"))
    
    # Handle language parameter from query string
    lan = request.args.get('lan', 'english')
    if lan not in x.allowed_languages: lan = "english"
    x.default_language = lan
    
    tag_name = request.args.get("tag_name", "").strip().lower()
    
    try:
        db, cursor = x.db()
        user_id = user["id"]
        
        if tag_name:
            # Show posts with specific tag
            q = """
                SELECT DISTINCT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at,
                       u.id as user_id, u.name as user_name, u.avatar as user_avatar, p.user_id as post_owner_id,
                       (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = %s) as user_liked,
                       (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comment_count,
                       GROUP_CONCAT(DISTINCT t2.name ORDER BY t2.name SEPARATOR ', ') as tags
                FROM posts p
                JOIN users u ON p.user_id = u.id
                JOIN post_tags pt ON p.id = pt.post_id
                JOIN tags t ON pt.tag_id = t.id
                LEFT JOIN post_tags pt2 ON p.id = pt2.post_id
                LEFT JOIN tags t2 ON pt2.tag_id = t2.id
                WHERE t.name = %s
                AND p.is_blocked = FALSE 
                AND u.is_blocked = FALSE
                AND u.id NOT IN (
                    SELECT blocked_id FROM user_blocks WHERE blocker_id = %s
                    UNION
                    SELECT blocker_id FROM user_blocks WHERE blocked_id = %s
                )
                GROUP BY p.id
                ORDER BY p.created_at DESC
                LIMIT 50
            """
            cursor.execute(q, (user_id, tag_name, user_id, user_id))
            posts = cursor.fetchall()
            
            for post in posts:
                q = """
                    SELECT c.id, c.content, c.created_at, u.name as user_name, u.avatar as user_avatar
                    FROM comments c
                    JOIN users u ON c.user_id = u.id
                    WHERE c.post_id = %s
                    ORDER BY c.created_at ASC
                """
                cursor.execute(q, (post["id"],))
                post["comments"] = cursor.fetchall()
        else:
            posts = []
        
        # Get all popular tags
        q = """
            SELECT t.name, COUNT(pt.post_id) as post_count
            FROM tags t
            JOIN post_tags pt ON t.id = pt.tag_id
            JOIN posts p ON pt.post_id = p.id
            WHERE p.is_blocked = FALSE
            GROUP BY t.id, t.name
            ORDER BY post_count DESC
            LIMIT 50
        """
        cursor.execute(q)
        all_tags = cursor.fetchall()
        
        return render_template("explore.html", posts=posts, tag_name=tag_name, all_tags=all_tags, user_id=user_id, lan=lan)
    except Exception as ex:
        ic(ex)
        return render_template("explore.html", posts=[], tag_name=tag_name, all_tags=[], user_id=user_id, error="Error loading explore page", lan=lan if 'lan' in locals() else "english"), 500
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/block/<int:user_id>", methods=["POST"])
def toggle_user_block(user_id):
    """Block or unblock a user (user-to-user blocking)."""
    blocker_id = get_user_id()
    if not blocker_id: return redirect(url_for("login"))
    if user_id == blocker_id: return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        
        # Check if already blocked
        q = "SELECT id FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s"
        cursor.execute(q, (blocker_id, user_id))
        existing_block = cursor.fetchone()
        
        if existing_block:
            # Unblock
            q = "DELETE FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s"
            cursor.execute(q, (blocker_id, user_id))
            # Also remove follow relationship if exists
            q = "DELETE FROM follows WHERE (follower_id = %s AND following_id = %s) OR (follower_id = %s AND following_id = %s)"
            cursor.execute(q, (blocker_id, user_id, user_id, blocker_id))
        else:
            # Block
            q = "INSERT INTO user_blocks (blocker_id, blocked_id) VALUES (%s, %s)"
            cursor.execute(q, (blocker_id, user_id))
            # Also remove follow relationship if exists
            q = "DELETE FROM follows WHERE (follower_id = %s AND following_id = %s) OR (follower_id = %s AND following_id = %s)"
            cursor.execute(q, (blocker_id, user_id, user_id, blocker_id))
        
        db.commit()
        return redirect(request.referrer or url_for("home"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")
    
    try:
        email = request.form.get("email", "").strip().lower()
        if not re.match(x.REGEX_EMAIL, email):
            return render_template("forgot_password.html", error="Please enter a valid email address.", email=email), 400
        
        db, cursor = x.db()
        q = "SELECT id, name FROM users WHERE email = %s"
        cursor.execute(q, (email,))
        user = cursor.fetchone()
        
        if not user:
            return redirect(url_for("verify_email", email=email, type="password_reset"))
        
        reset_token = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(hours=1)
        q = """
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
        """
        cursor.execute(q, (user["id"], reset_token, expires_at))
        db.commit()
        
        reset_url = request.url_root.rstrip('/') + url_for('reset_password', key=reset_token)
        email_template = render_template("_email_reset_password.html", user_name=user["name"], reset_url=reset_url)
        x.send_email(email, "Reset your EchoVerse password", email_template)
        
        return redirect(url_for("verify_email", email=email, type="password_reset"))
    except Exception as ex:
        ic(ex)
        return render_template("forgot_password.html", error="An error occurred. Please try again.", email=email if "email" in locals() else ""), 500
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    key = request.args.get("key", "") or request.form.get("key", "")
    
    if request.method == "GET":
        if not key:
            return render_template("reset_password.html", error="Invalid reset link.")
        return render_template("reset_password.html", key=key)
    
    try:
        reset_token = x.validate_uuid4_without_dashes(key)
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        
        if not re.match(x.REGEX_USER_PASSWORD, password):
            return render_template("reset_password.html", key=key, error="Invalid password. Password must be between 6 and 50 characters."), 400
        if password != password_confirm:
            return render_template("reset_password.html", key=key, error="Passwords do not match."), 400
        
        db, cursor = x.db()
        q = """
            SELECT user_id 
            FROM password_reset_tokens 
            WHERE token = %s AND expires_at > NOW()
        """
        cursor.execute(q, (reset_token,))
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid or expired reset link", 400)
        
        password_hash = generate_password_hash(password)
        q = "UPDATE users SET password_hash = %s WHERE id = %s"
        cursor.execute(q, (password_hash, token_data["user_id"]))
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Invalid reset link", 400)
        
        q = "DELETE FROM password_reset_tokens WHERE token = %s"
        cursor.execute(q, (reset_token,))
        db.commit()
        
        return render_template("reset_password.html", success=True, message="Password reset successfully! You can now log in.")
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        message = ex.args[0] if len(ex.args) >= 2 and ex.args[1] == 400 else "An error occurred during password reset."
        return render_template("reset_password.html", key=key if "key" in locals() else "", error=message), 400
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile")
@app.route("/profile/<int:profile_user_id>")
@x.no_cache
def profile(profile_user_id=None):
    current_user = get_user()
    if not current_user: return redirect(url_for("login"))
    
    # Handle language parameter from query string
    lan = request.args.get('lan', 'english')
    if lan not in x.allowed_languages: lan = "english"
    x.default_language = lan
    
    try:
        db, cursor = x.db()
        current_user_id = current_user["id"]
        
        # If no profile_user_id specified, show current user's profile
        if profile_user_id is None:
            profile_user_id = current_user_id
            is_own_profile = True
        else:
            is_own_profile = (profile_user_id == current_user_id)
        
        # Check if profile user exists and is not blocked by admin
        q = "SELECT id, name, email, avatar, bio, created_at, is_blocked FROM users WHERE id = %s"
        cursor.execute(q, (profile_user_id,))
        user_data = cursor.fetchone()
        
        if not user_data:
            return redirect(url_for("home"))
        
        if user_data.get("is_blocked") and not is_admin():
            return redirect(url_for("home"))
        
        # Check if current user is blocked by profile user or vice versa
        if not is_own_profile:
            q = "SELECT id FROM user_blocks WHERE (blocker_id = %s AND blocked_id = %s) OR (blocker_id = %s AND blocked_id = %s)"
            cursor.execute(q, (profile_user_id, current_user_id, current_user_id, profile_user_id))
            block_exists = cursor.fetchone()
            if block_exists:
                return redirect(url_for("home"))
        
        # Get follow status (if viewing another user's profile)
        is_following = False
        is_blocked_by_viewer = False
        if not is_own_profile:
            q = "SELECT id FROM follows WHERE follower_id = %s AND following_id = %s"
            cursor.execute(q, (current_user_id, profile_user_id))
            is_following = cursor.fetchone() is not None
            
            q = "SELECT id FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s"
            cursor.execute(q, (current_user_id, profile_user_id))
            is_blocked_by_viewer = cursor.fetchone() is not None
        
        q = "SELECT COUNT(*) as post_count FROM posts WHERE user_id = %s AND is_blocked = FALSE"
        cursor.execute(q, (profile_user_id,))
        post_count = cursor.fetchone()["post_count"]
        
        q = "SELECT COUNT(*) as following_count FROM follows WHERE follower_id = %s"
        cursor.execute(q, (profile_user_id,))
        following = cursor.fetchone()["following_count"]
        
        q = "SELECT COUNT(*) as followers_count FROM follows WHERE following_id = %s"
        cursor.execute(q, (profile_user_id,))
        followers = cursor.fetchone()["followers_count"]
        
        q = """
            SELECT p.id, p.content, p.media_path, p.media_type, p.total_likes, p.created_at,
                   (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND user_id = %s) as user_liked,
                   (SELECT COUNT(*) FROM comments WHERE post_id = p.id) as comment_count
            FROM posts p
            WHERE p.user_id = %s AND p.is_blocked = FALSE
            ORDER BY p.created_at DESC
            LIMIT 50
        """
        cursor.execute(q, (current_user_id, profile_user_id))
        posts = cursor.fetchall()
        
        for post in posts:
            q = """
                SELECT c.id, c.content, c.created_at, u.name as user_name, u.avatar as user_avatar
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.post_id = %s
                ORDER BY c.created_at ASC
            """
            cursor.execute(q, (post["id"],))
            post["comments"] = cursor.fetchall()
        
        return render_template("profile.html", 
                             user=user_data, 
                             post_count=post_count, 
                             following=following, 
                             followers=followers, 
                             posts=posts,
                             is_own_profile=is_own_profile,
                             is_following=is_following,
                             is_blocked_by_viewer=is_blocked_by_viewer,
                             current_user_id=current_user_id,
                             lan=lan)
    except Exception as ex:
        ic(ex)
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/update-name", methods=["POST"])
def update_name():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        new_name = request.form.get("name", "").strip()
        if not new_name or len(new_name) < 2 or len(new_name) > 100:
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        q = "UPDATE users SET name = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (new_name, user_id))
        db.commit()
        
        session["user_name"] = new_name
        user = get_user()
        if user:
            user["name"] = new_name
            session["user"] = user
        
        return redirect(url_for("profile"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("profile"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/update-email", methods=["POST"])
def update_email():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        new_email = request.form.get("email", "").strip().lower()
        if not re.match(x.REGEX_EMAIL, new_email):
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        
        # Check if email already exists (using parameterized query)
        q = "SELECT id FROM users WHERE email = %s AND id != %s"
        cursor.execute(q, (new_email, user_id))
        if cursor.fetchone():
            return redirect(url_for("profile"))
        
        verification_token = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(hours=24)
        q = """
            INSERT INTO email_verification_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
        """
        cursor.execute(q, (user_id, verification_token, expires_at))
        db.commit()
        
        verification_url = request.url_root.rstrip('/') + url_for('verify_email_change', key=verification_token, email=new_email)
        email_template = render_template("_email_verify_email_change.html", user_name=session["user_name"], new_email=new_email, verification_url=verification_url)
        x.send_email(new_email, "Verify your new email address", email_template)
        
        return redirect(url_for("verify_email", email=new_email, type="email_change"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("profile"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/update-avatar", methods=["POST"])
def update_avatar():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        avatar_file = request.files.get("avatar_file")
        if not avatar_file or not avatar_file.filename:
            return redirect(url_for("profile"))
        
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file_ext = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else ''
        if file_ext not in allowed_extensions:
            return redirect(url_for("profile"))
        
        db, cursor = x.db()
        filename = f"avatar_{user_id}_{uuid.uuid4().hex}.{file_ext}"
        upload_path = os.path.join("static", "uploads", "avatars", filename)
        os.makedirs(os.path.dirname(upload_path), exist_ok=True)
        avatar_file.save(upload_path)
        
        avatar_path = f"uploads/avatars/{filename}"
        q = "UPDATE users SET avatar = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (avatar_path, user_id))
        db.commit()
        
        return redirect(url_for("profile"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("profile"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/update-bio", methods=["POST"])
def update_bio():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        bio = request.form.get("bio", "").strip()
        if len(bio) > 500:
            bio = bio[:500]
        
        db, cursor = x.db()
        q = "UPDATE users SET bio = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (bio if bio else None, user_id))
        db.commit()
        
        return redirect(url_for("profile"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("profile"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/change-password", methods=["POST"])
def change_password():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    try:
        db, cursor = x.db()
        q = "SELECT email, name FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user_data = cursor.fetchone()
        
        change_token = uuid.uuid4().hex
        expires_at = datetime.now() + timedelta(hours=1)
        q = """
            INSERT INTO password_reset_tokens (user_id, token, expires_at)
            VALUES (%s, %s, %s)
        """
        cursor.execute(q, (user_id, change_token, expires_at))
        db.commit()
        
        change_url = request.url_root.rstrip('/') + url_for('reset_password', key=change_token)
        email_template = render_template("_email_reset_password.html", user_name=user_data["name"], reset_url=change_url)
        x.send_email(user_data["email"], "Change your EchoVerse password", email_template)
        
        return redirect(url_for("verify_email", email=user_data["email"], type="password_change"))
    except Exception as ex:
        ic(ex)
        return redirect(url_for("profile"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/verify-email-change", methods=["GET"])
def verify_email_change():
    try:
        key = request.args.get("key", "")
        new_email = request.args.get("email", "")
        if not key or not new_email:
            return render_template("verify_email.html", success=False, message="Invalid verification link.")
        
        reset_token = x.validate_uuid4_without_dashes(key)
        db, cursor = x.db()
        
        q = """
            SELECT user_id 
            FROM email_verification_tokens 
            WHERE token = %s AND expires_at > NOW()
        """
        cursor.execute(q, (reset_token,))
        token_data = cursor.fetchone()
        
        if not token_data:
            raise Exception("Invalid or expired verification link", 400)
        
        user_id = token_data["user_id"]
        q = "SELECT id FROM users WHERE email = %s AND id != %s"
        cursor.execute(q, (new_email, user_id))
        if cursor.fetchone():
            raise Exception("Email already in use", 400)
        
        q = "UPDATE users SET email = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (new_email, user_id))
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Invalid verification link", 400)
        
        q = "DELETE FROM email_verification_tokens WHERE token = %s"
        cursor.execute(q, (reset_token,))
        db.commit()
        
        return render_template("verify_email.html", success=True, message="Your email has been updated successfully!")
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        message = ex.args[0] if len(ex.args) >= 2 and ex.args[1] == 400 else "An error occurred during email verification."
        return render_template("verify_email.html", success=False, message=message), 400
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/profile/delete-account", methods=["GET", "POST"])
def delete_account():
    user_id = get_user_id()
    if not user_id: return redirect(url_for("login"))
    
    if request.method == "GET":
        return render_template("delete_account.html")
    
    try:
        db, cursor = x.db()
        q = "SELECT id, media_path FROM posts WHERE user_id = %s"
        cursor.execute(q, (user_id,))
        posts = cursor.fetchall()
        
        for post in posts:
            if post["media_path"]:
                file_path = os.path.join("static", "uploads", post["media_path"])
                if os.path.exists(file_path):
                    os.remove(file_path)
        
        q = "SELECT avatar FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user_data = cursor.fetchone()
        if user_data and user_data["avatar"] and not user_data["avatar"].startswith("http"):
            avatar_path = os.path.join("static", user_data["avatar"])
            if os.path.exists(avatar_path):
                os.remove(avatar_path)
        
        q = "DELETE FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        db.commit()
        if cursor.rowcount != 1:
            raise Exception("Failed to delete account", 400)
        
        session.clear()
        return redirect(url_for("landing_page"))
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        return render_template("delete_account.html", error="An error occurred while deleting your account."), 500
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/admin")
def admin_panel():
    """Admin panel to view all users and manage them."""
    if not is_admin():
        return redirect(url_for("home"))
    
    try:
        db, cursor = x.db()
        q = """
            SELECT id, name, email, role, is_verified, is_blocked, created_at
            FROM users
            ORDER BY created_at DESC
        """
        cursor.execute(q)
        users = cursor.fetchall()
        
        q = """
            SELECT p.id, p.content, p.is_blocked, p.created_at,
                   u.id as user_id, u.name as user_name, u.email as user_email
            FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 100
        """
        cursor.execute(q)
        posts = cursor.fetchall()
        
        return render_template("admin.html", users=users, posts=posts)
    except Exception as ex:
        ic(ex)
        return redirect(url_for("home"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/admin/user/<int:user_id>/toggle-block", methods=["POST"])
def toggle_block_user(user_id):
    """Block or unblock a user and send email notification."""
    if not is_admin():
        return json_response({"error": "Unauthorized"}, 403) if is_ajax() else redirect(url_for("home"))
    
    try:
        admin_id = get_user_id()
        db, cursor = x.db()
        
        # Get user info
        q = "SELECT id, name, email, is_blocked FROM users WHERE id = %s"
        cursor.execute(q, (user_id,))
        user = cursor.fetchone()
        
        if not user:
            return json_response({"error": "User not found"}, 404) if is_ajax() else redirect(url_for("admin_panel"))
        
        # Toggle block status
        new_blocked_status = not user["is_blocked"]
        q = "UPDATE users SET is_blocked = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (new_blocked_status, user_id))
        db.commit()
        
        # Log admin action
        action = "block_user" if new_blocked_status else "unblock_user"
        q = """
            INSERT INTO admin_logs (admin_id, action, target_user_id)
            VALUES (%s, %s, %s)
        """
        cursor.execute(q, (admin_id, action, user_id))
        db.commit()
        
        # Send email notification
        if new_blocked_status:
            subject = "Your EchoVerse account has been blocked"
            email_template = render_template(
                "_email_user_blocked.html",
                user_name=user["name"],
                action="blocked"
            )
        else:
            subject = "Your EchoVerse account has been unblocked"
            email_template = render_template(
                "_email_user_blocked.html",
                user_name=user["name"],
                action="unblocked"
            )
        
        try:
            x.send_email(user["email"], subject, email_template)
        except Exception as email_ex:
            ic(f"Failed to send email: {email_ex}")
        
        return json_response({
            "success": True,
            "is_blocked": new_blocked_status,
            "message": f"User {'blocked' if new_blocked_status else 'unblocked'} successfully"
        }) if is_ajax() else redirect(url_for("admin_panel"))
        
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        return json_response({"error": "Failed to update user"}, 500) if is_ajax() else redirect(url_for("admin_panel"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/admin/post/<int:post_id>/toggle-block", methods=["POST"])
def toggle_block_post(post_id):
    """Block or unblock a post and send email notification to post owner."""
    if not is_admin():
        return json_response({"error": "Unauthorized"}, 403) if is_ajax() else redirect(url_for("home"))
    
    try:
        admin_id = get_user_id()
        db, cursor = x.db()
        
        # Get post info with user details
        q = """
            SELECT p.id, p.content, p.is_blocked, p.user_id,
                   u.name as user_name, u.email as user_email
            FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.id = %s
        """
        cursor.execute(q, (post_id,))
        post = cursor.fetchone()
        
        if not post:
            return json_response({"error": "Post not found"}, 404) if is_ajax() else redirect(url_for("admin_panel"))
        
        # Toggle block status
        new_blocked_status = not post["is_blocked"]
        q = "UPDATE posts SET is_blocked = %s, updated_at = NOW() WHERE id = %s"
        cursor.execute(q, (new_blocked_status, post_id))
        db.commit()
        
        # Log admin action
        action = "block_post" if new_blocked_status else "unblock_post"
        q = """
            INSERT INTO admin_logs (admin_id, action, target_post_id)
            VALUES (%s, %s, %s)
        """
        cursor.execute(q, (admin_id, action, post_id))
        db.commit()
        
        # Send email notification to post owner
        if new_blocked_status:
            subject = "Your EchoVerse post has been blocked"
            email_template = render_template(
                "_email_post_blocked.html",
                user_name=post["user_name"],
                post_content=post["content"][:100] if post["content"] else "your post",
                action="blocked"
            )
        else:
            subject = "Your EchoVerse post has been unblocked"
            email_template = render_template(
                "_email_post_blocked.html",
                user_name=post["user_name"],
                post_content=post["content"][:100] if post["content"] else "your post",
                action="unblocked"
            )
        
        try:
            x.send_email(post["user_email"], subject, email_template)
        except Exception as email_ex:
            ic(f"Failed to send email: {email_ex}")
        
        return json_response({
            "success": True,
            "is_blocked": new_blocked_status,
            "message": f"Post {'blocked' if new_blocked_status else 'unblocked'} successfully"
        }) if is_ajax() else redirect(url_for("admin_panel"))
        
    except Exception as ex:
        ic(ex)
        if "db" in locals(): db.rollback()
        return json_response({"error": "Failed to update post"}, 500) if is_ajax() else redirect(url_for("admin_panel"))
    finally:
        cleanup_db(cursor if "cursor" in locals() else None, db if "db" in locals() else None)


@app.route("/admin/languages", methods=["GET"])
def get_languages_from_sheet():
    """Get languages from Google Sheets and return as JSON."""
    if not is_admin():
        return json_response({"error": "Unauthorized"}, 403)
    
    try:
        if not x.google_spread_sheet_key:
            return json_response({"error": "Google Spreadsheet key not configured"}, 400)
        
        # Fetch data from Google Sheets
        url = f"https://docs.google.com/spreadsheets/d/{x.google_spread_sheet_key}/export?format=csv&id={x.google_spread_sheet_key}"
        res = requests.get(url=url)
        res.raise_for_status()
        csv_text = res.content.decode('utf-8-sig')  # Handle BOM if present
        csv_file = io.StringIO(csv_text)
        
        # Parse CSV data - handle case-insensitive column names
        data = {}
        reader = csv.DictReader(csv_file)
        
        # Get the actual column names from the reader (case-insensitive matching)
        fieldnames = [f.lower() for f in reader.fieldnames] if reader.fieldnames else []
        
        for row in reader:
            # Normalize column names to lowercase for matching
            row_lower = {k.lower(): v for k, v in row.items()}
            
            key = row_lower.get('key', '').strip()
            if not key:  # Skip rows without a key
                continue
            
            item = {
                'english': row_lower.get('english', '').strip(),
                'danish': row_lower.get('danish', '').strip(),
                'spanish': row_lower.get('spanish', '').strip()
            }
            data[key] = item
        
        return json_response({
            "success": True,
            "languages": data,
            "available_languages": x.allowed_languages
        })
        
    except Exception as ex:
        ic(ex)
        return json_response({"error": str(ex)}, 500)


@app.route("/admin/languages/dictionary", methods=["GET"])
def get_dictionary_json():
    """Get all keys from dictionary.json in a format suitable for Google Sheets."""
    if not is_admin():
        return json_response({"error": "Unauthorized"}, 403)
    
    try:
        # Load dictionary.json
        with open("dictionary.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Convert to array format for easy table display
        table_data = []
        for key, translations in data.items():
            table_data.append({
                'key': key,
                'english': translations.get('english', ''),
                'danish': translations.get('danish', ''),
                'spanish': translations.get('spanish', '')
            })
        
        # Sort by key for easier reading
        table_data.sort(key=lambda x: x['key'])
        
        return json_response({
            "success": True,
            "data": table_data,
            "total_keys": len(table_data)
        })
        
    except FileNotFoundError:
        return json_response({"error": "dictionary.json not found"}, 404)
    except json.JSONDecodeError:
        return json_response({"error": "dictionary.json is invalid"}, 500)
    except Exception as ex:
        ic(ex)
        return json_response({"error": str(ex)}, 500)


@app.route("/admin/languages/sync", methods=["POST"])
def sync_languages_from_sheet():
    """Sync languages from Google Sheets to dictionary.json file."""
    if not is_admin():
        return json_response({"error": "Unauthorized"}, 403)
    
    try:
        if not x.google_spread_sheet_key:
            return json_response({"error": "Google Spreadsheet key not configured"}, 400)
        
        # Fetch data from Google Sheets
        url = f"https://docs.google.com/spreadsheets/d/{x.google_spread_sheet_key}/export?format=csv&id={x.google_spread_sheet_key}"
        res = requests.get(url=url)
        res.raise_for_status()  # Raise an exception for bad status codes
        csv_text = res.content.decode('utf-8-sig')  # Handle BOM if present
        csv_file = io.StringIO(csv_text)
        
        # Parse CSV data - handle case-insensitive column names
        data = {}
        reader = csv.DictReader(csv_file)
        
        for row in reader:
            # Normalize column names to lowercase for matching
            row_lower = {k.lower(): v for k, v in row.items()}
            
            key = row_lower.get('key', '').strip()
            if not key:  # Skip rows without a key
                continue
                
            item = {
                'english': row_lower.get('english', '').strip(),
                'danish': row_lower.get('danish', '').strip(),
                'spanish': row_lower.get('spanish', '').strip()
            }
            data[key] = item
        
        # Validate that we have data before overwriting
        if not data or len(data) == 0:
            return json_response({
                "error": "No valid translation keys found in Google Sheets. Please add at least one row with a 'key' column before syncing."
            }, 400)
        
        # Convert the data to JSON with proper formatting
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        
        # Save data to the dictionary.json file
        with open("dictionary.json", 'w', encoding='utf-8') as f:
            f.write(json_data)
        
        return json_response({
            "success": True,
            "message": f"Successfully synced {len(data)} translation keys from Google Sheets to dictionary.json",
            "keys_synced": len(data)
        })
        
    except requests.RequestException as ex:
        ic(ex)
        return json_response({"error": f"Failed to fetch from Google Sheets: {str(ex)}"}, 500)
    except Exception as ex:
        ic(ex)
        return json_response({"error": f"Failed to sync languages: {str(ex)}"}, 500)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing_page"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)