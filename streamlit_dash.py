# -*- coding: utf-8 -*-
"""
电商平台用户与订单综合数据分析 —— Streamlit 可视化看板
================================================================================
运行方式：
    streamlit run streamlit_dash.py
    （首次运行会自动在浏览器打开，默认地址 http://localhost:8501）

数据来源：
    同目录下 data_process.py 输出的清洗结果 clean_user.csv / clean_order.csv

看板内容：
    核心指标 | 转化漏斗 | 用户分群（渠道/新老/消费分层） | 品类分析 | 用户画像
    支持侧边栏按 注册渠道 / 用户等级 / 商品品类 动态筛选

依赖环境：pip install streamlit pandas numpy matplotlib
"""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # 无界面后端，由 Streamlit 渲染图片
import matplotlib.pyplot as plt
import streamlit as st

# ---------------- 图表中文字体设置 ----------------
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEW_USER_CUTOFF = pd.Timestamp("2025-01-01")   # 新老用户划分线（与 data_process.py 保持一致）

# ============================== 页面全局配置 ==============================
st.set_page_config(page_title="电商数据分析看板", layout="wide")
st.title("电商平台用户与订单综合数据分析看板")
st.caption("数据范围：2024-01-01 ~ 2025-06-30 | 数据来源：clean_user.csv / clean_order.csv（已清洗）")


# ============================== 数据加载 ==============================
@st.cache_data   # 缓存读取结果，筛选交互时不重复读文件
def load_data():
    """读取清洗后的用户表与订单表。"""
    user = pd.read_csv(os.path.join(BASE_DIR, "clean_user.csv"))
    order = pd.read_csv(os.path.join(BASE_DIR, "clean_order.csv"), parse_dates=["下单时间"])
    return user, order


user_all, order_all = load_data()


# ============================== 侧边栏筛选 ==============================
st.sidebar.header("筛选条件")


def multiselect_filter(label, series):
    """通用多选筛选器：默认全选；全部取消时视为不限（等价于全选）。"""
    options = sorted(series.dropna().unique().tolist())
    picked = st.sidebar.multiselect(label, options, default=options)
    return picked if picked else options


sel_channels = multiselect_filter("注册渠道", user_all["注册渠道"])
sel_levels = multiselect_filter("用户等级", user_all["用户等级"])
sel_categories = multiselect_filter("商品品类", order_all["商品品类"])

# 用户侧筛选（渠道/等级） -> 订单侧联动筛选（品类 + 用户范围）
u = user_all[user_all["注册渠道"].isin(sel_channels) & user_all["用户等级"].isin(sel_levels)]
o = order_all[order_all["user_id"].isin(u["user_id"]) & order_all["商品品类"].isin(sel_categories)]

st.sidebar.divider()
st.sidebar.metric("筛选后用户数", f"{len(u):,}")
st.sidebar.metric("筛选后订单数", f"{len(o):,}")

if o.empty:
    st.warning("当前筛选条件下没有订单数据，请调整筛选条件。")
    st.stop()

# 给筛选后的用户表补充"新老用户"标签（与离线分析口径一致）
u = u.copy()
u["用户分层"] = np.where(pd.to_datetime(u["注册时间"]) >= NEW_USER_CUTOFF,
                        "新用户(2025年注册)", "老用户(2024年注册)")


# ============================== 通用计算函数 ==============================
def calc_kpis(u, o):
    """核心指标计算（口径与 data_process.py 完全一致）。"""
    paid = o[o["是否支付"] == 1]
    total_users = u["user_id"].nunique()
    order_users = o["user_id"].nunique()
    paid_users = paid["user_id"].nunique()
    gmv = paid["订单金额"].sum()
    repurchase_users = int((paid.groupby("user_id").size() >= 2).sum())
    return {
        "GMV": gmv,
        "总订单量": len(o),
        "支付订单量": len(paid),
        "支付转化率(订单级)": len(paid) / len(o) if len(o) else 0,
        "下单用户数": order_users,
        "支付用户数": paid_users,
        "客单价": gmv / paid_users if paid_users else 0,
        "复购率": repurchase_users / paid_users if paid_users else 0,
        "下单转化率": order_users / total_users if total_users else 0,
    }


