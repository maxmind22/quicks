from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, FileField, PasswordField
from wtforms.validators import DataRequired


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired()])
    submit = SubmitField("Submit")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Submit")


class Files(FlaskForm):
    file = FileField("chose file", validators=[DataRequired()])
    submit = SubmitField("Submit")


class Search(FlaskForm):
    search = StringField("", validators=[DataRequired()], render_kw={
                         "placeholder": "your query here"})
    submit = SubmitField("Send")
