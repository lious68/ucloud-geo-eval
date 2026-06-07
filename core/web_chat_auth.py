"""
UCloud GEO 评估框架 - WebChat 认证状态管理
管理各 AI 模型官网的登录状态（Playwright storageState JSON 文件）
"""
import os
import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# 认证状态文件目录
AUTH_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "webchat_auth")

# 各模型对应的官网地址
WEBCHAT_SITES = {
    "deepseek": {
        "name": "DeepSeek",
        "url": "https://chat.deepseek.com",
    },
    "ernie": {
        "name": "文心一言",
        "url": "https://yiyan.baidu.com",
    },
    "doubao": {
        "name": "豆包",
        "url": "https://www.doubao.com/chat",
    },
    "kimi": {
        "name": "Kimi",
        "url": "https://kimi.moonshot.cn",
    },
    "qwen": {
        "name": "通义千问",
        "url": "https://tongyi.aliyun.com/tongyi/tongyi-hybrid",
    },
}


def ensure_auth_dir():
    """确保认证文件目录存在"""
    os.makedirs(AUTH_DIR, exist_ok=True)


def get_auth_path(model_key: str) -> str:
    """获取某模型的认证状态文件路径"""
    ensure_auth_dir()
    return os.path.join(AUTH_DIR, f"{model_key}_state.json")


def has_auth_state(model_key: str) -> bool:
    """检查某模型是否有认证状态文件"""
    path = get_auth_path(model_key)
    if not os.path.exists(path):
        return False
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # storageState 至少要有 cookies 或 origins
        return bool(data.get("cookies") or data.get("origins"))
    except (json.JSONDecodeError, ValueError):
        return False


def save_auth_state(model_key: str, state_data: Dict) -> str:
    """保存认证状态到文件

    Args:
        model_key: 模型标识 (如 "kimi")
        state_data: Playwright storageState dict (包含 cookies 和 origins)

    Returns:
        保存的文件路径
    """
    path = get_auth_path(model_key)
    Path(path).write_text(json.dumps(state_data, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved auth state for {model_key} to {path}")
    return path


def load_auth_state(model_key: str) -> Optional[Dict]:
    """加载认证状态

    Returns:
        storageState dict，或 None（文件不存在/无效）
    """
    path = get_auth_path(model_key)
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not (data.get("cookies") or data.get("origins")):
            return None
        return data
    except (json.JSONDecodeError, ValueError):
        return None


def delete_auth_state(model_key: str) -> bool:
    """删除认证状态文件"""
    path = get_auth_path(model_key)
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Deleted auth state for {model_key}")
        return True
    return False


def get_all_auth_status() -> Dict[str, Dict]:
    """获取所有模型的认证状态概览"""
    result = {}
    for model_key, site_info in WEBCHAT_SITES.items():
        has_auth = has_auth_state(model_key)
        result[model_key] = {
            "model_key": model_key,
            "name": site_info["name"],
            "url": site_info["url"],
            "has_auth": has_auth,
            "auth_path": get_auth_path(model_key) if has_auth else None,
        }
    return result