def calc_funnel(u, o):
    """用户级转化漏斗：浏览(注册近似) -> 加购 -> 下单 -> 支付。"""
    return pd.DataFrame({
        "环节": ["浏览商品(注册用户近似)", "加入购物车", "提交订单", "完成支付"],
        "人数": [
            u["user_id"].nunique(),
            o.loc[o["加购标记"] == 1, "user_id"].nunique(),
            o["user_id"].nunique(),
            o.loc[o["是否支付"] == 1, "user_id"].nunique(),
        ],
    })


def group_stats(u, o, group_col):
    """通用分组统计：下单转化率/支付转化率/复购率/客单价（与离线口径一致）。"""
    paid = o[o["是否支付"] == 1]
    stat = o.groupby("user_id").agg(订单数=("order_id", "count")).reset_index()
    pstat = paid.groupby("user_id").agg(支付订单数=("order_id", "count"),
                                        支付金额=("订单金额", "sum")).reset_index()
    stat = stat.merge(pstat, on="user_id", how="left")
    stat[["支付订单数", "支付金额"]] = stat[["支付订单数", "支付金额"]].fillna(0)
    m = u[["user_id", group_col]].merge(stat, on="user_id", how="left")
    m[["订单数", "支付订单数", "支付金额"]] = m[["订单数", "支付订单数", "支付金额"]].fillna(0)
    g = m.groupby(group_col).agg(
        用户数=("user_id", "nunique"),
        下单用户数=("订单数", lambda s: int((s > 0).sum())),
        支付用户数=("支付订单数", lambda s: int((s > 0).sum())),
        复购用户数=("支付订单数", lambda s: int((s >= 2).sum())),
        GMV=("支付金额", "sum"),
    ).reset_index()
    g["下单转化率"] = (g["下单用户数"] / g["用户数"]).round(4)
    g["支付转化率"] = (g["支付用户数"] / g["下单用户数"].replace(0, np.nan)).round(4)
    g["复购率"] = (g["复购用户数"] / g["支付用户数"].replace(0, np.nan)).round(4)
    g["客单价"] = (g["GMV"] / g["支付用户数"].replace(0, np.nan)).round(2)
    return g.sort_values("GMV", ascending=False).reset_index(drop=True)


def draw_funnel(f_df):
    """用 matplotlib 绘制居中漏斗图并返回 figure。"""
    values = f_df["人数"].tolist()
    n = len(values)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    colors = plt.cm.Blues(np.linspace(0.85, 0.35, n))   # 由深到浅的蓝色系
    max_v = values[0] if values[0] else 1
    for i, (name, v) in enumerate(zip(f_df["环节"], values)):
        y = n - 1 - i
        w = v / max_v
        ax.barh(y, w, left=(1 - w) / 2, height=0.6, color=colors[i], edgecolor="white")
        ax.text(0.5, y, f"{name}  {v:,}人（{v / max_v:.1%}）", ha="center", va="center",
                fontsize=11, fontweight="bold", color="white" if i < 2 else "#1a3a5c")
        if i > 0:
            ax.text(1.01, y + 0.5, f"环节转化率 {v / values[i - 1]:.1%}" if values[i - 1] else "-",
                    fontsize=9, color="#c0392b", va="center")
    ax.set_xlim(0, 1.18)
    ax.set_ylim(-0.55, n - 0.45)
    ax.axis("off")
    ax.set_title("用户转化漏斗：浏览 -> 加购 -> 下单 -> 支付", fontsize=13, pad=10)
    fig.tight_layout()
    return fig


# ============================== 页签布局 ==============================
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["核心指标", "转化漏斗", "用户分群", "品类分析", "用户画像"])

