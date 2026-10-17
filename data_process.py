# -*- coding: utf-8 -*-
"""
电商平台用户与订单综合数据分析 —— 数据生成 / 清洗 / 分析 / 可视化 一体化脚本
================================================================================
项目背景：
    本项目模拟某电商平台 2024-01-01 ~ 2025-06-30 的用户与订单数据（共13000条，
    用户表5000条 + 订单表8000条），完成从数据清洗到业务分析的完整闭环，
    输出核心经营指标、转化漏斗、用户分群、品类分析与用户画像，
    并配套 SQL 分析脚本（mysql_analysis.sql）与 Streamlit 可视化看板
    （streamlit_dash.py）。

运行方式：
    python data_process.py        # 一键完成：生成数据 -> 清洗 -> 分析 -> 出图

输出文件：
    user_info.csv / order_info.csv        原始模拟数据（含脏数据）
    clean_user.csv / clean_order.csv      清洗后数据
    output/tables/*.csv                   各类分析结果表
    output/charts/*.png                   可视化图表

依赖环境：
    Python 3.9+，pandas / numpy / matplotlib / seaborn
    安装命令：pip install pandas numpy matplotlib seaborn
"""

import os
import random
from datetime import timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 使用无界面后端，服务器/无显示器环境也能正常出图
import matplotlib.pyplot as plt
import seaborn as sns

# ============================== 全局配置 ==============================
random.seed(42)   # 固定随机种子，保证每次运行结果完全一致（可复现）
np.random.seed(42)

# 中文字体设置（Windows 下 SimHei / 微软雅黑均可）
sns.set_style("whitegrid")   # seaborn 网格风格，图表更美观（注意：需在设置字体前调用，否则会覆盖字体配置）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False  # 解决负号 "-" 显示为方块的问题

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHART_DIR = os.path.join(BASE_DIR, "output", "charts")   # 图表输出目录
TABLE_DIR = os.path.join(BASE_DIR, "output", "tables")   # 分析结果表输出目录
os.makedirs(CHART_DIR, exist_ok=True)
os.makedirs(TABLE_DIR, exist_ok=True)

START_DATE = pd.Timestamp("2024-01-01")   # 平台上线日期（数据起点）
END_DATE = pd.Timestamp("2025-06-30")     # 统计截止日期（数据终点）
NEW_USER_CUTOFF = pd.Timestamp("2025-01-01")  # 新老用户划分线：2025年起注册视为新用户

N_USERS = 5000    # 用户表条数
N_ORDERS = 8000   # 订单表条数（两表合计 13000 条）

AMOUNT_MIN, AMOUNT_MAX = 5, 10000   # 订单金额的合理业务区间，超出视为异常

# 商品品类配置：品类名 -> (订单量权重, 品类基准客单价)
CATEGORY_CONF = {
    "服饰鞋包": (0.22, 180),
    "食品生鲜": (0.20, 60),
    "美妆个护": (0.16, 150),
    "家居日用": (0.12, 90),
    "数码家电": (0.10, 1200),
    "运动户外": (0.08, 260),
    "母婴用品": (0.07, 220),
    "图书文娱": (0.05, 45),
}
# 复购订单的品类偏好系数：复购更多发生在高频刚需品类（食品生鲜/美妆/家居）
REPEAT_CATEGORY_BOOST = {"食品生鲜": 2.2, "美妆个护": 1.8, "家居日用": 1.5}

# 注册渠道配置：
#   占比       —— 渠道拉新的结构占比
#   下单概率   —— 该渠道用户发生首单的概率（反映渠道引流质量）
#   支付率     —— 下单后完成支付的概率（反映冲动消费/流失情况）
#   客单价系数 —— 对订单金额的放大系数（反映渠道用户消费力）
#   复购倾向   —— 获得额外（复购）订单的权重（反映渠道用户粘性）
CHANNEL_CONF = {
    "自然流量": {"占比": 0.28, "下单概率": 0.78, "支付率": 0.82, "客单价系数": 1.00, "复购倾向": 1.30},
    "付费广告": {"占比": 0.20, "下单概率": 0.66, "支付率": 0.78, "客单价系数": 1.25, "复购倾向": 0.80},
    "社交媒体": {"占比": 0.24, "下单概率": 0.70, "支付率": 0.80, "客单价系数": 0.95, "复购倾向": 1.00},
    "直播带货": {"占比": 0.16, "下单概率": 0.52, "支付率": 0.68, "客单价系数": 0.80, "复购倾向": 0.60},
    "老带新":   {"占比": 0.12, "下单概率": 0.75, "支付率": 0.88, "客单价系数": 1.10, "复购倾向": 2.00},
}
CHANNELS = list(CHANNEL_CONF.keys())

# 用户等级及占比（清洗时异常等级统一归为"未知等级"）
LEVELS = ["新手", "白银", "黄金", "铂金", "钻石"]
LEVEL_WEIGHTS = [0.30, 0.28, 0.22, 0.13, 0.07]


# ============================== 通用工具函数 ==============================
def parse_time_safe(val):
    """尝试多种常见格式解析时间字符串，全部失败则返回 NaT（无效时间）。

    兼容场景：'2024-03-05 14:23:11'、'2024/3/5' 等合法格式，
    以及 '2024-02-30'（不存在的日期）、'not_a_time' 等非法字符串。
    """
    if pd.isna(val):
        return pd.NaT
    s = str(val).strip()
    if not s:
        return pd.NaT
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M",
                "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            continue
    return pd.NaT


def pick_category(repeat=False):
    """按权重随机抽取商品品类；复购订单向高频刚需品类倾斜。"""
    names = list(CATEGORY_CONF.keys())
    weights = [CATEGORY_CONF[c][0] for c in names]
    if repeat:
        # 复购订单：食品生鲜/美妆个护/家居日用等刚需品类权重放大
        weights = [w * REPEAT_CATEGORY_BOOST.get(c, 1.0) for c, w in zip(names, weights)]
    return random.choices(names, weights=weights)[0]


def make_amount(category, channel):
    """按品类基准价生成订单金额：对数正态扰动 x 渠道客单价系数。"""
    base = CATEGORY_CONF[category][1]
    coef = CHANNEL_CONF[channel]["客单价系数"]
    amount = base * np.random.lognormal(mean=0, sigma=0.45) * coef
    return round(float(np.clip(amount, AMOUNT_MIN, AMOUNT_MAX)), 2)


def make_pay_status(channel):
    """按渠道支付率生成支付状态：已支付 / 未支付 / 已取消。"""
    if random.random() < CHANNEL_CONF[channel]["支付率"]:
        return "已支付"
    # 未完成支付的订单中，进一步区分"未支付"（还在犹豫）与"已取消"（主动放弃）
    return "未支付" if random.random() < 0.75 else "已取消"


def make_order_time(reg_date):
    """生成下单时间：日期在[注册日, 统计截止日]内均匀分布，且 40% 集中在晚间 20-23 点（模拟晚间下单高峰）。"""
    span = (END_DATE - reg_date).days
    day = reg_date + timedelta(days=random.uniform(0, max(span, 1)))
    if random.random() < 0.40:
        hour = random.choice([20, 21, 22, 23])       # 晚间高峰时段
    else:
        hour = random.randint(8, 19)                 # 白天正常时段
    return day.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))


