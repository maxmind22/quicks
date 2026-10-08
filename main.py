import os
import json
import time
import secrets
from datetime import datetime, timedelta
from os.path import join
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, Response, stream_with_context
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from forms import RegisterForm, LoginForm, Files, Search
from decorators import must_login
from ai_engine import split_documents, save_embeddings, load_documents, get_answer, stream_answer, delete_user_file_embeddings, check_credentials

# Storage configuration (writable /tmp for serverless environments like Vercel)
if os.environ.get('VERCEL'):
    UPLOAD_FOLDER = '/tmp/quicks_uploads'
else:
    UPLOAD_FOLDER = './static/uploads'

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# Create uploads folder dynamically
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)

# Secret key: load from environment or use stable default for session persistence in serverless
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'quicks-session-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Usage & Demo Limits Configuration (overridable via environment variables)
MAX_DOCS_PER_USER = int(os.environ.get('MAX_DOCS_PER_USER', 5))         # Max documents stored per user
MAX_FILE_SIZE_MB = int(os.environ.get('MAX_FILE_SIZE_MB', 3))            # Max file upload size in MB (3 MB)
MAX_CHUNKS_PER_FILE = int(os.environ.get('MAX_CHUNKS_PER_FILE', 25))     # Max chunks per document (~15-20 pages)
MAX_QUERIES_PER_DAY = int(os.environ.get('MAX_QUERIES_PER_DAY', 30))     # Max daily AI searches per user
AUTO_DELETE_HOURS = int(os.environ.get('AUTO_DELETE_HOURS', 24))         # Demo mode: auto-purge files after 24 hours

app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_MB * 1024 * 1024

# Database configuration: support PostgreSQL (Neon/Supabase) via DATABASE_URL or SQLite fallback
database_url = (os.environ.get('DATABASE_URL') or '').strip()
if database_url and any(database_url.startswith(scheme) for scheme in ("postgresql://", "postgres://", "postgresql+psycopg2://", "sqlite://", "mysql://")):
    # Fix uri scheme for SQLAlchemy 2.0 + psycopg2 compatibility
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
elif os.environ.get('VERCEL'):
    # Default to /tmp SQLite on Vercel if external database is not yet configured
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/allusers.db'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///allusers.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Ensure connection resiliency on serverless platforms (Neon, Supabase, AWS RDS)
if app.config.get('SQLALCHEMY_DATABASE_URI', '').startswith("postgresql"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,       # Tests connection liveness before queries; transparently reconnects on closed SSL
        "pool_recycle": 280,        # Recycles connections under 5 minutes before database idle timeout
        "pool_size": 5,             # Safe pool size for serverless function concurrency
        "max_overflow": 10,
        "connect_args": {
            "connect_timeout": 15,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    }
else:
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_pre_ping": True,
    }

db = SQLAlchemy()
db.init_app(app)

@app.teardown_request
def teardown_request_handler(exception=None):
    """Ensures database connections and transactions are cleanly returned to the pool after each request."""
    if exception is not None:
        try:
            db.session.rollback()
        except Exception:
            pass
    try:
        db.session.remove()
    except Exception:
        pass

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

bootstrap = Bootstrap5(app)

# Database Models
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    documents = db.relationship('Document', backref='owner', lazy=True, cascade="all, delete-orphan")
    query_logs = db.relationship('QueryLog', backref='user', lazy=True, cascade="all, delete-orphan")

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class QueryLog(db.Model):
    __tablename__ = "query_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

def get_user_daily_query_count(user_id):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        return QueryLog.query.filter(
            QueryLog.user_id == user_id,
            QueryLog.created_at >= today_start
        ).count()
    except Exception:
        return 0

_last_purge_timestamp = 0

