from flask_login import current_user
from flask import redirect, url_for, flash
from functools import wraps


def must_login(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Login required!", "warning")
            return redirect(url_for('login'))
        return func(*args, **kwargs)
    return wrapper