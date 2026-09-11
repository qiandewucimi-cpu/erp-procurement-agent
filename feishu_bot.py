"""飞书长连接机器人：把「外贸 ERP 安全操作 Agent」接进飞书对话。

设计要点（详见 docs/飞书接入方案.md）：
- 长连接模式：机器人主动连飞书，无需公网 IP / 域名 / 内网穿透；
- 复用现有 Agent：直接在同进程调用 PurchasePOAgent.chat()，api.py / ui.py / erp_agent/* 零改动；
- 本文件只做「翻译」：飞书事件 → agent 入参；agent 回复 → 飞书消息。
- 安全边界不变：金额、业务校验、写入口令仍由工具层确定性代码保证。飞书里输入「确认提交」才会写入。

启动：python feishu_bot.py
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    P2ImMessageReceiveV1,
)

from erp_agent import llm  # noqa: F401  仅为触发 .env 加载（llm.py 里的 _load_dotenv）
from erp_agent.agent import PurchasePOAgent
from erp_agent.knowledge import KnowledgeBase
from erp_agent.repository import ERPRepository


# 让 print() 立刻输出：否则重定向到文件/管道时 Python 会块缓冲，
# 导致「收到消息」这类日志迟迟看不到（排查问题时很坑）。
try:
    import sys

    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:  # pragma: no cover - 老版本 Python 或特殊 stdout
    pass


BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = Path(os.getenv("ERP_AGENT_UPLOADS", BASE_DIR / "uploads"))

APP_ID = os.getenv("FEISHU_APP_ID", "").strip()
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "").strip()
ALLOWED_OPEN_IDS = {x.strip() for x in os.getenv("FEISHU_ALLOWED_OPEN_IDS", "").split(",") if x.strip()}
REQUIRE_MENTION_IN_GROUP = os.getenv("FEISHU_REQUIRE_MENTION_IN_GROUP", "true").lower() in ("1", "true", "yes")
# 回复用消息卡片（渲染 Markdown、按语义上色）；设为 false 则退回纯文本
REPLY_WITH_CARD = os.getenv("FEISHU_REPLY_CARD", "true").lower() in ("1", "true", "yes")

# 文件扩展名白名单：只有这些才当作 BOM / 物料档案处理
_FILE_EXTS = {".xlsx", ".xlsm", ".xls", ".csv"}
_EMPTY_REPLY = "（这条消息没能处理，请换个说法再试一次）"

# --------------------------------------------------------------------------- #
# 复用现有 Agent（同进程直调，最省事；不需先起 API）
# --------------------------------------------------------------------------- #
agent = PurchasePOAgent(
    ERPRepository(BASE_DIR / "data" / "demo_erp.db"),
    KnowledgeBase(BASE_DIR / "knowledge"),
    BASE_DIR / "samples",
)
client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

# sessions 是进程内共享的，加锁避免并发写坏历史
_agent_lock = threading.Lock()

# 飞书会重推事件，按 message_id 去重（有界，防内存无限增长）
_seen: "OrderedDict[str, None]" = OrderedDict()
_seen_lock = threading.Lock()

# 每个用户最近一次上传的文件名（用于「检测错误」这类不点名的指令）
_last_file: dict[str, str] = {}


def _dedup(message_id: str) -> bool:
    """True = 首次见到，可以处理；False = 重复推送，应忽略。"""
    with _seen_lock:
        if message_id in _seen:
            return False
        _seen[message_id] = None
        while len(_seen) > 2000:
            _seen.popitem(last=False)
    return True


# --------------------------------------------------------------------------- #
# 飞书 → 文本
# --------------------------------------------------------------------------- #
def _strip_mentions(text: str, mentions: list) -> str:
    """群里 @机器人时，正文里会残留 @_user_1 这类占位符，去掉它。"""
    for mention in mentions or []:
        key = getattr(mention, "key", None)
        if key:
            text = text.replace(key, "")
    return text.strip()


def _send_text(open_id: str, text: str) -> None:
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(open_id)
        .msg_type("text")
        .content(json.dumps({"text": text}, ensure_ascii=False))
        .build()
    )
    request = CreateMessageRequest.builder().receive_id_type("open_id").request_body(body).build()
    response = client.im.v1.message.create(request)
    if not response.success():
        print(f"[warn] 发送失败 code={response.code} msg={response.msg}")
    else:
        print(f"[info] 已发送文本 open_id={open_id} 长度={len(text)}")


def _download_file(message_id: str, file_key: str, file_name: str) -> Path:
    """把飞书消息里的文件下载到 uploads/，返回本地路径。

    文件名会先剥离目录成分，只保留 basename，避免写到 uploads/ 之外。
    """
    request = (
        GetMessageResourceRequest.builder()
        .message_id(message_id)
        .file_key(file_key)
        .type("file")
        .build()
    )
    response = client.im.v1.message_resource.get(request)
    if not response.success():
        raise RuntimeError(f"文件下载失败 code={response.code} msg={response.msg}")

    data = response.file.read()
    try:
        response.file.close()
    except Exception:
        pass

    # SDK 返回的 file_name 更可靠，优先用它
    real_name = getattr(response, "file_name", None) or file_name
    safe_name = Path(real_name).name or "uploaded.xlsx"
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOADS_DIR / safe_name
    path.write_bytes(data)
    return path


# --------------------------------------------------------------------------- #
# Agent 回复 → 飞书
# --------------------------------------------------------------------------- #
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_HEAD = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_FENCE = re.compile(r"^```.*$", re.MULTILINE)


def _to_feishu_text(reply: str) -> str:
    """飞书纯文本消息不渲染 Markdown，这里做最小清洗，避免满屏 ** 和 ###。"""
    text = _MD_FENCE.sub("", reply or "")
    text = _MD_HEAD.sub("", text)
    text = _MD_BOLD.sub(r"\1", text)
    return text.strip() or _EMPTY_REPLY


