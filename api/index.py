import sys
import os

# Ensure the repository root directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

class VercelPathMiddleware:
    """
    Middleware that fixes Vercel's rewrite pathing.
    When Vercel rewrites routes to /api/index.py, this middleware strips the
    /api prefix so Flask matches standard routes (/, /login, /dashboard, etc.).
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        for prefix in ('/api/index.py', '/api/index', '/api'):
            if path.startswith(prefix):
                stripped = path[len(prefix):]
                environ['PATH_INFO'] = stripped if stripped.startswith('/') else ('/' + stripped if stripped else '/')
                break
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathMiddleware(app.wsgi_app)