# ---------------- Tab 1：核心指标 ----------------
with tab1:
    k = calc_kpis(u, o)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("GMV（元）", f"{k['GMV']:,.0f}")
    c2.metric("总订单量", f"{k['总订单量']:,}")
    c3.metric("支付转化率（订单级）", f"{k['支付转化率(订单级)']:.1%}")
    c4.metric("客单价（元）", f"{k['客单价']:,.0f}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("支付用户数", f"{k['支付用户数']:,}")
    c6.metric("下单转化率（用户级）", f"{k['下单转化率']:.1%}")
    c7.metric("复购率", f"{k['复购率']:.1%}")
    c8.metric("支付转化率（用户级）", f"{o[o['是否支付'] == 1]['user_id'].nunique() / o['user_id'].nunique():.1%}")

    st.subheader("月度经营趋势")
    paid = o[o["是否支付"] == 1]
    monthly = o.groupby("下单月份").agg(订单量=("order_id", "count"))
    monthly["GMV"] = paid.groupby("下单月份")["订单金额"].sum().round(0)
    monthly = monthly.sort_index()
    col_a, col_b = st.columns([3, 2])
    with col_a:
        st.bar_chart(monthly["GMV"], height=280, use_container_width=True)
    with col_b:
        st.line_chart(monthly["订单量"], height=280, use_container_width=True)
    st.caption("口径说明：GMV 仅统计已支付订单；客单价 = GMV / 支付用户数。")

# ---------------- Tab 2：转化漏斗 ----------------
with tab2:
    f_df = calc_funnel(u, o)
    col_f, col_t = st.columns([3, 2])
    with col_f:
        st.pyplot(draw_funnel(f_df), use_container_width=True)
    with col_t:
        show = f_df.copy()
        show["整体转化率"] = (show["人数"] / show["人数"].iloc[0]).round(4)
        show["环节转化率"] = (show["人数"] / show["人数"].shift(1)).round(4)
        st.dataframe(show, use_container_width=True, hide_index=True)
    st.caption("口径说明：数据集无独立浏览/加购行为日志，浏览层以注册用户近似，"
               "加购标记挂在订单上（加购用户 >= 下单用户），因此加购->下单转化率接近100%；"
               "该环节真实流失需接入行为埋点数据度量。")

# ---------------- Tab 3：用户分群 ----------------
with tab3:
    st.subheader("注册渠道分群")
    ch = group_stats(u, o, "注册渠道")
    st.dataframe(ch, use_container_width=True, hide_index=True)
    rate_cols = ["下单转化率", "支付转化率", "复购率"]
    st.bar_chart(ch.set_index("注册渠道")[rate_cols] * 100, height=300, use_container_width=True)

    col_new, col_cons = st.columns(2)
    with col_new:
        st.subheader("新老用户对比")
        st.dataframe(group_stats(u, o, "用户分层"), use_container_width=True, hide_index=True)
    with col_cons:
        st.subheader("消费分层对比")
        st.dataframe(group_stats(u, o, "消费分层"), use_container_width=True, hide_index=True)
    st.caption("口径说明：新用户 = 2025-01-01 后注册；消费分层按累计支付金额 30%/70% 分位数划分。")

# ---------------- Tab 4：品类分析 ----------------
with tab4:
    paid = o[o["是否支付"] == 1]
    cat = o.groupby("商品品类").agg(订单量=("order_id", "count"),
                                   支付订单量=("是否支付", "sum"))
    cat["销售额"] = paid.groupby("商品品类")["订单金额"].sum().round(2)
    cat = cat.sort_values("销售额", ascending=False)
    cat["销售额占比"] = (cat["销售额"] / cat["销售额"].sum()).round(4)
    cat["支付转化率"] = (cat["支付订单量"] / cat["订单量"]).round(4)
    cat["笔单价"] = (cat["销售额"] / cat["支付订单量"]).round(2)

    col_c, col_p = st.columns([3, 2])
    with col_c:
        st.bar_chart(cat["销售额"], height=320, use_container_width=True)
    with col_p:
        # 环形饼图：品类销售额占比
        fig, ax = plt.subplots(figsize=(5.2, 4.6))
        ax.pie(cat["销售额"], labels=cat.index, autopct="%1.1f%%", startangle=90,
               counterclock=False, colors=plt.cm.Pastel1(np.arange(len(cat))),
               wedgeprops=dict(width=0.42, edgecolor="white"), textprops=dict(fontsize=8.5))
        ax.set_title("品类销售额占比", fontsize=12)
        st.pyplot(fig, use_container_width=True)
    st.dataframe(cat.reset_index(), use_container_width=True, hide_index=True)

# ---------------- Tab 5：用户画像 ----------------
with tab5:
    st.subheader("高复购用户 vs 非复购用户")
    pp = o[o["是否支付"] == 1]
    per_user = pp.groupby("user_id").agg(支付订单数=("order_id", "count"),
                                         支付金额=("订单金额", "sum"))
    per_user["用户类型"] = np.where(per_user["支付订单数"] >= 2, "复购用户", "非复购用户")
    profile = per_user.groupby("用户类型").agg(
        用户数=("支付订单数", "size"),
        人均支付订单数=("支付订单数", "mean"),
        人均支付金额=("支付金额", "mean")).round(2)
    st.dataframe(profile, use_container_width=True)

    # 品类偏好差异：复购/非复购用户的支付订单品类结构占比
    j = pp.merge(per_user["用户类型"], left_on="user_id", right_index=True)
    cat_share = j.groupby(["用户类型", "商品品类"]).size().rename("订单数").reset_index()
    cat_share["占比"] = cat_share.groupby("用户类型")["订单数"].transform(lambda s: s / s.sum())
    pivot = cat_share.pivot(index="商品品类", columns="用户类型", values="占比").fillna(0)
    pivot["偏好差异"] = pivot.get("复购用户", 0) - pivot.get("非复购用户", 0)
    pivot = pivot.sort_values("偏好差异", ascending=False).round(4)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("**品类偏好差异（复购-非复购订单占比）**")
        st.dataframe(pivot, use_container_width=True)
    with col_p2:
        st.markdown("**复购用户更偏好的品类（Top5）**")
        st.bar_chart(pivot["偏好差异"].head(5), height=300, use_container_width=True)
    st.caption("结论示例：复购用户在食品生鲜、美妆个护、家居日用等高频刚需品类的订单占比显著更高。")

    st.subheader("低转化用户定位（按渠道）")
    orderers = set(o["user_id"])
    payers = set(pp["user_id"])
    low = u.groupby("注册渠道").agg(用户数=("user_id", "nunique")).reset_index()
    # 注册未下单：从未产生订单的用户数与占比
    low["注册未下单用户"] = low["注册渠道"].map(
        u[~u["user_id"].isin(orderers)].groupby("注册渠道")["user_id"].nunique()).fillna(0).astype(int)
    low["注册未下单率"] = (low["注册未下单用户"] / low["用户数"]).round(4)
    # 下单未支付：有订单但从未支付的用户数与占比（分母为已下单用户数）
    low["下单未支付用户"] = low["注册渠道"].map(
        u[u["user_id"].isin(orderers) & ~u["user_id"].isin(payers)]
        .groupby("注册渠道")["user_id"].nunique()).fillna(0).astype(int)
    ordered_users = low["用户数"] - low["注册未下单用户"]
    low["下单未支付率"] = (low["下单未支付用户"] / ordered_users.replace(0, np.nan)).round(4)
    low = low.sort_values("注册未下单率", ascending=False)
    st.dataframe(low, use_container_width=True, hide_index=True)
    st.caption("结论示例：直播带货渠道注册未下单率与下单未支付率均为最高，是转化优化的重点人群。")
