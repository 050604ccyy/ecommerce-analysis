-- ============================================================================
-- 电商平台用户与订单综合数据分析 —— MySQL 分析脚本
-- ----------------------------------------------------------------------------
-- 运行环境 : MySQL 8.0+（使用了 CTE / 窗口函数）
-- 数据来源 : data_process.py 清洗输出的 clean_user.csv / clean_order.csv
-- 使用步骤 : 依次执行 第一节(建库建表) -> 第二节(导入数据) -> 第三~十节分析查询
-- 口径约定 : GMV 只统计"已支付"订单；复购用户 = 已支付订单数 >= 2 的用户；
--            客单价 = GMV / 支付用户数；支付转化率 = 支付订单量 / 总订单量
-- ============================================================================

-- ============================================================================
-- 一、建库建表
-- ============================================================================
CREATE DATABASE IF NOT EXISTS ecommerce_analysis DEFAULT CHARACTER SET utf8mb4;
USE ecommerce_analysis;

-- 用户表（清洗后，含衍生字段）
DROP TABLE IF EXISTS user_info;
CREATE TABLE user_info (
    user_id          VARCHAR(20)   NOT NULL COMMENT '用户ID',
    register_date    DATE          NULL     COMMENT '注册时间',
    user_level       VARCHAR(20)   NULL     COMMENT '用户等级',
    register_channel VARCHAR(30)   NULL     COMMENT '注册渠道',
    is_repurchase    TINYINT       NULL     COMMENT '是否复购用户(1是/0否，支付订单数>=2)',
    is_ordered       TINYINT       NULL     COMMENT '是否下单(1是/0否)',
    first_order_time DATETIME      NULL     COMMENT '首次下单时间',
    total_paid       DECIMAL(12,2) NULL     COMMENT '累计支付金额',
    consume_level    VARCHAR(20)   NULL     COMMENT '消费分层',
    PRIMARY KEY (user_id),
    KEY idx_channel (register_channel),
    KEY idx_regdate (register_date)
) ENGINE = InnoDB COMMENT = '电商用户表(清洗后)';

-- 订单表（清洗后，含衍生时间字段）
DROP TABLE IF EXISTS order_info;
CREATE TABLE order_info (
    order_id       VARCHAR(20)   NOT NULL COMMENT '订单ID',
    user_id        VARCHAR(20)   NULL     COMMENT '用户ID',
    order_time     DATETIME      NULL     COMMENT '下单时间',
    pay_status     VARCHAR(10)   NULL     COMMENT '支付状态：已支付/未支付/已取消',
    category       VARCHAR(20)   NULL     COMMENT '商品品类',
    amount         DECIMAL(12,2) NULL     COMMENT '订单金额',
    cart_flag      TINYINT       NULL     COMMENT '加购标记(1是/0否)',
    is_paid        TINYINT       NULL     COMMENT '是否支付(1是/0否)',
    order_month    VARCHAR(7)    NULL     COMMENT '下单月份YYYY-MM',
    order_hour     INT           NULL     COMMENT '下单小时(0-23)',
    is_first_order TINYINT       NULL     COMMENT '是否该用户首单(1是/0否)',
    PRIMARY KEY (order_id),
    KEY idx_user (user_id),
    KEY idx_time (order_time),
    KEY idx_category (category)
) ENGINE = InnoDB COMMENT = '电商订单表(清洗后)';

-- ============================================================================
-- 二、导入数据
-- 说明：① 路径按本地实际位置修改（Windows 下用正斜杠）；
--       ② 需开启 local_infile：SET GLOBAL local_infile = 1;
--       ③ 客户端连接时加 --local-infile=1 参数；
--       ④ IGNORE 1 LINES 跳过 CSV 表头。
-- ============================================================================
-- LOAD DATA LOCAL INFILE 'D:/easyagent/ecommerce_analysis/clean_user.csv'
-- INTO TABLE user_info
-- CHARACTER SET utf8mb4
-- FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
-- IGNORE 1 LINES
-- (user_id, @reg_date, user_level, register_channel, @rep, @ordered,
--  @first_order, @total_paid, consume_level)
-- SET register_date    = STR_TO_DATE(@reg_date,   '%Y-%m-%d'),
--     is_repurchase    = CAST(@rep      AS UNSIGNED),
--     is_ordered       = CAST(@ordered  AS UNSIGNED),
--     first_order_time = STR_TO_DATE(@first_order, '%Y-%m-%d %H:%i:%s'),
--     total_paid       = CAST(@total_paid AS DECIMAL(12,2));

