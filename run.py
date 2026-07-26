from app import create_app, db
from app.models.models import User
import os

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return dict(app=app, db=db, User=User)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode, host="127.0.0.1", port=5001)