# ============================== 第一部分：模拟数据生成 ==============================
def generate_data():
    """生成带脏数据的模拟数据集：user_info.csv（5000条）+ order_info.csv（8000条）。

    数据中预设了以下"业务剧本"，保证后续分析能得出真实、可讲述的业务结论：
      1) 老带新渠道：下单率高、支付率高、复购倾向最高（质量最好的渠道）；
      2) 直播带货渠道：拉新多但下单率/支付率/客单价均偏低（冲动消费、承接差），
         且 2025 年起该渠道占比翻倍，导致新用户整体转化弱于老用户；
      3) 付费广告渠道：客单价最高但复购倾向低（"一锤子买卖"型用户）；
      4) 复购订单时间贴近首单（约45天指数衰减），形成"首单后30天黄金复购窗口"；
      5) 复购订单品类向食品生鲜/美妆个护/家居日用等刚需品类倾斜。
    """
    print(">>> [1/4] 正在生成模拟数据（用户5000条 + 订单8000条，含脏数据）...")

    # ---------- 1.1 生成用户表 ----------
    users = []
    for i in range(1, N_USERS + 1):
        user_id = f"U{i:05d}"
        reg_date = START_DATE + timedelta(seconds=random.randint(0, int((END_DATE - START_DATE).total_seconds())))
        # 渠道结构随时间漂移：2025 年起直播带货投放力度翻倍（制造新老用户结构差异）
        if reg_date >= NEW_USER_CUTOFF:
            w = {ch: CHANNEL_CONF[ch]["占比"] * (2.0 if ch == "直播带货" else 1.3 if ch == "老带新" else 1.0)
                 for ch in CHANNELS}
        else:
            w = {ch: CHANNEL_CONF[ch]["占比"] for ch in CHANNELS}
        channel = random.choices(list(w.keys()), weights=list(w.values()))[0]
        level = random.choices(LEVELS, weights=LEVEL_WEIGHTS)[0]
        # 是否复购用户：此处为占位随机值（并会注入脏数据），清洗阶段将根据订单数据重算覆盖
        is_repurchase = 1 if random.random() < 0.15 else 0
        users.append([user_id, reg_date.strftime("%Y-%m-%d"), level, channel, is_repurchase])
    user_df = pd.DataFrame(users, columns=["user_id", "注册时间", "用户等级", "注册渠道", "是否复购用户"])

    # ---------- 1.2 生成订单表 ----------
    # 每个用户按其渠道的"下单概率"决定是否产生首单
    user_df["_下单概率"] = user_df["注册渠道"].map(lambda ch: CHANNEL_CONF[ch]["下单概率"])
    buyer_mask = np.random.rand(len(user_df)) < user_df["_下单概率"]
    buyers = user_df[buyer_mask].copy()

    orders = []
    first_order_time = {}   # 记录每个用户的首单时间，用于生成"贴近首单"的复购订单
    for _, row in buyers.iterrows():
        t0 = make_order_time(pd.Timestamp(row["注册时间"]))
        first_order_time[row["user_id"]] = t0
        cat = pick_category(repeat=False)
        orders.append([f"O{len(orders) + 1:06d}", row["user_id"], t0, make_pay_status(row["注册渠道"]),
                       cat, make_amount(cat, row["注册渠道"]), 1 if random.random() < 0.50 else 0])

    # 复购订单：向高复购倾向用户集中（权重 = 渠道复购倾向 x 随机数），时间贴近首单
    extra_target = N_ORDERS - len(orders)
    tend = buyers["注册渠道"].map(lambda ch: CHANNEL_CONF[ch]["复购倾向"]).values
    weights = tend * np.random.rand(len(buyers))
    weights = weights / weights.sum()
    picks = np.random.choice(buyers["user_id"].values, size=extra_target, p=weights)
    channel_map = user_df.set_index("user_id")["注册渠道"]
    for uid in picks:
        ch = channel_map[uid]
        # 复购订单时间 = 首单时间 + 指数分布(均值45天)，模拟"首单后黄金复购窗口"
        t = first_order_time[uid] + timedelta(days=abs(np.random.exponential(45)))
        if t > END_DATE:  # 超出统计期则压缩至期末附近
            t = END_DATE - timedelta(days=random.uniform(0, 3))
        if t <= first_order_time[uid]:
            t = first_order_time[uid] + timedelta(hours=1)
        t = t.replace(hour=(random.choice([20, 21, 22, 23]) if random.random() < 0.4 else random.randint(8, 19)),
                      minute=random.randint(0, 59), second=random.randint(0, 59))
        cat = pick_category(repeat=True)
        orders.append([f"O{len(orders) + 1:06d}", uid, t, make_pay_status(ch),
                       cat, make_amount(cat, ch), 1 if random.random() < 0.50 else 0])

    order_df = pd.DataFrame(orders, columns=["order_id", "user_id", "下单时间", "支付状态",
                                             "商品品类", "订单金额", "加购标记"])
    order_df["下单时间"] = order_df["下单时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
    # 是否支付：与支付状态保持一致（已支付=1），后续清洗阶段以支付状态为准重算
    order_df["是否支付"] = (order_df["支付状态"] == "已支付").astype(int)

    # 孤儿订单：60 笔订单的 user_id 不在用户表中（模拟历史遗留/系统迁移产生的脏关联）
    orphans = []
    for k in range(60):
        t = make_order_time(START_DATE)
        cat = pick_category()
        status = make_pay_status("自然流量")
        orphans.append([f"O{len(order_df) + len(orphans) + 1:06d}", f"U9{k + 1:05d}",
                        t.strftime("%Y-%m-%d %H:%M:%S"), status,
                        cat, make_amount(cat, "自然流量"), 1 if random.random() < 0.5 else 0,
                        1 if status == "已支付" else 0])
    order_df = pd.concat([order_df, pd.DataFrame(orphans, columns=order_df.columns)], ignore_index=True)

    # ---------- 1.3 向订单表注入脏数据 ----------
    # 先记录 order_id -> user_id 映射（脏数据会破坏部分 user_id，之后按映射找回用户）
    oid2uid = order_df.set_index("order_id")["user_id"].to_dict()
    inject_order_dirty(order_df)

    # 加购标记保障（注入脏数据后重新执行）：每个用户至少 3 笔"加购"订单（不足3笔全部标记）。
    # 用于支撑"浏览 -> 加购 -> 下单 -> 支付"用户级漏斗的口径（加购用户 >= 下单用户），
    # 避免脏值覆盖/订单被清洗剔除后导致漏斗环节倒挂
    order_df["_uid"] = order_df["order_id"].str.upper().map(oid2uid)
    for uid, idx in order_df.groupby("_uid").groups.items():
        idx = list(idx)
        for j in random.sample(idx, min(3, len(idx))):
            order_df.loc[j, "加购标记"] = 1
    order_df.drop(columns=["_uid"], inplace=True)

    # ---------- 1.4 向用户表注入脏数据 ----------
    inject_user_dirty(user_df)
    user_df.drop(columns="_下单概率", inplace=True)

    # ---------- 1.5 追加完全重复行（模拟重复导入/重复下单记录） ----------
    order_df = pd.concat([order_df, order_df.sample(150, random_state=301)], ignore_index=True)
    user_df = pd.concat([user_df, user_df.sample(30, random_state=302)], ignore_index=True)

    # ---------- 1.6 保存原始数据 ----------
    order_df.to_csv(os.path.join(BASE_DIR, "order_info.csv"), index=False, encoding="utf-8-sig")
    user_df.to_csv(os.path.join(BASE_DIR, "user_info.csv"), index=False, encoding="utf-8-sig")
    print(f"    已生成 user_info.csv（{len(user_df)}条） / order_info.csv（{len(order_df)}条）")
    print("    已注入脏数据：缺失值 / 重复记录 / 金额异常 / 无效时间 / 格式不规范 / 孤儿订单")
    return user_df, order_df


def inject_order_dirty(df):
    """向订单表注入脏数据：缺失值、金额异常、无效时间、格式不规范。"""
    # 先统一转为 object 类型，便于注入字符串类脏值
    for col in ["加购标记", "是否支付", "支付状态", "下单时间", "user_id", "order_id"]:
        df[col] = df[col].astype(object)
    # (1) 关键字段缺失值
    df.loc[df.sample(70, random_state=101).index, "user_id"] = np.nan    # 用户ID缺失
    df.loc[df.sample(110, random_state=102).index, "订单金额"] = np.nan  # 金额缺失
    df.loc[df.sample(50, random_state=103).index, "下单时间"] = np.nan   # 时间缺失
    df.loc[df.sample(40, random_state=104).index, "支付状态"] = np.nan   # 支付状态缺失
    df.loc[df.sample(60, random_state=105).index, "加购标记"] = np.nan   # 加购标记缺失
    df.loc[df.sample(40, random_state=106).index, "是否支付"] = np.nan   # 是否支付缺失
    # (2) 金额异常：负数（退款误录/系统错误）、极端大值（测试数据）、0元单
    idx = df.sample(35, random_state=201).index
    df.loc[idx, "订单金额"] = -np.round(np.random.uniform(50, 800, len(idx)), 2)
    df.loc[df.sample(25, random_state=202).index, "订单金额"] = 99999.00
    df.loc[df.sample(15, random_state=203).index, "订单金额"] = 0.00
    # (3) 无效时间：不存在的日期 / 非时间字符串 / 越界数值
    bad_times = ["2024/13/45 25:61:00", "not_a_time", "2024-02-30 10:00:00", "20250632", "0000-00-00 00:00:00"]
    idx = df.sample(30, random_state=204).index
    df.loc[idx, "下单时间"] = np.random.choice(bad_times, len(idx))
    # (4) 时间格式不统一（合法但格式混乱，需要标准化）
    idx = df.sample(40, random_state=205).index
    df.loc[idx, "下单时间"] = pd.to_datetime(df.loc[idx, "下单时间"], errors="coerce").dt.strftime("%Y/%m/%d %H:%M:%S")
    # (5) 支付状态脏值：同一状态多种写法（大小写/英文/多空格/同义词）
    sub = df.index[df["支付状态"] == "已支付"]
    sub = df.loc[sub].sample(min(60, len(sub)), random_state=206).index
    df.loc[sub, "支付状态"] = np.random.choice(["paid", "SUCCESS ", "成功", "已付款"], len(sub))
    sub = df.index[df["支付状态"] == "未支付"]
    sub = df.loc[sub].sample(min(40, len(sub)), random_state=207).index
    df.loc[sub, "支付状态"] = np.random.choice(["未付款", "pending", "待支付"], len(sub))
    sub = df.index[df["支付状态"] == "已取消"]
    sub = df.loc[sub].sample(min(20, len(sub)), random_state=208).index
    df.loc[sub, "支付状态"] = np.random.choice(["cancel", "cancelled"], len(sub))
    # (6) 加购标记脏值：中文/字符串数字/空格
    idx = df.sample(90, random_state=209).index
    df.loc[idx, "加购标记"] = np.random.choice(["是", "否", "1", "0", " "], len(idx))
    # (7) 是否支付脏值：中文/字符型数字（后续按支付状态重算覆盖）
    idx = df.sample(40, random_state=210).index
    df.loc[idx, "是否支付"] = np.random.choice(["是", "否", "1"], len(idx))
    # (8) ID 格式不规范：小写 / 带前后空格
    sub = df.index[df["user_id"].notna()]
    sub = df.loc[sub].sample(min(50, len(sub)), random_state=211).index
    df.loc[sub, "user_id"] = " " + df.loc[sub, "user_id"].str.lower()
    sub = df.index[df["order_id"].notna()]
    sub = df.loc[sub].sample(min(30, len(sub)), random_state=212).index
    df.loc[sub, "order_id"] = df.loc[sub, "order_id"].str.lower()


def inject_user_dirty(df):
    """向用户表注入脏数据：缺失值、无效时间、渠道/等级脏值、格式不规范。"""
    for col in ["注册时间", "注册渠道", "用户等级", "是否复购用户"]:
        df[col] = df[col].astype(object)   # 转为 object 便于注入字符串脏值
    df.loc[df.sample(25, random_state=111).index, "注册时间"] = np.nan          # 注册时间缺失
    df.loc[df.sample(12, random_state=112).index, "注册时间"] = "2026-12-31"    # 未来时间（业务上不可能）
    df.loc[df.sample(8, random_state=113).index, "注册时间"] = "2024-13-01"     # 不存在的日期
    idx = df.sample(15, random_state=114).index                                 # 日期格式不统一
    df.loc[idx, "注册时间"] = pd.to_datetime(df.loc[idx, "注册时间"], errors="coerce").dt.strftime("%Y/%m/%d")
    df.loc[df.sample(45, random_state=115).index, "注册渠道"] = np.nan          # 渠道缺失
    idx = df.sample(30, random_state=116).index                                 # 渠道脏值/别名
    df.loc[idx, "注册渠道"] = np.random.choice(["社交媒体 ", "social", "直播", "社媒"], len(idx))
    df.loc[df.sample(35, random_state=117).index, "用户等级"] = np.nan          # 等级缺失
    df.loc[df.sample(15, random_state=118).index, "用户等级"] = np.random.choice(["vip", "黄金 ", "钻石"], 15)
    df.loc[df.sample(90, random_state=119).index, "是否复购用户"] = np.nan      # 复购标记缺失
    df.loc[df.sample(40, random_state=120).index, "是否复购用户"] = np.random.choice(["是", "否"], 40)


# ============================== 第二部分：数据清洗 ==============================
def clean_user_data(raw_path):
    """清洗用户表：去重、规范化、无效时间过滤、缺失值填充。

    清洗规则：
      1) 全字段去除首尾空格，user_id 统一大写，空字符串视为缺失；
      2) user_id 去重（重复导入产生完全重复行，保留首条）；
      3) 注册时间多格式解析，无法解析/未来时间（晚于统计截止日）视为无效并剔除；
      4) 注册渠道/用户等级规范化：别名归一，无法识别的统一填"未知"；
      5) 是否复购用户字段脏值较多，直接丢弃原值，改由订单数据重算（见 derive_user_features）。
    """
    print(">>> [2/4] 正在清洗用户表 user_info.csv ...")
    df = pd.read_csv(raw_path, dtype=str)
    log = []   # 清洗日志：(步骤, 处理行数, 说明)

    # 步骤1：去除首尾空格 + 空字符串转缺失 + user_id 统一大写
    for c in df.columns:
        df[c] = df[c].str.strip().replace("", np.nan)
    df["user_id"] = df["user_id"].str.upper()

    # 步骤2：按 user_id 去重（保留首次出现的记录）
    before = len(df)
    df = df.drop_duplicates(subset="user_id", keep="first")
    log.append(("用户表去重", before - len(df), "按user_id去重，保留首条"))

    # 步骤3：注册时间解析（多格式兼容），无效/未来时间剔除
    df["注册时间"] = df["注册时间"].apply(parse_time_safe)
    future_mask = df["注册时间"] > END_DATE          # 未来时间在业务上不可能存在
    df.loc[future_mask, "注册时间"] = pd.NaT
    before = len(df)
    df = df[df["注册时间"].notna()]
    log.append(("无效注册时间剔除", before - len(df), "无法解析或晚于统计截止日"))

    # 步骤4：注册渠道规范化（别名归一 + 非法值置空），缺失填"未知渠道"
    df["注册渠道"] = df["注册渠道"].replace({"social": "社交媒体", "社媒": "社交媒体", "直播": "直播带货"})
    df.loc[~df["注册渠道"].isin(CHANNELS), "注册渠道"] = np.nan
    n_unknown = int(df["注册渠道"].isna().sum())
    df["注册渠道"] = df["注册渠道"].fillna("未知渠道")
    log.append(("渠道缺失/脏值填充", n_unknown, "统一填充为'未知渠道'"))

    # 步骤5：用户等级规范化，缺失/非法值填"未知等级"
    df.loc[~df["用户等级"].isin(LEVELS), "用户等级"] = np.nan
    n_unknown = int(df["用户等级"].isna().sum())
    df["用户等级"] = df["用户等级"].fillna("未知等级")
    log.append(("等级缺失/脏值填充", n_unknown, "统一填充为'未知等级'"))

    # 步骤6：丢弃原始"是否复购用户"（脏值多），后续按订单重算
    df = df.drop(columns=["是否复购用户"])
    log.append(("复购标记重算准备", len(df), "丢弃原始脏值，改由订单数据重算"))

    df = df.reset_index(drop=True)
    return df, log


def clean_order_data(raw_path, user_df):
    """清洗订单表：去重、缺失值、金额异常、无效时间、孤儿订单、状态规范化。

    清洗规则：
      1) order_id 去重（保留首条）；user_id 缺失的订单无法归属用户，直接剔除；
      2) 下单时间多格式解析，解析失败或越界（早于平台上线/晚于截止日）的剔除；
      3) 订单金额转数值：缺失按品类中位数填充；<=0 或超出合理区间的剔除；
      4) 支付状态归一化（paid/成功/已付款 -> 已支付 等），缺失的按"是否支付"推断；
      5) 加购标记归一化（是/1 -> 1，否/0/空 -> 0）；是否支付按支付状态重算；
      6) 关联校验：剔除 user_id 不在用户表中的孤儿订单、下单时间早于注册时间的逻辑异常订单。
    """
    print(">>> [2/4] 正在清洗订单表 order_info.csv ...")
    df = pd.read_csv(raw_path, dtype=str)
    log = []

    # 步骤1：去空格 + 空串转缺失 + ID 统一大写
    for c in df.columns:
        df[c] = df[c].str.strip().replace("", np.nan)
    df["order_id"] = df["order_id"].str.upper()
    df["user_id"] = df["user_id"].str.upper()

    # 步骤2：按 order_id 去重
    before = len(df)
    df = df.drop_duplicates(subset="order_id", keep="first")
    log.append(("订单去重", before - len(df), "按order_id去重，保留首条"))

    # 步骤3：user_id 缺失的订单无法归属到用户，剔除
    before = len(df)
    df = df[df["user_id"].notna()]
    log.append(("用户ID缺失剔除", before - len(df), "无法归属用户，直接剔除"))

    # 步骤4：下单时间解析与越界过滤
    df["下单时间"] = df["下单时间"].apply(parse_time_safe)
    out_range = (df["下单时间"] < START_DATE) | (df["下单时间"] > END_DATE)
    df.loc[out_range, "下单时间"] = pd.NaT
    before = len(df)
    df = df[df["下单时间"].notna()]
    log.append(("无效下单时间剔除", before - len(df), "解析失败或超出统计期"))

    # 步骤5：金额缺失 -> 按品类中位数填充（保留订单，减少信息损失）
    df["订单金额"] = pd.to_numeric(df["订单金额"], errors="coerce")
    n_missing = int(df["订单金额"].isna().sum())
    med = df[df["订单金额"].between(AMOUNT_MIN, AMOUNT_MAX)].groupby("商品品类")["订单金额"].median()
    df["订单金额"] = df["订单金额"].fillna(df["商品品类"].map(med))
    log.append(("金额缺失填充", n_missing, "按同品类订单金额中位数填充"))

    # 步骤6：金额异常（<=0 或超出合理区间）剔除
    before = len(df)
    df = df[df["订单金额"].between(AMOUNT_MIN, AMOUNT_MAX)]
    log.append(("金额异常剔除", before - len(df), f"剔除金额<={AMOUNT_MIN - 1}或>{AMOUNT_MAX}的异常订单"))

    # 步骤7：支付状态归一化（大小写/英文/同义词统一为三种标准状态）
    status_map = {"已支付": "已支付", "未支付": "未支付", "已取消": "已取消",
                  "paid": "已支付", "success": "已支付", "成功": "已支付", "已付款": "已支付",
                  "未付款": "未支付", "pending": "未支付", "待支付": "未支付",
                  "cancel": "已取消", "cancelled": "已取消", "退款": "已取消"}
    df["支付状态"] = df["支付状态"].str.lower().map(status_map)
    # 缺失的支付状态：用"是否支付"字段推断；两者都缺失时按"未支付"保守处理
    n_infer = int(df["支付状态"].isna().sum())
    mask = df["支付状态"].isna()
    df.loc[mask & (df["是否支付"] == "1"), "支付状态"] = "已支付"
    df.loc[df["支付状态"].isna(), "支付状态"] = "未支付"
    log.append(("支付状态归一/填充", n_infer, "英文/同义词归一，缺失按是否支付推断"))

    # 步骤8：加购标记归一化（是/1 -> 1，否/0/空 -> 0）
    cart_map = {"是": 1, "1": 1, "true": 1, "否": 0, "0": 0, "false": 0}
    df["加购标记"] = df["加购标记"].str.lower().map(cart_map)
    n_cart_fill = int(df["加购标记"].isna().sum())
    df["加购标记"] = df["加购标记"].fillna(0).astype(int)
    log.append(("加购标记归一/填充", n_cart_fill, "中文/字符串归一，缺失按0处理"))

    # 步骤9：是否支付按支付状态重算（修复原字段脏值与逻辑不一致）
    df["是否支付"] = (df["支付状态"] == "已支付").astype(int)
    log.append(("是否支付重算", len(df), "以支付状态为准：已支付=1，其余=0"))

    # 步骤10：关联校验——剔除不在用户表中的孤儿订单
    before = len(df)
    df = df[df["user_id"].isin(set(user_df["user_id"]))]
    log.append(("孤儿订单剔除", before - len(df), "user_id不在用户表中"))

    # 步骤11：逻辑校验——下单时间早于注册时间的订单剔除
    reg_map = user_df.set_index("user_id")["注册时间"]
    before = len(df)
    df = df[df["下单时间"] >= df["user_id"].map(reg_map)]
    log.append(("时间逻辑异常剔除", before - len(df), "下单时间早于注册时间"))

    # 步骤12：衍生时间字段——下单月份/小时（用于趋势与时段分析）
    df["下单月份"] = df["下单时间"].dt.strftime("%Y-%m")
    df["下单小时"] = df["下单时间"].dt.hour
    # 是否首单：同一用户最早的一笔订单标记为1
    first_time = df.groupby("user_id")["下单时间"].transform("min")
    df["是否首单"] = (df["下单时间"] == first_time).astype(int)

    df = df.sort_values("下单时间").reset_index(drop=True)
    return df, log


def derive_user_features(user_df, order_df):
    """基于清洗后订单数据，为用户表衍生业务指标字段。

    衍生字段：
      是否下单     —— 统计期内是否产生过订单（识别"注册未下单"的低活跃用户）
      首次下单时间 —— 用于新用户留存/新老用户相关分析
      是否复购用户 —— 已支付订单数 >= 2 视为复购用户（重算覆盖原始脏值）
      累计支付金额 —— 统计期内已支付订单金额合计
      消费分层     —— 未下单用户 / 下单未支付 / 低消费 / 中消费 / 高消费
                      （有支付行为的用户按累计支付金额的 30%/70% 分位数划分）
    """
    paid = order_df[order_df["是否支付"] == 1]
    # 每个用户的支付订单数与支付金额
    stat = paid.groupby("user_id").agg(支付订单数=("order_id", "count"),
                                       累计支付金额=("订单金额", "sum")).reset_index()
    # 首次下单时间（含未支付订单，反映"有过下单意向"的时间）
    first_order = order_df.groupby("user_id")["下单时间"].min().rename("首次下单时间")

    user_df = user_df.merge(stat, on="user_id", how="left").merge(first_order, on="user_id", how="left")
    user_df["支付订单数"] = user_df["支付订单数"].fillna(0).astype(int)
    user_df["累计支付金额"] = user_df["累计支付金额"].fillna(0).round(2)
    user_df["是否下单"] = user_df["首次下单时间"].notna().astype(int)
    # 复购用户：已支付订单数 >= 2（口径：按支付口径统计，剔除下单未支付的干扰）
    user_df["是否复购用户"] = (user_df["支付订单数"] >= 2).astype(int)

    # 消费分层：有支付行为的用户按分位数划分三档，未下单/下单未支付单独标识
    payer_mask = user_df["支付订单数"] >= 1
    q30 = user_df.loc[payer_mask, "累计支付金额"].quantile(0.30)
    q70 = user_df.loc[payer_mask, "累计支付金额"].quantile(0.70)
    user_df["消费分层"] = np.select(
        [user_df["是否下单"] == 0,
         ~payer_mask,
         user_df["累计支付金额"] <= q30,
         user_df["累计支付金额"] <= q70],
        ["未下单用户", "下单未支付", "低消费", "中消费"], default="高消费")

    # 时间列格式化为字符串，便于 csv 存储与 Streamlit 读取
    user_df["注册时间"] = user_df["注册时间"].dt.strftime("%Y-%m-%d")
    user_df["首次下单时间"] = user_df["首次下单时间"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return user_df[["user_id", "注册时间", "用户等级", "注册渠道", "是否复购用户",
                    "是否下单", "首次下单时间", "累计支付金额", "消费分层"]]


# ============================== 第三部分：业务分析 ==============================
def build_group_stats(user_df, order_df, group_col):
    """通用分组统计：按指定维度（渠道/新老用户/消费分层等）对比转化与复购表现。

    输出指标：
      下单转化率 = 下单用户数 / 用户数          （拉新 -> 首单的能力）
      支付转化率 = 支付用户数 / 下单用户数      （下单 -> 支付的承接能力）
      复购率     = 复购用户数 / 支付用户数      （老用户粘性）
      客单价     = GMV / 支付用户数             （用户消费力，人数口径）
    """
    paid = order_df[order_df["是否支付"] == 1]
    stat = order_df.groupby("user_id").agg(订单数=("order_id", "count")).reset_index()
    pstat = paid.groupby("user_id").agg(支付订单数=("order_id", "count"),
                                        支付金额=("订单金额", "sum")).reset_index()
    stat = stat.merge(pstat, on="user_id", how="left")
    stat[["支付订单数", "支付金额"]] = stat[["支付订单数", "支付金额"]].fillna(0)

    m = user_df[["user_id", group_col]].merge(stat, on="user_id", how="left")
    m[["订单数", "支付订单数", "支付金额"]] = m[["订单数", "支付订单数", "支付金额"]].fillna(0)

    g = m.groupby(group_col).agg(
        用户数=("user_id", "nunique"),
        下单用户数=("订单数", lambda s: int((s > 0).sum())),
        总订单量=("订单数", "sum"),
        支付用户数=("支付订单数", lambda s: int((s > 0).sum())),
        复购用户数=("支付订单数", lambda s: int((s >= 2).sum())),
        GMV=("支付金额", "sum"),
    ).reset_index()
    g["下单转化率"] = (g["下单用户数"] / g["用户数"]).round(4)
    g["支付转化率"] = (g["支付用户数"] / g["下单用户数"]).round(4)
    g["复购率"] = (g["复购用户数"] / g["支付用户数"]).round(4)
    g["客单价"] = (g["GMV"] / g["支付用户数"]).round(2)
    return g.sort_values("GMV", ascending=False).reset_index(drop=True)


def calc_core_metrics(user_df, order_df):
    """核心指标：GMV、总订单量、支付转化率、客单价、复购率、新用户30天留存率。"""
    total_users = user_df["user_id"].nunique()          # 注册用户数
    order_users = order_df["user_id"].nunique()         # 下单用户数
    paid = order_df[order_df["是否支付"] == 1]
    paid_users = paid["user_id"].nunique()              # 支付用户数
    gmv = paid["订单金额"].sum()                        # GMV：已支付订单金额合计
    repurchase_users = int((paid.groupby("user_id").size() >= 2).sum())  # 复购用户数
    retention = calc_retention(order_df)[0]             # 新用户30天留存率（整体）

    rows = [
        ("注册用户数", total_users, "清洗后用户表全量"),
        ("GMV(元)", round(gmv, 2), "统计期内已支付订单金额合计"),
        ("总订单量", len(order_df), "清洗后全部订单"),
        ("支付订单量", len(paid), "支付状态=已支付"),
        ("支付转化率(订单级)", f"{len(paid) / len(order_df):.2%}", "支付订单量 / 总订单量"),
        ("下单用户数", order_users, "产生过订单的去重用户"),
        ("支付用户数", paid_users, "完成过支付的去重用户"),
        ("下单转化率(用户级)", f"{order_users / total_users:.2%}", "下单用户 / 注册用户"),
        ("支付转化率(用户级)", f"{paid_users / order_users:.2%}", "支付用户 / 下单用户"),
        ("客单价(元)", round(gmv / paid_users, 2), "GMV / 支付用户数（人数口径）"),
        ("笔单价(元)", round(gmv / len(paid), 2), "GMV / 支付订单量（订单口径）"),
        ("复购率", f"{repurchase_users / paid_users:.2%}", "支付订单数>=2的用户 / 支付用户数"),
        ("新用户30天留存率", f"{retention:.2%}", "首单后30天内再次支付的用户占比"),
    ]
    return pd.DataFrame(rows, columns=["指标", "数值", "口径说明"])


def calc_retention(order_df):
    """新用户留存：以"首次支付"为起点，统计30天内再次支付的用户比例（按首单月份分组）。"""
    paid = order_df[order_df["是否支付"] == 1][["user_id", "下单时间"]]
    first = paid.groupby("user_id")["下单时间"].min().rename("首单时间")
    j = paid.merge(first, on="user_id")
    j["间隔天数"] = (j["下单时间"] - j["首单时间"]).dt.days

    # 整体30天复购留存率
    retained_users = j[(j["间隔天数"] > 0) & (j["间隔天数"] <= 30)]["user_id"].nunique()
    overall = retained_users / first.shape[0]

    # 按首单月份分组的留存表（注意：最后一个月存在观察期不足30天的截尾问题）
    j["首单月份"] = j["首单时间"].dt.strftime("%Y-%m")
    first_users = j.drop_duplicates("user_id").groupby("首单月份")["user_id"].nunique().rename("首单用户数")
    retained = j[(j["间隔天数"] > 0) & (j["间隔天数"] <= 30)].groupby("首单月份")["user_id"].nunique().rename("30天复购用户")
    cohort = pd.concat([first_users, retained], axis=1).fillna(0).astype(int)
    cohort["30天复购留存率"] = (cohort["30天复购用户"] / cohort["首单用户数"]).round(4)
    cohort = cohort.reset_index()
    return overall, cohort


def calc_funnel(user_df, order_df):
    """转化漏斗（用户级）：浏览商品 -> 加入购物车 -> 提交订单 -> 完成支付。

    口径说明：
      浏览商品 = 全部注册用户（数据集未含独立浏览日志，以"注册即访问"近似）；
      加入购物车 = 存在加购标记=1订单的用户；
      提交订单   = 产生过订单的用户；
      完成支付   = 完成过支付的用户。
      注：加购行为挂在订单上（无"加购未下单"的行为日志），因此加购->下单转化率接近100%，
          该环节的真实流失需接入行为埋点数据才能度量。
    """
    stage_users = order_df["user_id"].nunique()                                   # 提交订单
    cart_users = order_df.loc[order_df["加购标记"] == 1, "user_id"].nunique()     # 加入购物车
    paid_users = order_df.loc[order_df["是否支付"] == 1, "user_id"].nunique()     # 完成支付
    browse_users = user_df["user_id"].nunique()                                   # 浏览商品（近似）

    stages = ["浏览商品(注册用户近似)", "加入购物车", "提交订单", "完成支付"]
    values = [browse_users, cart_users, stage_users, paid_users]
    rows = []
    for i, (name, v) in enumerate(zip(stages, values)):
        rows.append((name, v,
                     f"{v / values[0]:.2%}",
                     "-" if i == 0 else f"{v / values[i - 1]:.2%}"))
    return pd.DataFrame(rows, columns=["环节", "人数", "整体转化率", "环节转化率"])


def calc_category_stats(order_df):
    """品类分析：各品类销售额、订单量、占比、支付转化率与笔单价。"""
    g = order_df.groupby("商品品类").agg(订单量=("order_id", "count"),
                                        支付订单量=("是否支付", "sum"))
    paid_amt = order_df[order_df["是否支付"] == 1].groupby("商品品类")["订单金额"].sum().rename("销售额")
    g = g.join(paid_amt).sort_values("销售额", ascending=False)
    g["销售额占比"] = (g["销售额"] / g["销售额"].sum()).round(4)
    g["支付转化率"] = (g["支付订单量"] / g["订单量"]).round(4)
    g["笔单价"] = (g["销售额"] / g["支付订单量"]).round(2)
    return g.reset_index()


def calc_repurchase_profile(user_df, order_df):
    """高复购用户画像：对比复购/非复购用户的消费力、品类偏好与渠道分布。"""
    paid = order_df[order_df["是否支付"] == 1]
    per_user = paid.groupby("user_id").agg(支付订单数=("order_id", "count"),
                                           支付金额=("订单金额", "sum"))
    per_user["用户类型"] = np.where(per_user["支付订单数"] >= 2, "复购用户", "非复购用户")

    # 1) 消费力对比
    m = per_user.groupby("用户类型").agg(用户数=("支付订单数", "size"),
                                        人均支付订单数=("支付订单数", "mean"),
                                        人均支付金额=("支付金额", "mean")).round(2).reset_index()

    # 2) 品类偏好：两类用户的支付订单品类结构占比
    j = paid.merge(per_user["用户类型"], left_on="user_id", right_index=True)
    cat = j.groupby(["用户类型", "商品品类"]).size().rename("订单数").reset_index()
    cat["占比"] = cat.groupby("用户类型")["订单数"].transform(lambda s: s / s.sum())
    cat_pivot = cat.pivot(index="商品品类", columns="用户类型", values="占比").fillna(0).round(4)
    cat_pivot["占比差异(复购-非复购)"] = (cat_pivot.get("复购用户", 0) - cat_pivot.get("非复购用户", 0)).round(4)

    # 3) 渠道分布：两类用户的注册渠道结构占比
    ch = j.drop_duplicates("user_id")[["user_id", "用户类型"]].merge(
        user_df[["user_id", "注册渠道"]], on="user_id")
    ch_share = ch.groupby(["用户类型", "注册渠道"]).size().rename("人数").reset_index()
    ch_share["占比"] = ch_share.groupby("用户类型")["人数"].transform(lambda s: s / s.sum())
    ch_pivot = ch_share.pivot(index="注册渠道", columns="用户类型", values="占比").fillna(0).round(4)

    return m, cat_pivot.sort_values("占比差异(复购-非复购)", ascending=False), ch_pivot


def calc_low_conversion(user_df, order_df):
    """低转化用户画像：定位"注册未下单"与"下单未支付"两类流失用户的渠道分布。"""
    orderers = set(order_df["user_id"])
    payers = set(order_df.loc[order_df["是否支付"] == 1, "user_id"])

    g = user_df.groupby("注册渠道").agg(用户数=("user_id", "nunique")).reset_index()
    # 注册未下单：从未产生任何订单的用户
    g["注册未下单用户"] = g["注册渠道"].map(
        user_df[~user_df["user_id"].isin(orderers)].groupby("注册渠道")["user_id"].nunique()).fillna(0).astype(int)
    g["注册未下单率"] = (g["注册未下单用户"] / g["用户数"]).round(4)
    # 下单未支付：有订单但从未完成支付的用户
    g["下单未支付用户"] = g["注册渠道"].map(
        user_df[user_df["user_id"].isin(orderers) & ~user_df["user_id"].isin(payers)]
        .groupby("注册渠道")["user_id"].nunique()).fillna(0).astype(int)
    g["下单未支付率"] = (g["下单未支付用户"] / (g["用户数"] - g["注册未下单用户"])).round(4)
    return g.sort_values("注册未下单率", ascending=False).reset_index(drop=True)


# ============================== 第四部分：可视化 ==============================
def plot_funnel(funnel_df, path):
    """绘制用户转化漏斗图（居中梯形样式，标注人数与各环节转化率）。"""
    stages = funnel_df["环节"].tolist()
    values = funnel_df["人数"].tolist()
    n = len(stages)
    fig, ax = plt.subplots(figsize=(10, 5.8))
    colors = sns.color_palette("Blues", n)[::-1]   # 由深到浅
    max_v = values[0]
    for i, (name, v) in enumerate(zip(stages, values)):
        y = n - 1 - i
        w = v / max_v
        ax.barh(y, w, left=(1 - w) / 2, height=0.62, color=colors[i], edgecolor="white")
        ax.text(0.5, y, f"{name}  {v:,}人（{v / values[0]:.1%}）", ha="center", va="center",
                fontsize=11.5, fontweight="bold", color="white" if i < 2 else "#1a3a5c")
        if i > 0:   # 右侧标注环节转化率
            ax.text(1.01, y + 0.5, f"环节转化率 {v / values[i - 1]:.1%}",
                    fontsize=9.5, color="#c0392b", va="center")
    ax.set_xlim(0, 1.18)
    ax.set_ylim(-0.55, n - 0.45)
    ax.axis("off")
    ax.set_title("用户转化漏斗：浏览 -> 加购 -> 下单 -> 支付", fontsize=14, pad=14)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_channel_conversion(channel_df, path):
    """绘制各注册渠道的下单转化率/支付转化率/复购率对比柱状图。"""
    melt = channel_df.melt(id_vars="注册渠道",
                           value_vars=["下单转化率", "支付转化率", "复购率"],
                           var_name="指标", value_name="比率")
    melt["比率"] = melt["比率"] * 100   # 转为百分比便于标注
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bar = sns.barplot(data=melt, x="注册渠道", y="比率", hue="指标",
                      palette="Set2", ax=ax)
    for container in bar.containers:   # 柱顶标注数值
        ax.bar_label(container, fmt="%.1f%%", fontsize=8.5, padding=2)
    ax.set_title("各注册渠道转化与复购表现对比", fontsize=14, pad=12)
    ax.set_xlabel("注册渠道")
    ax.set_ylabel("比率(%)")
    ax.legend(title="指标")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_category_pie(category_df, path):
    """绘制品类销售额占比环形饼图。"""
    fig, ax = plt.subplots(figsize=(8.5, 8))
    colors = sns.color_palette("pastel", len(category_df))
    wedges, texts, autotexts = ax.pie(
        category_df["销售额"], labels=category_df["商品品类"],
        autopct="%1.1f%%", startangle=90, counterclock=False,
        colors=colors, pctdistance=0.78,
        wedgeprops=dict(width=0.42, edgecolor="white"),   # 环形样式
        textprops=dict(fontsize=10.5))
    for t in autotexts:   # 百分比文字加深颜色提高可读性
        t.set_color("#333333")
        t.set_fontsize(9.5)
    ax.text(0, 0, f"总销售额\n{category_df['销售额'].sum():,.0f} 元",
            ha="center", va="center", fontsize=13, fontweight="bold", color="#2c3e50")
    ax.set_title("各品类销售额占比（支付口径）", fontsize=14, pad=16)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_repurchase_profile(profile_m, cat_pivot, ch_pivot, path):
    """绘制复购用户画像：消费力对比 + 品类偏好 + 渠道结构。"""
    fig, axes = plt.subplots(1, 3, figsize=(17, 5))
    order = ["复购用户", "非复购用户"]

    # 子图1：人均支付金额对比
    m = profile_m.set_index("用户类型").reindex(order)
    bars = axes[0].bar(order, m["人均支付金额"], color=["#e67e22", "#95a5a6"], width=0.5)
    for b, v in zip(bars, m["人均支付金额"]):
        axes[0].text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f} 元",
                     ha="center", va="bottom", fontsize=11, fontweight="bold")
    axes[0].set_title("人均支付金额对比", fontsize=12.5)
    axes[0].set_ylabel("人均支付金额(元)")

    # 子图2：品类偏好对比（支付订单结构占比前6品类）
    top6 = cat_pivot["占比差异(复购-非复购)"].abs().sort_values(ascending=False).head(6).index
    x = np.arange(len(top6))
    v1 = cat_pivot.loc[top6, "复购用户"].values * 100 if "复购用户" in cat_pivot else np.zeros(len(top6))
    v2 = cat_pivot.loc[top6, "非复购用户"].values * 100 if "非复购用户" in cat_pivot else np.zeros(len(top6))
    axes[1].bar(x - 0.18, v1, width=0.36, label="复购用户", color="#e67e22")
    axes[1].bar(x + 0.18, v2, width=0.36, label="非复购用户", color="#95a5a6")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(top6, rotation=30, ha="right")
    axes[1].set_title("支付订单品类结构对比(Top6)", fontsize=12.5)
    axes[1].set_ylabel("订单结构占比(%)")
    axes[1].legend(fontsize=9)

    # 子图3：注册渠道结构对比
    chans = ch_pivot.index.tolist()
    x = np.arange(len(chans))
    c1 = ch_pivot["复购用户"].values * 100 if "复购用户" in ch_pivot else np.zeros(len(chans))
    c2 = ch_pivot["非复购用户"].values * 100 if "非复购用户" in ch_pivot else np.zeros(len(chans))
    axes[2].bar(x - 0.18, c1, width=0.36, label="复购用户", color="#e67e22")
    axes[2].bar(x + 0.18, c2, width=0.36, label="非复购用户", color="#95a5a6")
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(chans, rotation=30, ha="right")
    axes[2].set_title("注册渠道结构对比", fontsize=12.5)
    axes[2].set_ylabel("用户结构占比(%)")
    axes[2].legend(fontsize=9)

    fig.suptitle("复购用户 vs 非复购用户画像对比", fontsize=15, y=1.02)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_monthly_trend(order_df, path):
    """绘制月度GMV趋势（柱）与订单量趋势（线）组合图。"""
    paid = order_df[order_df["是否支付"] == 1]
    monthly = order_df.groupby("下单月份").agg(订单量=("order_id", "count"))
    monthly["GMV"] = paid.groupby("下单月份")["订单金额"].sum()
    monthly = monthly.sort_index()

    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.bar(monthly.index, monthly["GMV"], color="#5b9bd5", alpha=0.8, label="GMV")
    ax1.set_ylabel("GMV(元)")
    ax1.set_xlabel("月份")
    ax1.tick_params(axis="x", rotation=45)
    ax2 = ax1.twinx()
    ax2.plot(monthly.index, monthly["订单量"], color="#ed7d31", marker="o", linewidth=2, label="订单量")
    ax2.set_ylabel("订单量(笔)")
    # 合并双轴图例
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)
    ax1.set_title("月度GMV与订单量趋势", fontsize=14, pad=12)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ============================== 主流程 ==============================