-- LOAD DATA LOCAL INFILE 'D:/easyagent/ecommerce_analysis/clean_order.csv'
-- INTO TABLE order_info
-- CHARACTER SET utf8mb4
-- FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
-- IGNORE 1 LINES
-- (order_id, user_id, @ot, pay_status, category, @amt, @cart, @paid,
--  order_month, @oh, @first)
-- SET order_time      = STR_TO_DATE(@ot,    '%Y-%m-%d %H:%i:%s'),
--     amount          = CAST(@amt   AS DECIMAL(12,2)),
--     cart_flag       = CAST(@cart  AS UNSIGNED),
--     is_paid         = CAST(@paid  AS UNSIGNED),
--     order_hour      = CAST(@oh    AS UNSIGNED),
--     is_first_order  = CAST(@first AS UNSIGNED);

-- 导入后行数校验（预期：用户约4955行，订单约7699行）
SELECT (SELECT COUNT(*) FROM user_info) AS 用户表行数,
       (SELECT COUNT(*) FROM order_info) AS 订单表行数;


-- ============================================================================
-- 三、核心指标：GMV / 总订单量 / 支付转化率 / 客单价 / 复购率（一行总览）
-- 思路：订单表聚合 + 子查询计算"人数口径"指标，避免 JOIN 导致的重复计数
-- ============================================================================
SELECT
    ROUND(SUM(CASE WHEN is_paid = 1 THEN amount ELSE 0 END), 2)          AS `GMV(元)`,
    COUNT(*)                                                             AS `总订单量`,
    SUM(is_paid = 1)                                                     AS `支付订单量`,
    ROUND(SUM(is_paid = 1) / COUNT(*), 4)                                AS `支付转化率(订单级)`,
    (SELECT COUNT(*) FROM user_info)                                     AS `注册用户数`,
    COUNT(DISTINCT user_id)                                              AS `下单用户数`,
    (SELECT COUNT(*) FROM user_info WHERE is_ordered = 1)                AS `下单用户数(用户表口径)`,
    COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END)               AS `支付用户数`,
    ROUND(COUNT(DISTINCT user_id) / (SELECT COUNT(*) FROM user_info), 4) AS `下单转化率(用户级)`,
    ROUND(COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END)
        / COUNT(DISTINCT user_id), 4)                                    AS `支付转化率(用户级)`,
    ROUND(SUM(CASE WHEN is_paid = 1 THEN amount ELSE 0 END)
        / COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END), 2)     AS `客单价(元)`,
    -- 复购率：支付订单数>=2的用户数 / 支付用户数（子查询按用户聚合后计数）
    (SELECT ROUND(SUM(CASE WHEN pay_cnt >= 2 THEN 1 ELSE 0 END) / COUNT(*), 4)
       FROM (SELECT user_id, SUM(is_paid) AS pay_cnt
               FROM order_info GROUP BY user_id
              HAVING SUM(is_paid) >= 1) t)                              AS `复购率`;
-- 说明：HAVING SUM(is_paid) >= 1 保证分母只含"有支付行为"的用户


-- ============================================================================
-- 四、转化漏斗（用户级）：浏览 -> 加购 -> 提交订单 -> 完成支付
-- 口径：浏览 ≈ 全部注册用户（数据集无独立浏览日志）；加购 = 有加购标记=1订单的用户
-- ============================================================================
SELECT
    (SELECT COUNT(*) FROM user_info)                                          AS `浏览商品(注册用户近似)`,
    COUNT(DISTINCT CASE WHEN cart_flag = 1 THEN user_id END)                  AS `加入购物车`,
    COUNT(DISTINCT user_id)                                                   AS `提交订单`,
    COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END)                    AS `完成支付`,
    -- 各环节整体转化率（相对浏览层）
    ROUND(COUNT(DISTINCT CASE WHEN cart_flag = 1 THEN user_id END)
        / (SELECT COUNT(*) FROM user_info), 4)                                AS `浏览->加购转化率`,
    ROUND(COUNT(DISTINCT user_id)
        / (SELECT COUNT(*) FROM user_info), 4)                                AS `浏览->下单转化率`,
    ROUND(COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END)
        / (SELECT COUNT(*) FROM user_info), 4)                                AS `浏览->支付转化率`
