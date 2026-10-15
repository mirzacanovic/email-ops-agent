"""HTTP Basic authentication against the `users` table.

Basic auth keeps the review UI free of session/cookie machinery (and of the
extra dependencies a login form would need), and the plain HTML forms keep
working unchanged. It sends credentials on every request, so it must only
be served over TLS outside of local demos. Fails closed: with no users in
the database, every protected route answers 401.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.models import User
from app.auth.passwords import DUMMY_HASH, verify_password
from app.db.session import get_db

_basic = HTTPBasic(realm="Email Ops Agent", auto_error=False)


def require_user(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": 'Basic realm="Email Ops Agent"'},
    )
    if credentials is None:
        raise unauthorized

    user = db.scalar(select(User).where(User.username == credentials.username))
    # Always run one verification, even for an unknown user (see DUMMY_HASH).
    ok = verify_password(credentials.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not ok:
        raise unauthorized
    return user

