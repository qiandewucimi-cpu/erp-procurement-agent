from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st


API_BASE = os.getenv("ERP_AGENT_API", "http://127.0.0.1:8000")
# 用户上传目录：与后端 uploads/ 为同一处（容器场景通过 volume 共享）
UPLOADS_DIR = Path(os.getenv("ERP_AGENT_UPLOADS", "uploads"))


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{API_BASE}{path}", timeout=120, **kwargs)
    if not response.ok:
        detail = response.json().get("detail", response.text)
        raise RuntimeError(detail)
    return response.json()


st.set_page_config(page_title="外贸 ERP 安全操作 Agent", page_icon="🧭", layout="wide")
st.title("外贸 ERP 安全操作 Agent")
st.caption("合成数据 Demo · 工具调用 Agent · 多轮对话 · 写前确认 · 审计与回滚")
st.info("本项目不连接任何真实企业系统，页面中的客户、供应商、价格和单号均为虚构数据。")

# ---------------- 模型状态 ----------------
# 说明：模型不可用时，Agent 会静默回退到确定性流水线（能跑，但不会自主编排工具），
# 因此这里必须显式告诉用户「模型到底在不在工作」。
try:
    _health = api("GET", "/health")
except Exception:
    _health = None

if _health is None:
    st.error("⚠️ 后端未启动：请先运行 `start_demo.cmd`（或 `docker compose up -d`），否则本页功能不可用。")
elif _health.get("llm_enabled"):
    st.success(f"🤖 模型已启用：`{_health.get('llm_model')}` —— 工具调用由模型自主编排")
else:
    st.warning(
        "⚠️ 模型未启用，当前运行在**确定性流水线**模式：功能仍可用（离线也能跑），"
        "但 Agent 不会自主编排工具。请检查项目根目录 `.env` 里的 `LLM_API_KEY`。"
    )

tab_chat, tab_audit = st.tabs(["Agent 对话", "订单与审计"])


def render_trace(trace: list[dict]) -> None:
    if not trace:
        return
    with st.expander("查看 Agent 工具调用轨迹", expanded=True):
        for item in trace:
            step = item.get("step", "?")
            tool = item.get("tool", "")
            purpose = item.get("purpose", "")
            result = item.get("result", "")
            st.markdown(f"**{step}. {tool}** — {purpose}")
            try:
                import json

                parsed = json.loads(result)
                st.json(parsed)
            except Exception:
                st.text(result)


with tab_chat:
    # ---------------- 导入自己的 BOM ----------------
    with st.expander("📤 导入自己的 BOM（.xlsx / .xlsm / .csv）", expanded=False):
        st.caption(
            "上传的文件只保存在本机 `uploads/` 目录，不会上传到任何外部服务，"
            "也已被 .gitignore 排除，不会进 Git。文件格式需与示例 BOM 一致"
            "（含物料编码、物料名称、数量、单位列）。"
        )
        # 提示已建档物料：避免用户导入自己的 BOM 后，因编码不匹配被判「未建档」而困惑
        try:
            mats = api("GET", "/materials")
            if mats:
                st.caption(
                    "当前模拟 ERP 已建档的物料如下。**你的 BOM 里的物料编码需要与之匹配**，"
                    "否则会被判为「未建档」并阻断。想用自己的真实物料，需要先把档案导入模拟库。"
                )
                st.dataframe(
                    pd.DataFrame(mats)[
                        ["material_code", "material_name", "supplier_name", "unit_price", "packaging_fee", "currency"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
        except Exception:
            pass

        uploaded = st.file_uploader("选择 BOM 文件", type=["xlsx", "xlsm", "csv"], key="bom_upload")
        if uploaded is not None:
            safe_name = Path(uploaded.name).name  # 剥离任何目录成分
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            (UPLOADS_DIR / safe_name).write_bytes(uploaded.getbuffer())
            st.success(f"已导入 `{safe_name}`，现在可以直接对我说：")
            st.markdown(
                f"- 「检测一下 **{safe_name}** 有哪些物料错误」\n"
                f"- 「根据 **{safe_name}** 生成采购 PO 草稿」"
            )
            st.session_state.uploaded_bom = safe_name

    if "session_id" not in st.session_state:
        st.session_state.session_id = uuid.uuid4().hex[:8]
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            render_trace(message.get("trace", []))

    if not st.session_state.messages:
        with st.chat_message("assistant"):
            st.markdown(
                "你好，我是采购操作助手。你可以直接用自然语言让我办事，比如：\n\n"
                "- 「帮我根据 **正常示例_BOM.xlsx** 生成采购 PO 草稿，先给我看金额」\n"
                "- 「查一下 MAT-FAB-001 的价格和包装费」\n"
                "- 「检测一下 **异常示例_BOM.xlsx** 有哪些物料错误」\n"
                "- 生成草稿后，输入「**确认提交**」我才会真正写入模拟 ERP"
            )

    if prompt := st.chat_input("描述你的采购需求…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            try:
                data = api(
                    "POST",
                    "/agent/chat",
                    json={
                        "session_id": st.session_state.session_id,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                reply = data.get("reply", "")
                trace = data.get("tool_trace", [])
                st.markdown(reply)
                render_trace(trace)
                st.session_state.messages.append({"role": "assistant", "content": reply, "trace": trace})
            except Exception as exc:
                st.error(f"调用失败：{exc}")

with tab_audit:
    if st.button("刷新订单与审计"):
        st.rerun()
    try:
        orders = api("GET", "/orders")
        audits = api("GET", "/audit")
        reports = api("GET", "/error_reports")
        st.subheader("模拟 ERP 采购 PO")
        st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True)
        st.subheader("审计日志")
        st.dataframe(pd.DataFrame(audits), use_container_width=True, hide_index=True)
        st.subheader("物料错误报告（推送队列）")
        st.dataframe(pd.DataFrame(reports), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.warning(f"后端尚未启动：{exc}")