def _trace_summary(trace: list) -> str:
    """把工具轨迹压成一行摘要，不把原始 JSON 推给用户。"""
    if not trace:
        return ""
    names: list[str] = []
    for item in trace:
        name = item.get("tool", "?")
        if name not in names:
            names.append(name)
    return f"\n\n—\n工具调用 {len(trace)} 步：{'、'.join(names)}"


# --------------------------------------------------------------------------- #
# 消息卡片：展示增强（渲染 Markdown、按语义上色）
# 安全约束：卡片只读，**不放一键写入按钮** —— 写入必须靠用户回复「确认提交」口令。
# --------------------------------------------------------------------------- #
_MD_FENCE_LINE = re.compile(r"^\s*```.*$", re.MULTILINE)
_MD_HEAD_MARKS = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MD_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.MULTILINE)


def _to_lark_md(reply: str) -> str:
    """卡片正文用 lark_md：保留 **加粗** 与列表，去掉代码围栏、# 标题符号和表格分隔行。"""
    text = _MD_FENCE_LINE.sub("", reply or "")
    text = _MD_TABLE_SEP.sub("", text)
    text = _MD_HEAD_MARKS.sub("", text)
    return text.strip() or _EMPTY_REPLY


def _pick_header_template(text: str) -> str:
    """按语义给卡片上色：出错橙、写入成功绿、其余蓝。"""
    if any(k in text for k in ("阻断", "错误", "失败", "未建档", "不通过")):
        return "orange"
    if any(k in text for k in ("已写入", "写入成功", "COMMITTED", "已提交")):
        return "green"
    return "blue"


def _build_card(reply_md: str, trace: list, llm_enabled: bool) -> dict:
    elements: list = [{"tag": "div", "text": {"tag": "lark_md", "content": reply_md}}]

    notes: list = []
    if trace:
        names: list = []
        for item in trace:
            name = item.get("tool", "?")
            if name not in names:
                names.append(name)
        notes.append(f"工具调用 {len(trace)} 步：{'、'.join(names)}")
    if not llm_enabled:
        notes.append("模型未启用，当前为确定性流水线模式")
    # 仅当这条回复看起来是「待写入的草稿」时才提示口令，避免每条消息都刷屏
    if any(k in reply_md for k in ("草稿", "待确认", "确认提交", "action_id")):
        notes.append("以上为草稿预览，确认无误请回复「确认提交」，才会真正写入")

    if notes:
        elements.append({"tag": "hr"})
        elements.append(
            {"tag": "note", "elements": [{"tag": "plain_text", "content": " ｜ ".join(notes)}]}
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": _pick_header_template(reply_md),
            "title": {"tag": "plain_text", "content": "外贸 ERP Agent"},
        },
        "elements": elements,
    }


def _send_card(open_id: str, card: dict) -> bool:
    """发送交互卡片；返回是否成功，失败时由调用方回退为纯文本。"""
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(open_id)
        .msg_type("interactive")
        .content(json.dumps(card, ensure_ascii=False))
        .build()
    )
    request = CreateMessageRequest.builder().receive_id_type("open_id").request_body(body).build()
    try:
        response = client.im.v1.message.create(request)
    except Exception as exc:  # noqa: BLE001 - 网络/SDK 异常都不该让机器人静默
        print(f"[warn] 卡片发送异常 {type(exc).__name__}: {exc}")
        return False
    if not response.success():
        print(f"[warn] 卡片发送失败 code={response.code} msg={response.msg}")
        return False
    print(f"[info] 已发送卡片 open_id={open_id}")
    return True