FROM order_info;


-- ============================================================================
-- 五、渠道分群：各注册渠道的转化与复购对比（评估渠道引流质量与后链路承接）
-- ============================================================================
SELECT
    u.register_channel                                                        AS `注册渠道`,
    COUNT(*)                                                                  AS `用户数`,
    COUNT(o.user_id)                                                          AS `下单用户数`,
    ROUND(COUNT(o.user_id) / COUNT(*), 4)                                     AS `下单转化率`,
    COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END)                                AS `支付用户数`,
    ROUND(COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END) / COUNT(o.user_id), 4)   AS `支付转化率`,
    COUNT(CASE WHEN o.pay_cnt >= 2 THEN 1 END)                                AS `复购用户数`,
    ROUND(COUNT(CASE WHEN o.pay_cnt >= 2 THEN 1 END)
        / NULLIF(COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END), 0), 4)           AS `复购率`,
    ROUND(SUM(COALESCE(o.pay_amount, 0))
        / NULLIF(COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END), 0), 2)           AS `客单价(元)`,
    ROUND(SUM(COALESCE(o.pay_amount, 0)), 2)                                  AS `GMV(元)`
FROM user_info u
LEFT JOIN (
    -- 按用户聚合订单，避免一对多 JOIN 造成的用户数重复计数
    SELECT user_id,
           COUNT(*)          AS order_cnt,
           SUM(is_paid)      AS pay_cnt,
           SUM(amount * is_paid) AS pay_amount
    FROM order_info
    GROUP BY user_id
) o ON u.user_id = o.user_id
GROUP BY u.register_channel
ORDER BY GMV DESC;
-- 关键点：JOIN 前先按 user_id 聚合（一用户一行），是避免指标翻倍的常用手法


-- ============================================================================
-- 六、新老用户对比：以 2025-01-01 为界划分（近半年注册 = 新用户）
-- ============================================================================
SELECT
    CASE WHEN u.register_date >= '2025-01-01' THEN '新用户(2025年注册)'
         ELSE '老用户(2024年注册)' END                        AS `用户分层`,
    COUNT(*)                                                  AS `用户数`,
    COUNT(o.user_id)                                          AS `下单用户数`,
    ROUND(COUNT(o.user_id) / COUNT(*), 4)                     AS `下单转化率`,
    ROUND(COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END)
        / COUNT(o.user_id), 4)                                AS `支付转化率`,
    ROUND(COUNT(CASE WHEN o.pay_cnt >= 2 THEN 1 END)
        / COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END), 4)      AS `复购率`,
    ROUND(SUM(COALESCE(o.pay_amount, 0))
        / NULLIF(COUNT(CASE WHEN o.pay_cnt >= 1 THEN 1 END), 0), 2) AS `客单价(元)`
FROM user_info u
LEFT JOIN (
    SELECT user_id, SUM(is_paid) AS pay_cnt, SUM(amount * is_paid) AS pay_amount
    FROM order_info GROUP BY user_id
) o ON u.user_id = o.user_id
GROUP BY `用户分层`
ORDER BY `用户分层`;


-- ============================================================================
-- 七、消费分层：按用户累计支付金额用 NTILE(3) 三等分（高/中/低消费）
-- ============================================================================
WITH user_paid AS (
    -- 每个用户的支付金额汇总
    SELECT user_id, SUM(amount * is_paid) AS pay_amount
    FROM order_info
    GROUP BY user_id
    HAVING SUM(is_paid) >= 1          -- 仅保留有支付行为的用户
),
paid_ranked AS (
    SELECT user_id,
           pay_amount,
           NTILE(3) OVER (ORDER BY pay_amount) AS grp   -- 按支付金额三等分
    FROM user_paid
)
SELECT
    CASE grp WHEN 1 THEN '低消费' WHEN 2 THEN '中消费' ELSE '高消费' END AS `消费分层`,
    COUNT(*)                          AS `用户数`,
    ROUND(SUM(pay_amount), 2)         AS `累计支付金额(元)`,
    ROUND(AVG(pay_amount), 2)         AS `人均支付金额(元)`,
    ROUND(SUM(pay_amount) / (SELECT SUM(amount * is_paid) FROM order_info), 4) AS `GMV贡献占比`
