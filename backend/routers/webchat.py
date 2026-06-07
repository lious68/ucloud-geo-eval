"""WebChat 认证状态管理路由"""
import os
import sys
import json
import logging
from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Dict

# 添加 core 模块路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from web_chat_auth import (
    has_auth_state, save_auth_state, delete_auth_state,
    get_all_auth_status, WEBCHAT_SITES, load_auth_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webchat", tags=["webchat"])


@router.get("/auth/status")
async def get_auth_status():
    """获取所有模型的 WebChat 认证状态"""
    status = get_all_auth_status()
    return {"success": True, "data": status}


@router.post("/auth/upload/{model_key}")
async def upload_auth_state(model_key: str, file: UploadFile = File(...)):
    """上传 Playwright storageState JSON 认证文件

    用户在本机运行 setup_webchat_auth.py 后，将生成的 JSON 文件上传到服务器
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

    return {
        "success": True,
        "data": {
            "model_key": model_key,
            "name": WEBCHAT_SITES[model_key]["name"],
            "auth_path": path,
            "has_auth": True,
        },
    }


@router.post("/auth/validate/{model_key}")
async def validate_auth_state(model_key: str):
    """验证认证状态是否仍有效

    尝试加载认证文件并检查基本格式
    """
    if model_key not in WEBCHAT_SITES:
        raise HTTPException(400, f"未知模型: {model_key}")

    state_data = load_auth_state(model_key)
    if not state_data:
        return {"success": True, "data": {"model_key": model_key, "has_auth": False, "is_valid": False}}

    # 简单检查：有 cookies 就可能有效
    cookies = state_data.get("cookies", [])
    has_cookies = len(cookies) > 0

    # 检查是否有关键的认证 cookie（各站点不同，这里只检查是否有 cookie）
    is_valid = has_cookies

    return {
        "success": True,
        "data": {
            "model_key": model_key,
            "name": WEBCHAT_SITES[model_key]["name"],
            "has_auth": True,
            "is_valid": is_valid,
            "cookie_count": len(cookies),
        },
    }


@router.delete("/auth/{model_key}")
async def remove_auth_state(model_key: str):
    """删除认证状态"""
    if model_key not in WEBCHAT_SITES:
        raise HTTPException(400, f"未知模型: {model_key}")

    deleted = delete_auth_state(model_key)
    return {"success": True, "data": {"model_key": model_key, "deleted": deleted}}