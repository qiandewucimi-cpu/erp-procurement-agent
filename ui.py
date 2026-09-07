from __future__ import annotations

import base64
import os

import pandas as pd
import requests
import streamlit as st


API_BASE = os.getenv("ERP_AGENT_API", "http://127.0.0.1:8000")


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{API_BASE}{path}", timeout=30, **kwargs)
    if not response.ok:
        detail = response.json().get("detail", response.text)
        raise RuntimeError(detail)
    return response.json()


st.set_page_config(page_title="外贸 ERP 安全操作 Agent", page_icon="🧭", layout="wide")
st.title("外贸 ERP 安全操作 Agent")
st.caption("合成数据 Demo · BOM → 采购 PO · RAG 来源 · 写前确认 · 审计与回滚")
st.info("本项目不连接任何真实企业系统，页面中的客户、供应商、价格和单号均为虚构数据。")

tab_agent, tab_audit = st.tabs(["Agent 工作台", "订单与审计"])

with tab_agent:
    task = st.text_area(
        "业务任务",
        "请根据上传的 BOM 生成采购 PO 草稿，查询物料档案、单价和包装费，检查异常；不要直接写入，先让我确认。",
        height=90,
    )
    left, right = st.columns([2, 1])
    with left:
        uploaded = st.file_uploader("上传 BOM（.xlsx / .csv）", type=["xlsx", "xlsm", "csv"])
    with right:
        sample = st.selectbox("或使用合成示例", ["正常示例_BOM.xlsx", "异常示例_BOM.xlsx"])

    if st.button("让 Agent 分析并生成草稿", type="primary", use_container_width=True):
        payload = {"task": task, "filename": sample}
        if uploaded is not None:
            payload["filename"] = uploaded.name
            payload["content_base64"] = base64.b64encode(uploaded.getvalue()).decode()
        try:
            st.session_state.preview = api("POST", "/agent/prepare", json=payload)
        except Exception as exc:
            st.error(f"生成失败：{exc}")

    preview = st.session_state.get("preview")
    if preview:
        st.subheader("Agent 执行轨迹")
        for step in preview["tool_trace"]:
            st.write(f"**{step['step']}. {step['tool']}** — {step['purpose']}  \\n+结果：{step['result']}")

        status_col, amount_col, action_col = st.columns(3)
        status_col.metric("状态", "等待确认" if preview["status"] == "ready_for_confirmation" else "已阻断")
        amount_col.metric("草稿总金额", f"¥ {preview['draft']['total_amount']:,.2f}")
        action_col.metric("Action ID", preview["action_id"])

        if preview["issues"]:
            st.subheader("校验结果")
            for issue in preview["issues"]:
                message = f"{issue['field']}：{issue['message']}"
                st.error(message) if issue["level"] == "blocking" else st.warning(message)
        else:
            st.success("全部业务校验通过。当前只生成了预览，尚未写入模拟 ERP。")

        st.subheader("采购 PO 草稿")
        header = {key: value for key, value in preview["draft"].items() if key != "items"}
        st.json(header)
        st.dataframe(pd.DataFrame(preview["draft"]["items"]), use_container_width=True, hide_index=True)

        st.subheader("RAG 检索依据")
        for citation in preview["citations"]:
            with st.expander(f"{citation['source']} / {citation['section']} · score={citation['score']}"):
                st.write(citation["excerpt"])

        st.subheader("安全确认")
        confirmation = st.text_input("若确认无误，请输入：确认提交", key="confirmation")
        if st.button("写入模拟 ERP", disabled=preview["status"] != "ready_for_confirmation"):
            try:
                result = api(
                    "POST",
                    "/agent/confirm",
                    json={"action_id": preview["action_id"], "confirmation": confirmation, "operator": "demo_user"},
                )
                st.session_state.commit_result = result
                st.success(f"已创建 {result['po_no']}。重复点击不会重复建单。")
            except Exception as exc:
                st.error(f"提交被拒绝：{exc}")

        committed = st.session_state.get("commit_result")
        if committed and committed["action_id"] == preview["action_id"]:
            reason = st.text_input("回滚原因", "面试演示：验证可回退能力")
            if st.button("回滚这张采购 PO"):
                try:
                    result = api(
                        "POST",
                        "/agent/rollback",
                        json={"action_id": preview["action_id"], "reason": reason, "operator": "demo_user"},
                    )
                    st.warning(f"{result['po_no']} 已标记为 ROLLED_BACK，审计记录仍保留。")
                except Exception as exc:
                    st.error(f"回滚失败：{exc}")

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

