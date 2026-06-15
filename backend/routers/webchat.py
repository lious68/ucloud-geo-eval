"""WebChat 认证状态管理路由"""
import os
import sys
import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from routers.auth import require_admin
from typing import Dict

# 添加 core 模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_auth import (
    has_auth_state, save_auth_state, delete_auth_state,
    get_all_auth_status, WEBCHAT_SITES, load_auth_state,
    validate_auth_cookies,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webchat", tags=["webchat"])


@router.get("/auth/status")
async def get_auth_status():
    """获取所有模型的 WebChat 认证状态（含精确验证）"""
    status = get_all_auth_status()
    return {"success": True, "data": status}


@router.post("/auth/upload/{model_key}")
async def upload_auth_state(model_key: str, file: UploadFile = File(...), user=Depends(require_admin)):
    """上传 Playwright storageState JSON 认证文件

    用户在本机运行 setup_webchat_auth.py 后，将生成的 JSON 文件上传到服务器。
    上传完成后自动验证认证状态。
    """
    if model_key not in WEBCHAT_SITES:
        raise HTTPException(400, f"未知模型: {model_key}")

    # 读取上传的文件内容
    content = await file.read()
    try:
        state_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "文件不是有效的 JSON 格式")

    # 验证 storageState 格式
    if not isinstance(state_data, dict):
        raise HTTPException(400, "storageState 必须是 JSON 对象")

    # 保存认证状态
    path = save_auth_state(model_key, state_data)

    # 上传后立即验证
    validation = validate_auth_cookies(model_key)

    return {
        "success": True,
        "data": {
            "model_key": model_key,
            "name": WEBCHAT_SITES[model_key]["name"],
            "auth_path": path,
            "has_auth": validation["has_auth"],
            "is_valid": validation["is_valid"],
            "matched_cookies": validation["matched_cookies"],
            "cookie_count": validation["cookie_count"],
            "details": validation["details"],
        },
    }


@router.post("/auth/validate/{model_key}")
async def validate_auth(model_key: str):
    """验证认证状态是否仍有效

    检查该平台的关键认证 cookie 是否存在、域名匹配、未过期。
    匹配任意一个关键 cookie 即视为登录有效。
    """
    if model_key not in WEBCHAT_SITES:
        raise HTTPException(400, f"未知模型: {model_key}")

    result = validate_auth_cookies(model_key)
    result["model_key"] = model_key
    result["name"] = WEBCHAT_SITES[model_key]["name"]
    return {"success": True, "data": result}


@router.delete("/auth/{model_key}")
async def remove_auth_state(model_key: str, user=Depends(require_admin)):
    """删除认证状态"""
    if model_key not in WEBCHAT_SITES:
        raise HTTPException(400, f"未知模型: {model_key}")

    deleted = delete_auth_state(model_key)
    return {"success": True, "data": {"model_key": model_key, "deleted": deleted}}