FROM paid_ranked
GROUP BY grp
ORDER BY grp;
-- 结论关注点：高消费1/3用户贡献了约73%的GMV，符合"二八法则"


-- ============================================================================
-- 八、品类统计：销售额 / 订单量 / 支付转化率 / 笔单价 + 销售额排名（窗口函数）
-- ============================================================================
SELECT
    category                                                   AS `商品品类`,
    COUNT(*)                                                   AS `订单量`,
    SUM(is_paid)                                               AS `支付订单量`,
    ROUND(SUM(amount * is_paid), 2)                            AS `销售额(元)`,
    ROUND(SUM(amount * is_paid) / (SELECT SUM(amount * is_paid)
        FROM order_info), 4)                                   AS `销售额占比`,
    ROUND(SUM(is_paid) / COUNT(*), 4)                          AS `支付转化率`,
    ROUND(SUM(amount * is_paid) / NULLIF(SUM(is_paid), 0), 2)  AS `笔单价(元)`,
    RANK() OVER (ORDER BY SUM(amount * is_paid) DESC)          AS `销售额排名`
FROM order_info
GROUP BY category
ORDER BY `销售额排名`;


-- ============================================================================
-- 九、月度经营趋势 + 新用户30天留存（ cohort 思路）
-- ============================================================================
-- 9.1 月度 GMV 与订单量趋势
SELECT
    DATE_FORMAT(order_time, '%Y-%m')                    AS `月份`,
    COUNT(*)                                            AS `订单量`,
    SUM(is_paid)                                        AS `支付订单量`,
    ROUND(SUM(amount * is_paid), 2)                     AS `GMV(元)`,
    COUNT(DISTINCT CASE WHEN is_paid = 1 THEN user_id END) AS `支付用户数`
FROM order_info
GROUP BY DATE_FORMAT(order_time, '%Y-%m')
ORDER BY `月份`;

-- 9.2 新用户30天复购留存：按"首次支付月份"分组，统计30天内再次支付的比例
WITH first_pay AS (
    -- 每个用户的首次支付时间
    SELECT user_id, MIN(order_time) AS first_pay_time
    FROM order_info
    WHERE is_paid = 1
    GROUP BY user_id
),
pay_detail AS (
    -- 每笔支付订单与其用户的首次支付时间关联，计算间隔天数
    SELECT o.user_id,
           f.first_pay_time,
           TIMESTAMPDIFF(DAY, f.first_pay_time, o.order_time) AS gap_days
    FROM order_info o
    JOIN first_pay f ON o.user_id = f.user_id
    WHERE o.is_paid = 1
)
SELECT
    DATE_FORMAT(first_pay_time, '%Y-%m')                     AS `首单月份`,
    COUNT(DISTINCT user_id)                                  AS `首单用户数`,
    COUNT(DISTINCT CASE WHEN gap_days BETWEEN 1 AND 30
                        THEN user_id END)                    AS `30天内复购用户`,
    ROUND(COUNT(DISTINCT CASE WHEN gap_days BETWEEN 1 AND 30 THEN user_id END)
        / COUNT(DISTINCT user_id), 4)                        AS `30天复购留存率`
FROM pay_detail
GROUP BY `首单月份`
ORDER BY `首单月份`;
-- 注意：最后一个月份的用户观察期不足30天，留存率存在截尾偏高，解读时需剔除


-- ============================================================================
-- 十、用户画像：高复购用户特征 + 低转化用户定位
-- ============================================================================
-- 10.1 高复购用户 vs 非复购用户：品类偏好差异（关键业务结论来源）
WITH user_pay AS (
    SELECT user_id, SUM(is_paid) AS pay_cnt
    FROM order_info
    GROUP BY user_id
    HAVING SUM(is_paid) >= 1
),
user_tag AS (
    SELECT user_id,
           CASE WHEN pay_cnt >= 2 THEN '复购用户' ELSE '非复购用户' END AS user_type
    FROM user_pay
)
SELECT
    o.category                                                  AS `商品品类`,
    t.user_type                                                 AS `用户类型`,
    COUNT(*)                                                    AS `支付订单数`,
    ROUND(COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY t.user_type), 4) AS `品类订单占比`,
    ROUND(AVG(o.amount), 2)                                     AS `平均订单金额(元)`