def purge_expired_documents(max_age_hours=None, force=False):
    """
    Deletes documents older than max_age_hours from PostgreSQL, Pinecone, and disk.
    For this demo application, uploaded documents and their embeddings expire after 24 hours.
    Throttled to run at most once every 5 minutes during user requests, or instantly if force=True.
    """
    global _last_purge_timestamp
    now_ts = time.time()
    if not force and (now_ts - _last_purge_timestamp < 300):
        return 0
    _last_purge_timestamp = now_ts

    if max_age_hours is None:
        max_age_hours = AUTO_DELETE_HOURS
    try:
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        expired_docs = Document.query.filter(Document.uploaded_at < cutoff).all()
        if not expired_docs:
            return 0
        
        purged = 0
        for doc in expired_docs:
            filename = doc.filename
            user_id = doc.user_id
            
            # 1. Clear vectors from Pinecone
            try:
                delete_user_file_embeddings(filename, user_id)
            except Exception as e:
                print(f"Error purging embeddings for {filename}: {e}")
                
            # 2. Clear disk file if present
            try:
                user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{user_id}")
                filepath = join(user_upload_dir, filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception:
                pass
                
            # 3. Remove from database
            db.session.delete(doc)
            purged += 1
            
        db.session.commit()
        return purged
    except Exception as e:
        db.session.rollback()
        print(f"Error during expired documents purge: {e}")
        return 0

class VercelPathMiddleware:
    """
    Normalizes WSGI PATH_INFO and SCRIPT_NAME for Vercel deployment.
    Strips framework and rewrite prefixes (/api/index.py, /api/index, /api, /index.py, /main.py).
    """
    PREFIXES = (
        '/api/index.py',
        '/api/index',
        '/api/main.py',
        '/api/main',
        '/api',
        '/index.py',
        '/index',
        '/main.py',
    )

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        environ['SCRIPT_NAME'] = ''
        path = environ.get('PATH_INFO', '')
        if not path or path == '/':
            environ['PATH_INFO'] = '/'
            return self.wsgi_app(environ, start_response)

        for prefix in self.PREFIXES:
            if path == prefix or path == prefix + '/':
                environ['PATH_INFO'] = '/'
                break
            elif path.startswith(prefix + '/'):
                stripped = path[len(prefix):]
                environ['PATH_INFO'] = stripped if stripped.startswith('/') else '/' + stripped
                break
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Database initialization info: {e}")

@app.route('/api/index.py')
@app.route('/api/index')
@app.route('/api')
@app.route('/index.py')
@app.route('/')
def home():
    return render_template("index.html")

@app.route('/favicon.ico')
def favicon():
    return ('', 204)

@app.errorhandler(404)
def handle_404(e):
    return render_template("index.html"), 404

# Register users
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_pass = generate_password_hash(
            form.password.data,
            method='scrypt'
        )
        try:
            existing_user = User.query.filter_by(email=form.email.data).first()
        except (OperationalError, SQLAlchemyError):
            db.session.rollback()
            existing_user = User.query.filter_by(email=form.email.data).first()

        if existing_user:
            flash("You've already signed up with that email. Please login.", "warning")
            return redirect(url_for("register"))
        new_user = User(
            name=form.name.data,
            email=form.email.data,
            password=hashed_pass,
        )
        try:
            db.session.add(new_user)
            db.session.commit()
        except (OperationalError, SQLAlchemyError):
            db.session.rollback()
            db.session.add(new_user)
            db.session.commit()
        flash("Successfully registered! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)

# Login users
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (OperationalError, SQLAlchemyError):
        db.session.rollback()
        return db.session.get(User, int(user_id))
    except Exception:
        return None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        try:
            user = User.query.filter_by(email=form.email.data).first()
        except (OperationalError, SQLAlchemyError):
            db.session.rollback()
            user = User.query.filter_by(email=form.email.data).first()
        if not user:
            flash("That email does not exist. Please check your credentials or register.", "warning")
            return redirect(url_for("login"))
        elif not check_password_hash(user.password, form.password.data):
            flash("Incorrect password. Please try again.", "warning")
            return redirect(url_for("login"))
        else:
            login_user(user)
            return redirect(url_for("dashboard"))
    return render_template("login.html", form=form)

# User dashboard
@app.route('/dashboard', methods=['GET', 'POST'])
@must_login
def dashboard():
    form = Search()
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")

    # Demo mode: purge any documents older than 24 hours
    purge_expired_documents()

    # Backwards compatibility: sync existing local disk files to Document table
    if os.path.exists(user_upload_dir):
        disk_files = [f for f in os.listdir(user_upload_dir) if os.path.isfile(join(user_upload_dir, f))]
        for df in disk_files:
            if not Document.query.filter_by(user_id=current_user.id, filename=df).first():
                db.session.add(Document(filename=df, user_id=current_user.id))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Query persistent document list from database
    user_docs = Document.query.filter_by(user_id=current_user.id).order_by(Document.uploaded_at.desc()).all()
    
    # Calculate time remaining before automatic 24-hour expiration for each file
    files = []
    now = datetime.utcnow()
    for doc in user_docs:
        age_seconds = (now - doc.uploaded_at).total_seconds()
        remaining_seconds = max(0, (AUTO_DELETE_HOURS * 3600) - age_seconds)
        remaining_hours = int(remaining_seconds // 3600)
        remaining_minutes = int((remaining_seconds % 3600) // 60)
        
        if remaining_hours >= 1:
            time_left_str = f"{remaining_hours}h left"
        else:
            time_left_str = f"{remaining_minutes}m left"
            
        files.append({
            "filename": doc.filename,
            "uploaded_at": doc.uploaded_at,
            "time_left": time_left_str
        })
    
    # Check if API keys are set up
    credentials_ok = check_credentials()
    if not credentials_ok:
        flash("Google Gemini or Pinecone API keys are missing. Standard searches will be disabled. Please set them in your server environment.", "danger")
        
    # Usage stats
    queries_today = get_user_daily_query_count(current_user.id)
    usage = {
        "doc_count": len(files),
        "max_docs": MAX_DOCS_PER_USER,
        "queries_today": queries_today,
        "max_queries": MAX_QUERIES_PER_DAY,
        "remaining_queries": max(0, MAX_QUERIES_PER_DAY - queries_today),
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "max_chunks": MAX_CHUNKS_PER_FILE,
        "auto_delete_hours": AUTO_DELETE_HOURS
    }
        
    return render_template("dashboard.html", form=form, files=files, credentials_ok=credentials_ok, usage=usage)

@app.route('/search', methods=['POST'])
@must_login
def search():
    query = request.form.get('query')
    if not query:
        return jsonify({"error": "Error: Empty query received."}), 400
    
    # Demo mode: purge expired documents
    purge_expired_documents()

    # Enforce daily query quota per user
    queries_today = get_user_daily_query_count(current_user.id)
    if queries_today >= MAX_QUERIES_PER_DAY:
        return jsonify({
            "error": f"Daily AI search limit reached ({queries_today}/{MAX_QUERIES_PER_DAY} questions used today). Quota resets at 00:00 UTC."
        }), 429

    # Process the query using RAG scoped to current user
    result = get_answer(query, current_user.id)
    
    # Log successful query
    try:
        db.session.add(QueryLog(user_id=current_user.id))
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({
        "answer": result,
        "queries_today": queries_today + 1,
        "max_queries": MAX_QUERIES_PER_DAY,
        "remaining_queries": max(0, MAX_QUERIES_PER_DAY - (queries_today + 1))
    })

@app.route('/search/stream', methods=['POST'])
@must_login
def search_stream():
    query = request.form.get('query') or (request.json.get('query') if request.is_json else None)
    if not query:
        return jsonify({"error": "Error: Empty query received."}), 400
    
    # Periodic background cleanup check
    purge_expired_documents()

    # Enforce daily query quota per user
    queries_today = get_user_daily_query_count(current_user.id)
    if queries_today >= MAX_QUERIES_PER_DAY:
        return jsonify({
            "error": f"Daily AI search limit reached ({queries_today}/{MAX_QUERIES_PER_DAY} questions used today). Quota resets at 00:00 UTC."
        }), 429

    # Log successful query
    try:
        db.session.add(QueryLog(user_id=current_user.id))
        db.session.commit()
    except Exception:
        db.session.rollback()

    def generate():
        try:
            for token in stream_answer(query, current_user.id):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'queries_today': queries_today + 1, 'max_queries': MAX_QUERIES_PER_DAY})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache, no-transform'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route('/logout')
def logout():
    logout_user()
    flash("Successfully logged out.", "success")
    return redirect(url_for("home"))

@app.route('/api/cleanup', methods=['GET', 'POST'])
@app.route('/cleanup', methods=['GET', 'POST'])
def cleanup_endpoint():
    """Endpoint for Vercel Cron or manual pings to purge documents older than 24h."""
    purged = purge_expired_documents(force=True)
    return jsonify({
        "status": "success",
        "purged_documents": purged,
        "retention_hours": AUTO_DELETE_HOURS,
        "timestamp": datetime.utcnow().isoformat()
    })

# File upload helpers
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.errorhandler(413)
def request_entity_too_large(error):
    flash(f"File size exceeds the maximum allowed limit of {MAX_FILE_SIZE_MB} MB. Please upload a smaller document.", "danger")
    return redirect(url_for('upload'))

@app.route('/upload', methods=['GET', 'POST'])
@must_login
def upload():
    form = Files()
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")
    
    # Demo mode: purge expired documents before checking user quota
    purge_expired_documents()
    doc_count = Document.query.filter_by(user_id=current_user.id).count()
    
    if request.method == 'POST':
        # Enforce maximum document count limit
        if doc_count >= MAX_DOCS_PER_USER:
            flash(
                f"Document limit reached! You already have {doc_count}/{MAX_DOCS_PER_USER} documents. "
                "Please delete an existing document from your dashboard before uploading a new one.",
                "warning"
            )
            return redirect(url_for('dashboard'))

        if 'file' not in request.files:
            flash('No file selected.', 'warning')
            return redirect(request.url)
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected.', 'warning')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Enforce file size limit
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                flash(f"File size ({file_size / (1024*1024):.1f} MB) exceeds maximum allowed limit of {MAX_FILE_SIZE_MB} MB. Please upload a smaller document.", "danger")
                return redirect(request.url)
            
            os.makedirs(user_upload_dir, exist_ok=True)
            filepath = join(user_upload_dir, filename)
            file.save(filepath)

            # Process and save embeddings into Pinecone
            try:
                raw_docs = load_documents(user_upload_dir, filename)
                split_docs = split_documents(raw_docs, chunk_size=1000, chunk_overlap=20)
                
                # Enforce max chunks limit to prevent 429 rate limit exhaustion
                if len(split_docs) > MAX_CHUNKS_PER_FILE:
                    flash(
                        f"Document contains {len(split_docs)} chunks, which exceeds the limit of {MAX_CHUNKS_PER_FILE} chunks (~15-20 pages). "
                        "To avoid exhausting AI token quotas, please upload a shorter document or split it into sections.",
                        "warning"
                    )
                    if os.path.exists(filepath):
                        try:
                            os.remove(filepath)
                        except OSError:
                            pass
                    return redirect(request.url)

                if save_embeddings(split_docs, current_user.id):
                    # Record persistent document tracking in database
                    if not Document.query.filter_by(user_id=current_user.id, filename=filename).first():
                        new_doc = Document(filename=filename, user_id=current_user.id)
                        db.session.add(new_doc)
                        db.session.commit()
                    flash(f"File '{filename}' uploaded and indexed successfully!", 'success')
            except Exception as e:
                flash(f"File uploaded, but failed to index: {str(e)}", 'warning')
            finally:
                # In serverless environments, remove temporary file to free up ephemeral space
                if os.environ.get('VERCEL') and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid file format. Only PDF and TXT files are supported.', 'danger')
            return redirect(request.url)
            
    return render_template(
        "upload.html", 
        form=form,
        doc_count=doc_count,
        max_docs=MAX_DOCS_PER_USER,
        max_file_size_mb=MAX_FILE_SIZE_MB,
        max_chunks=MAX_CHUNKS_PER_FILE,
        auto_delete_hours=AUTO_DELETE_HOURS
    )

@app.route('/delete-file/<filename>', methods=['POST'])
@must_login
def delete_file(filename):
    filename = secure_filename(filename)
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")
    filepath = join(user_upload_dir, filename)
    
    # Remove from disk if it exists locally
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass

    # Remove from Document database table
    doc = Document.query.filter_by(user_id=current_user.id, filename=filename).first()
    if doc:
        db.session.delete(doc)
        db.session.commit()

    # Clear vectors from Pinecone
    try:
        delete_user_file_embeddings(filename, current_user.id)
        flash(f"Successfully deleted document '{filename}' and cleared its embeddings.", "success")
    except Exception as e:
        flash(f"Document record deleted, but warning clearing vectors: {str(e)}", "warning")
        
    return redirect(url_for('dashboard'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
