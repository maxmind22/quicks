import os
import secrets
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegisterForm, LoginForm, Files, Search
from decorators import must_login
from werkzeug.utils import secure_filename
from os.path import join
from ai_engine import split_documents, save_embeddings, load_documents, get_answer, delete_user_file_embeddings, check_credentials

UPLOAD_FOLDER = './static/uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf'}

# Create uploads folder dynamically
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
# Load secret key from environment or use a secure random key
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# CONNECT TO DB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///allusers.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy()
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

bootstrap = Bootstrap5(app)

# CREATE TABLE IN DB
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return render_template("index.html")

# register users
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

# login users
@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)

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

# user dashboard
@app.route('/dashboard', methods=['GET', 'POST'])
@must_login
def dashboard():
    form = Search()
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")
    files = []
    if os.path.exists(user_upload_dir):
        files = [f for f in os.listdir(user_upload_dir) if os.path.isfile(join(user_upload_dir, f))]
    
    # Check if API keys are set up
    credentials_ok = check_credentials()
    if not credentials_ok:
        flash("OpenAI or Pinecone API keys are missing. Standard searches will be disabled. Please set them in your server environment.", "danger")
        
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

# file upload
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['GET', 'POST'])
@must_login
def upload():
    form = Files()
    user_upload_dir = join(app.config['UPLOAD_FOLDER'], f"user_{current_user.id}")
    
    if request.method == 'POST':
        # check if the post request has the file part
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

            # process and save embeddings
            try:
                files = load_documents(user_upload_dir, filename)
                docs = split_documents(files, chunk_size=1000, chunk_overlap=20)
                if save_embeddings(docs, current_user.id):
                    flash(f"File '{filename}' uploaded and indexed successfully!", 'success')
            except Exception as e:
                # Still keep the file locally but inform user of vector indexing error
                flash(f"File uploaded, but failed to index: {str(e)}", 'warning')
                
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
    
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            # Remove from Pinecone
            delete_user_file_embeddings(filename, current_user.id)
            flash(f"Successfully deleted document '{filename}' and cleared its embeddings.", "success")
        except Exception as e:
            flash(f"Error during deletion: {str(e)}", "danger")
    else:
        flash("Document not found.", "warning")
        
    return redirect(url_for('dashboard'))

if __name__ == "__main__":
    app.run(debug=True)
