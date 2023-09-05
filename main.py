from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_bootstrap import Bootstrap5
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegisterForm, LoginForm, Files, Search
from decorators import must_login
from werkzeug.utils import secure_filename
from os.path import join
from ai_engine import split_documents, save_embeddings, embeddings, load_documents, get_answer


UPLOAD_FOLDER = './static/uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc'}


app = Flask(__name__)
app.config['SECRET_KEY'] = '8BYkEfBA6O6donzWlSihBXox7C0sKR6er'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# CONNECT TO DB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///allusers.db'
db = SQLAlchemy()
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
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
    form = RegisterForm()
    if form.validate_on_submit():
        hashed_pass = generate_password_hash(
            form.password.data,
            method='pbkdf2:sha256',
            salt_length=10
        )
        new_user = User(
            name=form.name.data,
            email=form.email.data,
            password=hashed_pass,
        )
        if User.query.filter_by(email=form.email.data).first():
            flash("You've already signed up with that email, ", "warning")
            return redirect(url_for("register"))
        db.session.add(new_user)
        db.session.commit()
        flash("Successfully registered! Please login", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)

# login users


@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(
            email=form.email.data
        ).first()
        if not user:
            flash("That email does not exist, please", "warning")
            return redirect(url_for("login"))
        elif not check_password_hash(user.password, form.password.data):
            flash("Email or Password incorrect, please try again or ", "warning")
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
    return render_template("dashboard.html", form=form)


@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.form.get('query')
    result = get_answer(query)
    return jsonify(result)


@app.route('/logout')
def logout():
    logout_user()
    return render_template("index.html")

# file upload


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/upload', methods=['GET', 'POST'])
@must_login
def upload():
    form = Files()
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(join(UPLOAD_FOLDER, filename))

            # save embeddings
            files = load_documents(UPLOAD_FOLDER, filename)
            docs = split_documents(files, chunk_size=1000, chunk_overlap=20)
            if save_embeddings(docs, embeddings):
                flash(
                    'File uploaded successfully, upload another file or search your files', 'success')
            return redirect(url_for('upload'))
    return render_template("upload.html", form=form)


if __name__ == "__main__":
    app.run(debug=True)