def _reply_with_agent(open_id: str, user_text: str, session_id: str) -> None:
    try:
        with _agent_lock:
            result = agent.chat([{"role": "user", "content": user_text}], session_id)
    except Exception as exc:  # 任何异常都转成可读回复，别让机器人静默
        _send_text(open_id, f"（处理失败：{type(exc).__name__}: {exc}）")
        return

    raw = result.get("reply", "")
    trace = result.get("tool_trace", []) or []
    llm_enabled = bool(result.get("llm_enabled"))

    # 优先发消息卡片（渲染 Markdown + 按语义上色）；失败则退回纯文本，保证不失联
    if REPLY_WITH_CARD:
        if _send_card(open_id, _build_card(_to_lark_md(raw), trace, llm_enabled)):
            return
        print("[warn] 卡片发送未成功，回退为纯文本")

    text = _to_feishu_text(raw) + _trace_summary(trace)
    if not llm_enabled:
        text += "\n\n（提示：模型未启用，当前为确定性流水线模式）"
    _send_text(open_id, text)


# --------------------------------------------------------------------------- #
# 飞书事件入口
# --------------------------------------------------------------------------- #
def _on_message(data: P2ImMessageReceiveV1) -> None:
    event = data.event
    message = event.message
    sender_id = event.sender.sender_id
    open_id = sender_id.open_id

    # 1) 幂等：飞书会重推相同事件
    if not _dedup(message.message_id):
        return

    # 2) 白名单：未配置时不限制（仅建议本机自测），配置后只服务指定的人
    if ALLOWED_OPEN_IDS and open_id not in ALLOWED_OPEN_IDS:
        print(f"[info] 拒绝未授权用户 open_id={open_id}")
        _send_text(open_id, "抱歉，这个机器人目前未对你开放。")
        return

    is_group = message.chat_type == "group"
    mentions = message.mentions or []

    # 3) 群里默认只在被 @ 时响应（单聊不受影响）
    if is_group and REQUIRE_MENTION_IN_GROUP and not mentions:
        print(f"[info] 群消息未 @ 机器人，忽略（可把 FEISHU_REQUIRE_MENTION_IN_GROUP 设为 false 关闭）")
        return

    try:
        content = json.loads(message.content or "{}")
    except json.JSONDecodeError:
        content = {}

    session_id = f"feishu:{open_id}"
    message_type = message.message_type

    # 4) 文本消息 → 直接交给 Agent
    if message_type == "text":
        user_text = _strip_mentions(str(content.get("text", "")), mentions)
        print(f"[info] 收到文本 open_id={open_id} chat={message.chat_type} text={user_text!r}")
        if not user_text:
            _send_text(open_id, "我在，直接说需求就行～比如「查一下 MAT-FAB-001 的价格」。")
            return

        # 若用户没点文件名，但刚上传过文件，附一句提示给模型（用户看不到）
        hint = ""
        if not any(ext in user_text.lower() for ext in _FILE_EXTS):
            last = _last_file.get(open_id)
            if last:
                hint = f"\n[系统提示：该用户刚上传的文件名为「{last}」，若未指明文件名可优先使用它]"

        threading.Thread(
            target=_reply_with_agent, args=(open_id, user_text + hint, session_id), daemon=True
        ).start()
        return

    # 5) 文件消息 → 下载到 uploads/，再提示怎么用
    if message_type == "file":
        file_key = str(content.get("file_key", ""))
        file_name = str(content.get("file_name", "uploaded.xlsx"))
        suffix = Path(file_name).suffix.lower()
        if suffix not in _FILE_EXTS:
            _send_text(open_id, f"暂不支持 {suffix or '这种'} 格式，请上传 .xlsx / .xlsm / .csv 的 BOM 或物料档案。")
            return
        try:
            path = _download_file(message.message_id, file_key, file_name)
        except Exception as exc:
            _send_text(open_id, f"文件接收失败：{type(exc).__name__}: {exc}")
            return
        _last_file[open_id] = path.name
        print(f"[info] 文件已落地 {path}")
        _send_text(
            open_id,
            f"已收到「{path.name}」。你可以直接说：\n"
            f"· 检测一下 {path.name} 有哪些物料错误\n"
            f"· 根据 {path.name} 生成采购 PO 草稿",
        )
        return

    # 6) 其他类型（图片/语音等）
    _send_text(open_id, f"暂时只支持文字和 BOM 文件，收到的是「{message_type}」。")


def main() -> None:
    missing = [k for k, v in {"FEISHU_APP_ID": APP_ID, "FEISHU_APP_SECRET": APP_SECRET}.items() if not v]
    if missing:
        raise SystemExit(f"缺少配置：{', '.join(missing)}。请在项目根目录 .env 里填写（参考 .env.example）。")

    if not ALLOWED_OPEN_IDS:
        print("[warn] 未设置 FEISHU_ALLOWED_OPEN_IDS，当前任何能私聊到机器人的人都能用。建议先随便发一句，从日志里取 open_id 回填白名单。")

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .build()
    )
    ws_client = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO)
    print("飞书长连接机器人启动中……（无需公网，保持本窗口不关）")
    ws_client.start()


if __name__ == "__main__":
    main()