FROM order_info o
JOIN user_tag t ON o.user_id = t.user_id
WHERE o.is_paid = 1
GROUP BY o.category, t.user_type
ORDER BY o.category, t.user_type;
-- 结论关注点：复购用户在食品生鲜/美妆个护/家居日用等高频刚需品类的订单占比显著更高

-- 10.2 高复购用户的注册渠道结构（对比两类用户的渠道构成）
WITH user_pay AS (
    SELECT user_id, SUM(is_paid) AS pay_cnt
    FROM order_info GROUP BY user_id HAVING SUM(is_paid) >= 1
),
user_tag AS (
    SELECT user_id,
           CASE WHEN pay_cnt >= 2 THEN '复购用户' ELSE '非复购用户' END AS user_type
    FROM user_pay
)
SELECT
    u.register_channel AS `注册渠道`,
    t.user_type        AS `用户类型`,
    COUNT(*)           AS `用户数`,
    ROUND(COUNT(*) * 1.0 / SUM(COUNT(*)) OVER (PARTITION BY t.user_type), 4) AS `渠道占比`
FROM user_tag t
JOIN user_info u ON t.user_id = u.user_id
GROUP BY u.register_channel, t.user_type
ORDER BY u.register_channel, t.user_type;

-- 10.3 低转化用户定位：各渠道"注册未下单率"与"下单未支付率"
SELECT
    u.register_channel                                                 AS `注册渠道`,
    COUNT(*)                                                           AS `用户数`,
    SUM(CASE WHEN o.user_id IS NULL THEN 1 ELSE 0 END)                 AS `注册未下单用户`,
    ROUND(SUM(CASE WHEN o.user_id IS NULL THEN 1 ELSE 0 END) / COUNT(*), 4) AS `注册未下单率`,
    SUM(CASE WHEN o.user_id IS NOT NULL AND o.pay_cnt = 0 THEN 1 ELSE 0 END) AS `下单未支付用户`,
    ROUND(SUM(CASE WHEN o.user_id IS NOT NULL AND o.pay_cnt = 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(o.user_id), 0), 4)                              AS `下单未支付率`
FROM user_info u
LEFT JOIN (
    SELECT user_id, SUM(is_paid) AS pay_cnt
    FROM order_info GROUP BY user_id
) o ON u.user_id = o.user_id
GROUP BY u.register_channel
ORDER BY `注册未下单率` DESC;

-- 10.4 下单时段分布：识别下单高峰，指导营销活动排期与催付时间
SELECT
    order_hour                                                         AS `下单小时`,
    COUNT(*)                                                           AS `订单量`,
    ROUND(SUM(is_paid) / COUNT(*), 4)                                  AS `支付转化率`
FROM order_info
GROUP BY order_hour
ORDER BY order_hour;


-- ============================================================================
-- 十一、附：原始脏数据的 SQL 清洗参考（本项目主清洗在 Python 完成，此处演示
--       "仅用 SQL 也可完成同类清洗"的思路，供对比学习）
-- ============================================================================
-- 11.1 去重：按 order_id 用 ROW_NUMBER 保留首条（CTE + 窗口函数写法）
-- DELETE FROM order_raw
-- WHERE order_id IN (
--     SELECT order_id FROM (
--         SELECT order_id,
--                ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY order_time) AS rn
--         FROM order_raw
--     ) t WHERE rn > 1
-- );

-- 11.2 金额异常过滤：业务规则（金额<=0 或 >10000 视为异常）
-- SELECT * FROM order_raw WHERE amount <= 0 OR amount > 10000;

-- 11.3 无效时间过滤：STR_TO_DATE 解析失败返回 NULL，即可筛出非法时间
-- SELECT * FROM order_raw WHERE STR_TO_DATE(order_time_str, '%Y-%m-%d %H:%i:%s') IS NULL;

-- 11.4 支付状态归一化：CASE WHEN 多值映射
-- UPDATE order_raw
-- SET pay_status = CASE LOWER(TRIM(pay_status))
--     WHEN 'paid'    THEN '已支付' WHEN 'success' THEN '已支付' WHEN '成功' THEN '已支付'
--     WHEN '未付款'  THEN '未支付' WHEN 'pending' THEN '未支付'
--     WHEN 'cancel'  THEN '已取消' ELSE pay_status END;
