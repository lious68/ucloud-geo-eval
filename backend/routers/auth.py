"""认证路由"""
import hashlib
import secrets
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import database as db

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)

# 需要鉴权的路由前缀
PROTECTED_PREFIXES = ["/api/settings", "/api/evaluations", "/api/questions"]


def hash_password(password: str) -> str:
    """SHA256 密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证当前用户"""
    if not credentials:
        raise HTTPException(401, "未登录")
    token = credentials.credentials
    valid = await db.verify_session(token)
    if not valid:
        raise HTTPException(401, "登录已过期，请重新登录")
    return token


@router.post("/login")
async def login(body: dict):
    """登录"""
    password = body.get("password", "")
    stored_hash = await db.get_admin_password_hash()

    # 首次登录：设置密码
    if not stored_hash:
        if len(password) < 6:
            raise HTTPException(400, "密码至少6位")
        await db.set_admin_password_hash(hash_password(password))
        token = secrets.token_hex(32)
        await db.create_session(token)
        return {"success": True, "data": {"token": token, "is_first_login": True}}

    # 验证密码
    if hash_password(password) != stored_hash:
        raise HTTPException(401, "密码错误")

    token = secrets.token_hex(32)
    await db.create_session(token)
    return {"success": True, "data": {"token": token, "is_first_login": False}}


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """登出"""
    if credentials:
        await db.delete_session(credentials.credentials)
    return {"success": True}


@router.get("/check")
async def check_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """检查登录状态"""
    if not credentials:
        has_password = bool(await db.get_admin_password_hash())
        return {"success": True, "data": {"authenticated": False, "has_password": has_password}}
    valid = await db.verify_session(credentials.credentials)
    return {"success": True, "data": {"authenticated": valid, "has_password": True}}


@router.post("/change-password")
async def change_password(body: dict, credentials: HTTPAuthorizationCredentials = Depends(get_current_user)):
    """修改密码"""
    old_password = body.get("old_password", "")
    new_password = body.get("new_password", "")

    stored_hash = await db.get_admin_password_hash()
    if hash_password(old_password) != stored_hash:
        raise HTTPException(401, "原密码错误")
    if len(new_password) < 6:
        raise HTTPException(400, "新密码至少6位")

    await db.set_admin_password_hash(hash_password(new_password))
    # 清除所有旧会话
    db_conn = await db.get_db()
    try:
        await db_conn.execute("DELETE FROM admin_sessions")
        await db_conn.commit()
    finally:
        await db_conn.close()

    # 创建新会话
    token = secrets.token_hex(32)
    await db.create_session(token)
    return {"success": True, "data": {"token": token}}
