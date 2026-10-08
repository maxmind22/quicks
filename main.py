import os
import secrets
from datetime import datetime
from os.path import join
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from forms import RegisterForm, LoginForm, Files, Search
from decorators import must_login
from ai_engine import split_documents, save_embeddings, load_documents, get_answer, delete_user_file_embeddings, check_credentials

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

app = Flask(__name__)

# Secret key: load from environment or use stable default for session persistence in serverless
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'quicks-session-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Database configuration: support PostgreSQL (Neon/Supabase) via DATABASE_URL or SQLite fallback
database_url = (os.environ.get('DATABASE_URL') or '').strip()
if database_url and any(database_url.startswith(scheme) for scheme in ("postgresql://", "postgres://", "sqlite://", "mysql://")):
    # Fix uri scheme for SQLAlchemy compatibility (postgres:// -> postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
elif os.environ.get('VERCEL'):
    # Default to /tmp SQLite on Vercel if external database is not yet configured
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/allusers.db'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///allusers.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy()
db.init_app(app)

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

class Document(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"Database initialization info: {e}")

@app.route('/')
def home():
    return render_template("index.html")

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
        if User.query.filter_by(email=form.email.data).first():
            flash("You've already signed up with that email. Please login.", "warning")
            return redirect(url_for("register"))
        new_user = User(
            name=form.name.data,
            email=form.email.data,
            password=hashed_pass,
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Successfully registered! Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)

# Login users
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
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
    files = [doc.filename for doc in user_docs]
    
    # Check if API keys are set up
    credentials_ok = check_credentials()
    if not credentials_ok:
        flash("Google Gemini or Pinecone API keys are missing. Standard searches will be disabled. Please set them in your server environment.", "danger")
        
    return render_template("dashboard.html", form=form, files=files, credentials_ok=credentials_ok)

@app.route('/search', methods=['POST'])
@must_login
def search():
    query = request.form.get('query')
    if not query:
        return jsonify("Error: Empty query received."), 400
    
    # Process the query using RAG scoped to current user
    result = get_answer(query, current_user.id)
    return jsonify(result)

@app.route('/logout')
def logout():
    logout_user()
    flash("Successfully logged out.", "success")
    return redirect(url_for("home"))

# File upload helpers
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['GET', 'POST'])
@must_login
def upload():
    form = Files()
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected.', 'warning')
            return redirect(request.url)
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected.', 'warning')
            return redirect(request.url)
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            os.makedirs(user_upload_dir, exist_ok=True)
            filepath = join(user_upload_dir, filename)
            file.save(filepath)

            # Process and save embeddings into Pinecone
            try:
                files = load_documents(user_upload_dir, filename)
                docs = split_documents(files, chunk_size=1000, chunk_overlap=20)
                if save_embeddings(docs, current_user.id):
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
            
    return render_template("upload.html", form=form)

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
