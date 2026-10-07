import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from opspilot_common.auth import CurrentUser, create_access_token, get_current_user
from opspilot_common.errors import AppError

from app.db import get_db
from app.models import User
from app.schemas import LoginIn, TokenOut, UserOut
from app.security import verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut, summary="Đăng nhập, nhận JWT")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        logger.info("failed login for username=%s", body.username)
        raise AppError(401, "invalid_credentials", "Sai tên đăng nhập hoặc mật khẩu")
    token = create_access_token(user.id, user.username, user.role)
    logger.info("user %s logged in", user.id)
    return TokenOut(access_token=token, role=user.role, user_id=user.id)


@router.get("/me", response_model=UserOut, summary="Thông tin user hiện tại")
def me(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if current.is_system:
        return UserOut(id=current.id, username=current.username, role=current.role)
    user = db.get(User, current.id)
    if user is None:
        raise AppError(404, "user_not_found", "Không tìm thấy user")
    return user