def main():
    print("=" * 70)
    print("电商平台用户与订单综合数据分析 —— 开始运行")
    print("=" * 70)

    # ---------- 第一部分：生成模拟数据 ----------
    generate_data()

    # ---------- 第二部分：数据清洗 ----------
    user_raw_path = os.path.join(BASE_DIR, "user_info.csv")
    order_raw_path = os.path.join(BASE_DIR, "order_info.csv")
    clean_user, user_log = clean_user_data(user_raw_path)
    clean_order, order_log = clean_order_data(order_raw_path, clean_user)
    clean_user = derive_user_features(clean_user, clean_order)

    # 打印清洗日志并保存
    clean_log = pd.DataFrame(user_log + order_log, columns=["清洗步骤", "处理行数", "规则说明"])
    print("\n----- 数据清洗日志 -----")
    print(clean_log.to_string(index=False))
    print(f"清洗后用户表：{len(clean_user)}条 | 清洗后订单表：{len(clean_order)}条")
    clean_log.to_csv(os.path.join(TABLE_DIR, "clean_log.csv"), index=False, encoding="utf-8-sig")

    # 保存清洗后数据（utf-8-sig 编码，Excel 打开不乱码）
    clean_user.to_csv(os.path.join(BASE_DIR, "clean_user.csv"), index=False, encoding="utf-8-sig")
    clean_order.to_csv(os.path.join(BASE_DIR, "clean_order.csv"), index=False, encoding="utf-8-sig")

    # ---------- 第三部分：业务分析 ----------
    print("\n>>> [3/4] 正在进行业务分析 ...")

    # 3.1 核心指标
    core = calc_core_metrics(clean_user, clean_order)
    core.to_csv(os.path.join(TABLE_DIR, "core_metrics.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 核心指标 -----")
    print(core.to_string(index=False))

    # 3.2 转化漏斗
    funnel = calc_funnel(clean_user, clean_order)
    funnel.to_csv(os.path.join(TABLE_DIR, "funnel.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 转化漏斗（用户级） -----")
    print(funnel.to_string(index=False))

    # 3.3 渠道分群
    channel = build_group_stats(clean_user, clean_order, "注册渠道")
    channel.to_csv(os.path.join(TABLE_DIR, "channel_stats.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 分群分析：注册渠道 -----")
    print(channel.to_string(index=False))

    # 3.4 新老用户对比（2025年起注册视为新用户）
    clean_user["用户分层"] = np.where(pd.to_datetime(clean_user["注册时间"]) >= NEW_USER_CUTOFF,
                                     "新用户(2025年注册)", "老用户(2024年注册)")
    cohort = build_group_stats(clean_user, clean_order, "用户分层")
    cohort.to_csv(os.path.join(TABLE_DIR, "cohort_stats.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 分群分析：新老用户 -----")
    print(cohort.to_string(index=False))

    # 3.5 消费分层对比
    consume = build_group_stats(clean_user, clean_order, "消费分层")
    consume.to_csv(os.path.join(TABLE_DIR, "consume_stats.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 分群分析：消费分层 -----")
    print(consume.to_string(index=False))

    # 3.6 新用户30天留存（按首单月份）
    retention_overall, retention_month = calc_retention(clean_order)
    retention_month.to_csv(os.path.join(TABLE_DIR, "retention_by_month.csv"), index=False, encoding="utf-8-sig")
    print(f"\n----- 新用户30天留存率（整体 {retention_overall:.2%}，按首单月份） -----")
    print(retention_month.to_string(index=False))

    # 3.7 品类分析
    category = calc_category_stats(clean_order)
    category.to_csv(os.path.join(TABLE_DIR, "category_stats.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 品类分析 -----")
    print(category.to_string(index=False))

    # 3.8 复购用户画像
    profile, cat_pivot, ch_pivot = calc_repurchase_profile(clean_user, clean_order)
    profile.to_csv(os.path.join(TABLE_DIR, "repurchase_profile.csv"), index=False, encoding="utf-8-sig")
    cat_pivot.to_csv(os.path.join(TABLE_DIR, "repurchase_category.csv"), encoding="utf-8-sig")
    ch_pivot.to_csv(os.path.join(TABLE_DIR, "repurchase_channel.csv"), encoding="utf-8-sig")
    print("\n----- 复购用户画像：消费力对比 -----")
    print(profile.to_string(index=False))
    print("\n----- 复购用户画像：品类偏好差异（Top5） -----")
    print(cat_pivot.head(5).to_string())

    # 3.9 低转化用户画像
    low_conv = calc_low_conversion(clean_user, clean_order)
    low_conv.to_csv(os.path.join(TABLE_DIR, "low_conversion.csv"), index=False, encoding="utf-8-sig")
    print("\n----- 低转化用户画像 -----")
    print(low_conv.to_string(index=False))

    # ---------- 第四部分：可视化 ----------
    print("\n>>> [4/4] 正在生成可视化图表 ...")
    plot_funnel(funnel, os.path.join(CHART_DIR, "01_转化漏斗图.png"))
    plot_channel_conversion(channel, os.path.join(CHART_DIR, "02_渠道转化对比图.png"))
    plot_category_pie(category, os.path.join(CHART_DIR, "03_品类销售额占比图.png"))
    plot_repurchase_profile(profile, cat_pivot, ch_pivot, os.path.join(CHART_DIR, "04_复购用户画像图.png"))
    plot_monthly_trend(clean_order, os.path.join(CHART_DIR, "05_月度GMV趋势图.png"))
    print(f"    已输出 5 张图表至 output/charts/")

    # ---------- 核心结论摘要 ----------
    print("\n" + "=" * 70)
    print("核心结论摘要（详见 analysis_report.md）")
    print("=" * 70)
    best_ch = channel.loc[channel["下单转化率"].idxmax()]
    worst_ch = channel.loc[channel["下单转化率"].idxmin()]
    top_cat = category.iloc[0]
    print(f"1. GMV {core.iloc[1]['数值']:,.0f} 元，支付转化率(订单级) {core.iloc[4]['数值']}，"
          f"客单价 {core.iloc[9]['数值']} 元，复购率 {core.iloc[11]['数值']}")
    print(f"2. 渠道：[{best_ch['注册渠道']}]下单转化率最高({best_ch['下单转化率']:.1%})；"
          f"[{worst_ch['注册渠道']}]最低({worst_ch['下单转化率']:.1%})且支付/复购均偏弱")
    print(f"3. 品类：[{top_cat['商品品类']}]销售额居首({top_cat['销售额占比']:.1%})，"
          f"头部品类集中度高")
    print(f"4. 新用户30天留存率 {retention_overall:.1%}，首单后30天是复购黄金窗口")
    print("全部流程运行完成！")


if __name__ == "__main__":
    main()
