import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, _connection_record):
    """Enforce relational integrity and wait briefly for concurrent SQLite writes."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        # WAL lets readers (web requests) proceed while the WhatsApp/backup
        # background threads hold a write transaction, instead of blocking
        # on the default rollback-journal's single-writer-excludes-all-readers
        # behavior. No-op for :memory: databases used in tests.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate(compare_type=True, render_as_batch=True)
login_manager.login_view = "auth.login"
login_manager.login_message = "Lütfen giriş yapın."
login_manager.login_message_category = "warning"
