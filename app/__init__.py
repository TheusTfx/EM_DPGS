from flask import Flask
from .database import init_db, close_db
from .routes import registrar_blueprints


def create_app():
    app = Flask(
        __name__,
        static_folder='../static',
        template_folder='../templates',
    )
    app.teardown_appcontext(close_db)

    init_db()
    registrar_blueprints(app)
    _registrar_errorhandler(app)
    return app


def _registrar_errorhandler(app):
    from flask import jsonify, request

    @app.errorhandler(Exception)
    def handle(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        if request.path.startswith('/api/'):
            return jsonify({'erro': str(e), 'tipo': type(e).__name__}), 500
        return str(e), 500
