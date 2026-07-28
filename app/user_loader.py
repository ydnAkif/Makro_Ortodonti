from app import db, login_manager
from app.models.models import User


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return None
    user = db.session.get(User, uid)
    if user and not user.is_active:
        return None
    return user
