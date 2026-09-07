from __future__ import annotations

import os
import uuid

import pandas as pd
import requests
import streamlit as st


API_BASE = os.getenv("ERP_AGENT_API", "http://127.0.0.1:8000")


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
        st.subheader("模拟 ERP 采购 PO")
        st.dataframe(pd.DataFrame(orders), use_container_width=True, hide_index=True)
        st.subheader("审计日志")
        st.dataframe(pd.DataFrame(audits), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.warning(f"后端尚未启动：{exc}")
