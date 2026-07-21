# 医院IT工单管理系统 — 产品手册

> **版本**: 2.0 | **最后更新**: 2026年6月  
> **适用场景**: 医院信息科 / IT运维部门 / 后勤保障中心

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [功能模块详解](#3-功能模块详解)
4. [三端协同工作机制](#4-三端协同工作机制)
5. [部署指南](#5-部署指南)
6. [用户角色与权限体系](#6-用户角色与权限体系)
7. [运维管理](#7-运维管理)
8. [常见问题与排障](#8-常见问题与排障)
9. [附录](#9-附录)

---

## 1. 产品概述

### 1.1 一句话介绍

专为医院信息科设计的 IT 工单全生命周期管理系统，覆盖**报修→发布→接单→处理→完成→归档**完整闭环，支持 PC 管理端、Mobile Web 接单端、微信小程序端三端实时同步。

### 1.2 核心价值

| 维度 | 价值点 |
|------|--------|
| 🎯 **效率提升** | 自动识别设备类型/故障类型/地址，一键匹配解决方案模板，批量生成巡检工单 |
| 🔔 **通知闭环** | 企业微信群通知 + 微信订阅消息 + 小程序内轮询，新工单秒级触达 |
| 📊 **数据驱动** | 仪表盘实时展示工单统计、人员排行、趋势分析、月度报表自动生成 |
| 📱 **三端协同** | PC 管理、手机网页接单、微信小程序查单，同一数据底座，实时同步 |
| 🔒 **安全管控** | 角色权限分离、操作审计日志、紧急程度冻结保护、token/session双认证 |

### 1.3 适用场景

- 医院信息科日常IT故障报修管理（电脑、打印机、网络、软件等）
- 全院设备巡检计划制定与执行跟踪
- IT设备资产台账管理与生命周期跟踪
- IT备件耗材库存管理
- 维修工单的电子化填写、审批与归档
- 运维人员排班与工作统计

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       用户访问层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  PC Web端     │  │  Mobile Web  │  │  微信小程序       │   │
│  │ (管理后台)     │  │ (接单端)      │  │ (移动查单/处理)   │   │
│  │ Flask+Jinja2  │  │ 响应式HTML   │  │  WXML+JS+WXSS    │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
└─────────┼──────────────────┼───────────────────┼─────────────┘
          │                  │                   │
          ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                     Nginx 反向代理                             │
│              https://demolin.cn (生产环境)                     │
│              /static/ → 本地静态资源 (30天缓存)                │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Gunicorn WSGI 服务器                        │
│                    Flask 应用 (Python 3.11)                     │
├─────────────────────────────────────────────────────────────┤
│                     认证层                                     │
│  ┌─────────────────┐  ┌────────────────────────────────┐      │
│  │ PC/Mobile Web   │  │ 微信小程序                      │      │
│  │ Session 认证    │  │ Bearer Token 认证               │      │
│  │ Flask-Login     │  │ MobileToken 表                  │      │
│  └─────────────────┘  └────────────────────────────────┘      │
├─────────────────────────────────────────────────────────────┤
│                     路由层（14个蓝图）                          │
│  main/orders/auth/mobile/api_mobile/data/settings            │
│  asset/stock/report/inspection/forms/repair/audit            │
├─────────────────────────────────────────────────────────────┤
│                     业务逻辑层                                 │
│  services/address.py  全院地址数据                             │
│  services/matcher.py  方案模板智能匹配引擎                     │
│  services/generator.py工单生成引擎                             │
│  services/cache.py    轻量缓存层                               │
├─────────────────────────────────────────────────────────────┤
│                     数据层                                     │
│  SQLite 数据库 (workorders.db)                                 │
│  12+ 张业务数据表                                             │
│  预置索引: status/created_at/person/completed_at              │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| **后端框架** | Flask 3.0 + Python 3.11 | ≥ 3.0 |
| **ORM** | Flask-SQLAlchemy 3.0 | ≥ 3.0 |
| **数据库** | SQLite 3（单文件部署） | 内置 |
| **用户认证** | Flask-Login (Web) + Bearer Token (小程序) | — |
| **Web 服务器** | Gunicorn | ≥ 20.0 |
| **反向代理** | Nginx | ≥ 1.18 |
| **前端模板** | Jinja2 + Bootstrap 5 + Font Awesome 6 | — |
| **图表库** | Chart.js (仪表盘交互图表) | — |
| **小程序端** | 微信原生开发框架 (WXML/WXSS/JS) | — |
| **Android端** | Kotlin + WebView (Flask session cookie 穿透) | — |
| **Excel处理** | openpyxl | ≥ 3.0 |
| **模糊匹配** | fuzzywuzzy + python-Levenshtein | ≥ 0.18 |

### 2.3 部署拓扑（生产环境）

```
                  ┌─────────────────────┐
                  │     用户浏览器       │
                  │  (PC/Mobile/小程序)  │
                  └──────────┬──────────┘
                             │ HTTPS :443
                             ▼
                  ┌─────────────────────┐
                  │      Nginx          │ ★ 生产环境 1C2G 轻量云服务器
                  │  SSL termination    │
                  │  /static/ → 本地缓存 │
                  │  / → proxy_pass 5000│
                  └──────────┬──────────┘
                             │ HTTP :5000
                             ▼
                  ┌─────────────────────┐
                  │   Gunicorn          │
                  │  4 workers + wsgi   │
                  │  Flask 应用         │
                  └──────────┬──────────┘
                             │
                             ▼
                  ┌─────────────────────┐
                  │   SQLite DB         │
                  │  workorders.db      │
                  │ + .env 配置         │
                  └─────────────────────┘
```

**服务器规格（推荐）**:
- **最低配置**: 1核 2GB 内存, 20GB 系统盘
- **推荐配置**: 2核 4GB 内存, 40GB 系统盘
- **操作系统**: Ubuntu 22.04 LTS
- **域名要求**: 已备案域名，配置 SSL 证书（WeChat 小程序要求 HTTPS）

---

## 3. 功能模块详解

### 3.1 📊 仪表盘 (Dashboard)

**访问路径**: `GET /`

**功能说明**:
工单管理系统的数据总览中枢，以可视化图表和数据卡片展示本月运维全貌。

**展示内容**:

| 组件 | 类型 | 说明 |
|------|------|------|
| 本月统计卡片 | 统计值 | 工单总数、已完成、进行中、待接单（含环比） |
| 故障类型分布 | 环形图 | 按故障类型统计数量及占比 |
| 处理人员排行 | 横向柱状图 | 本月接单量 Top 排行榜 |
| 近7天工单趋势 | 折线图 | 每天新工单和完成工单的走势对比 |
| 响应时长趋势 | 折线图 | 每日平均响应时长（分钟，上限60，Y轴自适应缩放） |
| 今日动态 | 滚动列表 | 最新10条工单状态变化实时刷新 |
| 楼区热度图 | 横向柱状图 | 各楼栋/区域的工单量排行 |
| 科室排行 | 横向柱状图 | 各科室报修量 Top 排行 |

**交互特性**:
- 图表区域支持轮播显示（7秒自动切换，圆点指示器右下角）
- 数据实时响应，页面刷新即获取最新统计
- 所有卡片标题统一前缀"本月"

### 3.2 📋 工单管理 (Orders)

#### 3.2.1 工单列表

**访问路径**: `GET /orders`

**三标签页结构**:

| 标签 | 状态筛选 | 说明 |
|------|----------|------|
| ⏳ 待接单 | `pending` | 已发布但尚未被认领的工单 |
| 🔧 处理中 | `in_progress` | 已被工程师接单但尚未完成的工单 |
| ✅ 已完成 | `completed` | 已填方案并结单的工单 |

**多维筛选条件**:
- 状态筛选（三标签）
- 楼区 / 楼层 / 科室（三级联动下拉）
- 设备类型
- 故障类型
- 处理人员
- 关键词搜索（匹配标题/描述/位置）
- 日期范围（起止日期）
- 紧急程度筛选

**排序规则**:
- 默认按紧急程度降序：紧急🔴 → 加急🟡 → 普通🟢
- 同级内按创建时间降序

**列表视觉规范**:

| 元素 | 说明 |
|------|------|
| 优先级圆点 | 🔴紧急 / 🟡加急 / 🟢普通（**已完成工单显示 original_priority**，冻结不变） |
| 紧急程度标签 | 红色标签 = 紧急，黄色标签 = 加急，绿色标签 = 普通 |
| 状态标签 | 待接单蓝、处理中橙、已完成绿 |
| 时间显示 | 发布多久前（自动换算分钟/小时/天） |

#### 3.2.2 发布工单

**访问路径**: `POST /orders/publish`

**智能识别能力**:
- **设备类型自动识别**: 根据标题关键词自动匹配（如"打印机卡纸"→打印机）
- **故障类型自动识别**: 根据标题匹配故障分类（打印机故障/软件故障/硬件故障）
- **地址自动提取**: 输入关键词自动补全楼区→楼层→科室→详细位置
- **方案模板建议**: 输入标题后 AJAX 实时查询匹配方案模板

**通知推送**:
- 企业微信群机器人通知（Markdown 格式含工单标题+位置+紧急程度）
- 微信订阅消息推送（已订阅用户接收新工单提醒）

#### 3.2.3 工单详情与编辑

**访问路径**: `GET /orders/<id>`

**详情页内容**:
- 工单标题、设备类型、故障类型、紧急程度
- 完整地址信息（楼区→楼层→科室→位置）
- 故障描述、处理方案、处理人
- 发布时间、接单时间、完成时间（时间线展示）
- 关联电子表单（如有）

**编辑页规则**:
- 已结单工单禁止修改紧急程度（返回403）
- 所有字段可编辑（管理员权限）
- 修改记录写入审计日志

#### 3.2.4 紧急程度管理

**优先级循环**: `normal → urgent → emergency → normal`

**规则**:
- 未接单工单可任意切换
- **已结单工单冻结**：显示 `original_priority`（创建时原始优先级）
- 自动升级脚本（`scripts/auto_escalate.py`）仅影响未接单工单的 `priority` 字段

**紧急程度含义**:

| 级别 | 颜色 | 说明 | 自动升级触发 |
|------|------|------|-------------|
| 普通 🟢 | 绿色 | 常规问题，按排队顺序处理 | → 加急（超时限） |
| 加急 🟡 | 黄色 | 需尽快处理 | → 紧急（再超时限） |
| 紧急 🔴 | 红色 | 影响业务运行，立即处理 | 不再升级 |

#### 3.2.5 批量生成工单

**访问路径**: `POST /orders/batch`

**双步骤流程**:
1. **预览**: 输入数量（1-50），系统自动生成预览列表
2. **确认**: 确认后批量入库，支持 5 分钟内撤回（`/orders/batch/undo`）

**生成范围**: 软件故障、硬件故障、打印机故障、协助请求等场景

#### 3.2.6 Excel 导出

**访问路径**: `GET /orders/export`

- 导出当前所有筛选条件下的工单
- 文件格式: `.xlsx`（openpyxl）
- 包含字段: 编号、标题、设备类型、故障类型、位置、状态、紧急程度、处理人、时间等

### 3.3 📱 Mobile Web 端（接单端）

**访问根路径**: `/mobile/`

专为运维人员在手机浏览器中设计的接单工作台，与 PC 端共用 Session 认证。

#### 3.3.1 工单列表

**三标签设计**:
- 待接单 → 处理中 → 今日已完成

**统计标识**:
- 页面顶部显示四项统计数字（pending / in_progress / completed / completed_today）
- 已完成仅显示当日数据

#### 3.3.2 接单操作

| 操作 | 路径 | 描述 |
|------|------|------|
| 接单 | `POST /mobile/order/<id>/accept` | 认领工单，状态 pending → in_progress |
| 填方案 | `POST /mobile/order/<id>/solve` | 提交处理方案，in_progress → completed |
| 一键结单 | `POST /mobile/order/<id>/quick-solve` | 自动匹配方案模板并完成 |
| 巡检提交 | `POST /mobile/order/<id>/inspection-submit` | 提交巡检结果+签名 |

#### 3.3.3 今日总结

**访问路径**: `GET /mobile/today-summary`

一键生成当日已完成工单的格式化工作总结文本，自动复制到剪贴板。

### 3.4 📱 微信小程序端

#### 3.4.1 功能清单

| 页面 | 功能 |
|------|------|
| 登录页 | 密码登录、微信自动登录、微信绑定 |
| 工单列表 | 三标签切换、统计数字、一键结单、今日总结、新单轮询提醒 |
| 工单详情 | 查看信息、接单、处理方案、巡检提交、电子表单内联编辑 |
| 电子表单 | 动态字段渲染、手写签名、提交审批 |

#### 3.4.2 认证流程

```
小程序启动
    │
    ├── 本地有 Token？ → 调用 /api/mobile/profile 验证
    │       │               │
    │       │ 有效          │ 无效 → 清除 Token → 跳转登录页
    │       ▼
    │   进入首页
    │
    └── 本地无 Token → 跳转登录页
            │
            ▼
    用户输入账号密码 → POST /api/mobile/login
            │
            ▼
    返回 Token + 用户信息 → 本地存储 Token
            │
            ▼
    尝试微信绑定: wx.login() → POST /api/mobile/bind_wx
            │
            ▼
    进入首页
```

#### 3.4.3 新工单轮询机制

- 待接单标签页每 10 秒后台刷新
- 发现新工单时：Toast 提示 + 震动反馈
- 支持微信订阅消息推送（一次性订阅，需用户授权）

#### 3.4.4 电子表单

支持 10+ 种字段类型：
- 文本框、数字、邮箱、电话、网址、多行文本
- 下拉选择、单选、日期、复选框
- 手写签名（Canvas 2D 触摸绘制）
- 装饰字段：标题/分割线/标签/富文本

**审批流程**: 保存草稿 → 提交审批 → 审批通过（自动完结关联工单）

### 3.5 🤖 Android 接单端

#### 3.5.1 架构设计

Android 原生应用 + WebView 容器，加载 Mobile Web 端页面，通过 **Session Cookie 穿透** 实现无缝登录。

**核心文件**:
- `HospitalWorkorderActivity.kt` — 主 Activity，WebView 配置
- `BootReceiver.kt` — 开机自启动，保障服务持续运行
- `NotificationService.kt` — 后台轮询通知服务

#### 3.5.2 功能特性

| 特性 | 实现方式 |
|------|----------|
| 登录页 | 原生白色背景输入框（不加载 Flask 登录页，优化体验） |
| 主页 | WebView 加载 `/mobile/`，Cookie 双份存储（local + httpOnly） |
| 自动登录 | WebView 加载 `/mobile/auto-login/<uid>` 自动设置 session |
| 通知推送 | 30 秒轮询 `select-user` API，Bearer token 鉴权 |
| 后台保活 | BootReceiver + WakeLock (10min/cycle) + 电池优化白名单引导 |
| 离线通知 | Android 13+ POST_NOTIFICATIONS 权限申请 |

### 3.6 🗄️ 数据管理

**访问路径**: `GET /data`

8 大基础数据管理模块，统一使用数据管理首页作为入口。

| 模块 | 功能 |
|------|------|
| **人员管理** | 增删改、启用/停用、创建登录账号、从工单导入 |
| **科室字典** | 楼区/楼层/地址信息维护、导入科室 |
| **方案模板** | 200+ 条预置模板、编辑/新增/删除、重置默认、从工单导入 |
| **地址数据** | 全院地址树管理、覆盖/新增/软删除 |
| **故障类型** | 自定义分类及关键词匹配规则 |
| **存放位置** | 备件/耗材存放位置字典 |
| **供应商管理** | 供应商信息维护（联系人/电话/服务范围/合同到期） |
| **知识库** | 运维知识文章管理，分类筛选 |

### 3.7 🖥️ 资产台账

**访问路径**: `GET /asset`

| 功能 | 说明 |
|------|------|
| 保修日历 | 按剩余天数排序，筛选(即将过期/已过保/有效) |
| 资产列表 | 搜索/筛选/分页展示 |
| 资产详情 | 含关联工单历史 |
| 新增/编辑资产 | 50+ 字段：资产编号、品牌型号、SN、配置、位置、财务信息 |
| 批量操作 | 批量编辑/调拨/回收/移位 |
| Excel 导入导出 | 支持下载导入模板 |
| 操作日志 | 记录资产所有变更 |

### 3.8 📦 备件库存

**访问路径**: `GET /stock`

| 功能 | 说明 |
|------|------|
| 库存总览 | 分类筛选，低库存预警（<=min_stock 红色标记） |
| 备件详情 | 基本信息 + 出入库历史记录 |
| 出入库操作 | 填写数量、关联工单号、备注 |
| Excel 导入 | 下载模板后批量导入 |

### 3.9 💧 耗材管理

**访问路径**: `GET /data/consumables`

| 功能 | 说明 |
|------|------|
| 耗材列表 | 搜索筛选、库存预警 |
| 新增/编辑 | 名称、型号、品牌、分类、库存、最低库存预警 |
| 出入库 | 入库/出库操作，自动更新库存 |
| Excel 导入 | 含"下载表头模板"功能 |

### 3.10 ✅ 巡检管理

**访问路径**: `GET /inspection/templates`

| 功能 | 说明 |
|------|------|
| 巡检模板 | 预设巡检内容项列表（如"检查电源""检查温度"等） |
| 巡检计划 | 模板+位置+时间→到期自动生成巡检工单 |
| 巡检执行 | Mobile Web/小程序端逐项勾选✅❌⬜，手写签名 |
| 巡检确认单 | 导出/打印巡检报告 |
| 自动检查 | 前端定时调用 `/inspection/api/check_due` 触发到期计划 |

### 3.11 📄 电子表单

**访问路径**: `GET /forms`

| 功能 | 说明 |
|------|------|
| 表单模板 | 可视化配置字段列表（A4 画布定位布局） |
| 表单实例 | 使用模板创建 → 填充数据 → 提交审批 → 完结工单 |
| 字段类型 | 10+ 种（text/number/email/tel/url/textarea/select/radio/date/checkbox/signature） |
| 数据源 | 动态加载科室/人员/位置等下接选项 |
| 审批流程 | 提交 → 审批通过（自动完结关联工单）|
| 打印 | A4 尺寸动态表单打印 |

### 3.12 🔧 维修管理

**访问路径**: `GET /repair`

| 功能 | 说明 |
|------|------|
| 维修单列表 | 搜索/筛选/分页 |
| 创建维修单 | 选择维修模板 |
| 填写/编辑 | 保存字段值、手写签名 |
| 审批流程 | 提交审核 → 审批通过/驳回 |
| 打印 | 维修单打印 |
| 统计报表 | 维修单统计图表 |

### 3.13 📅 值班排班

**访问路径**: `GET /data/duty-schedules`

| 功能 | 说明 |
|------|------|
| 网格视图 | 横向日期 × 纵向人员，按月展示 |
| 单元格编辑 | 点击快速设置班次 |
| 批量操作 | 填充整行、填充工作日、清空、复制上个月 |
| Excel 导入 | 批量导入排班数据 |
| 人员管理 | 排班人员增删改、启用/停用 |

### 3.14 📊 月度报表

**访问路径**: `GET /report`

**7 大维度统计**:

| 维度 | 展示方式 |
|------|----------|
| 工单总量趋势 | 全年月度柱状图 |
| 故障类型分布 | 环形图 |
| 人员工作量统计 | 横向柱状图 |
| 各科室工单分布 | 横向柱状图 |
| 响应时效分析 | 折线图 |
| 完成率走势 | 折线图 |
| 紧急程度分布 | 柱状图 |

**导出**: 一键下载 Excel 报表（7 个工作表对应 7 个维度）

### 3.15 📜 审计日志

**访问路径**: `GET /audit/logs`

| 功能 | 说明 |
|------|------|
| 操作记录 | 分页展示所有用户操作 |
| 日志搜索 | 按操作人、操作类型、目标类型筛选 |
| 审计统计 | 今日操作量、趋势、TOP 操作人 |
| 记录类型 | create/update/delete/login/logout |

### 3.16 🛡️ 权限管理

**访问路径**: `GET /data/permissions`

**角色体系**:

| 角色 | 说明 |
|------|------|
| **管理员** (is_admin=True) | 所有模块可见，可管理所有数据 |
| **普通用户** (is_admin=False) | 按模块权限矩阵控制可见性 |

**权限配置**:
- 动态编辑模块权限矩阵（15+ 个业务模块）
- 管理员/普通用户分别配置
- 配置存储在 `SystemSetting` 表 `module_permissions` 键中
- 侧边栏根据 `can_access()` 动态渲染

---

## 4. 三端协同工作机制

### 4.1 数据一致性

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   PC 管理端   │     │  Mobile Web  │     │  微信小程序   │
│  (Flask Web)  │     │  (Flask Web) │     │  (微信原生)   │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ Session 认证  │     │ Session 认证  │     │ Token 认证   │
│ routes/      │     │ routes/      │     │ routes/      │
│ orders.py    │     │ mobile.py    │     │ api_mobile.py│
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └────────────────┬───────────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │   同一数据库    │
               │  workorders.db │
               │  (SQLite)      │
               └────────────────┘
```

### 4.2 通知推送体系

```
新工单发布
    │
    ├── 企业微信群机器人 ──→ Markdown 消息（标题 + 位置 + 紧急程度 + 链接）
    │
    ├── 微信订阅消息 ──→ 已订阅用户接收新工单提醒（一次性订阅）
    │
    └── 小程序内轮询 ──→ 每 10 秒刷新待接单列表，新单到达 toast 提示 + 震动
```

### 4.3 紧急程度冻结机制

```
┌────────────────────────────────────────────────────────────┐
│                   紧急程度生命周期                            │
│                                                            │
│  创建工单       未接单期间       接单处理        完成结单     │
│  ┌──────┐     ┌─────────┐     ┌──────┐     ┌─────────┐   │
│  │🟢普通│────→│🟢→🟡→🔴│────→│🔴紧急│────→│🟢普通   │   │
│  │      │     │自动升级  │     │      │     │冻结不变  │   │
│  └──────┘     └─────────┘     └──────┘     └─────────┘   │
│                                                            │
│  priority = normal   priority 可被升级    priority=emergency │
│  original_priority=normal  original_priority=normal        │
│                             显示 original_priority=normal    │
└────────────────────────────────────────────────────────────┘
```

---

## 5. 部署指南

### 5.1 快速部署（生产环境）

#### 前置条件

- Ubuntu 22.04+ / Debian 11+
- Python 3.11+
- Nginx 已安装
- 已备案域名并配置 DNS 指向服务器
- SSL 证书（Let's Encrypt 或商业证书）

#### 一键部署脚本

```bash
# 1. 进入项目目录
cd /var/www/hospital-workorder

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cat > .env << 'EOF'
WECHAT_APPID=wxbb774dea14895624
WECHAT_SECRET=你的secret
WECHAT_TEMPLATE_ID=你的模板ID
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
SECRET_KEY=your-random-secret-key-here
EOF

# 5. 初始化数据库
python app.py --init-db

# 6. 配置 Nginx
# 参考下方 Nginx 配置

# 7. 启动服务
gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app
```

#### Nginx 配置

```nginx
server {
    listen 443 ssl http2;
    server_name demolin.cn;

    ssl_certificate /etc/letsencrypt/live/demolin.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/demolin.cn/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # 静态资源（不经过 Flask，大幅提升性能）
    location /static/ {
        alias /var/www/hospital-workorder/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 动态请求转发到 Gunicorn
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 80;
    server_name demolin.cn;
    return 301 https://$server_name$request_uri;
}
```

#### SSL 证书配置（重要）

微信小程序要求 HTTPS，且老版本微信客户端不信任 ECDSA 证书链：

```bash
# 推荐使用 RSA 证书
certbot certonly --key-type rsa --webroot -w /var/www/html -d demolin.cn

# 或者使用经典证书链
certbot certonly --key-type rsa --webroot -w /var/www/html \
  -d demolin.cn --preferred-chain "ISRG Root X1"
```

### 5.2 微信小程序配置

#### 小程序后台配置

1. 登录 [微信公众平台](https://mp.weixin.qq.com)
2. **开发管理 → 服务器域名**:
   - `request合法域名`: `https://demolin.cn`
3. **小程序后台 → 订阅消息**:
   - 添加订阅模板（工单状态通知）

#### 部署后的验证清单

- [ ] PC 端访问 `https://demolin.cn` 正常
- [ ] Mobile Web 访问 `https://demolin.cn/mobile/` 正常
- [ ] 微信小程序真机调试可正常登录
- [ ] 企业微信群消息推送正常
- [ ] 微信订阅消息推送正常
- [ ] 关键词搜索：CDN 资源使用本地 `static/vendor/` 避免被拦截
- [ ] 小程序 TTL 检查：WXML 中无方法调用（如 `.substring()` `.startsWith()` 等前端预计算）

### 5.3 开发环境

```bash
# 克隆项目
git clone <repo-url>
cd hospital-workorder

# 安装依赖
pip install -r requirements.txt

# 直接启动（开发模式）
python app.py --debug

# 访问 http://127.0.0.1:5000
# 默认管理员 admin / admin123
```

---

## 6. 用户角色与权限体系

### 6.1 角色定义

| 角色 | 权限范围 | 典型用户 |
|------|----------|----------|
| **系统管理员** | 全模块访问、权限管理、数据管理、审计日志 | 信息科主任、系统管理员 |
| **运维工程师** | 工单处理、接单/填方案、知识库、巡检 | 一线IT运维人员 |
| **工单发布员** | 发布工单、查看工单列表 | 护士长、科室管理员 |

### 6.2 模块权限矩阵（默认配置）

| 模块 | 管理员 | 普通用户 |
|------|--------|----------|
| 仪表盘 | ✅ | ✅ |
| 工单列表 | ✅ | ✅ |
| 发布工单 | ✅ | ✅ |
| 新建工单 | ✅ | ✅ |
| 批量生成 | ✅ | ❌ |
| 知识库 | ✅ | ✅ |
| 巡检管理 | ✅ | ✅ |
| 数据管理首页 | ✅ | ❌ |
| 资产台账 | ✅ | ❌ |
| 备件库存 | ✅ | ❌ |
| 耗材管理 | ✅ | ❌ |
| 值班排班 | ✅ | ❌ |
| 审计日志 | ✅ | ❌ |
| 月度报表 | ✅ | ❌ |
| 权限管理 | ✅ | ❌ |

### 6.3 紧急程度操作权限

| 状态 | 操作 | 权限要求 |
|------|------|----------|
| 未接单 (pending) | 循环切换优先级 | 管理员/发布者 |
| 处理中 (in_progress) | 循环切换优先级 | 管理员/处理人 |
| 已完成 (completed) | **冻结，不可修改** | 无（任何人均不可操作） |

---

## 7. 运维管理

### 7.1 日常运维命令

```bash
# 查看服务状态
systemctl status hospital-workorder

# 重启服务
sudo systemctl restart hospital-workorder

# 查看实时日志
journalctl -u hospital-workorder -f

# 数据库备份（SQLite）
cp /var/www/hospital-workorder/workorders.db \
   /var/backups/workorders-$(date +%Y%m%d-%H%M%S).db

# 保留最近 3 份备份，循环覆盖
```

### 7.2 紧急程度自动升级配置

**脚本路径**: `scripts/auto_escalate.py`

**升级规则**:
- 未接单且状态为 `normal` 的工单 → 升级为 `urgent`
- 未接单且状态为 `urgent` 的工单 → 升级为 `emergency`
- `emergency` 和已接单/已完成的工单不处理

**定时执行**（建议 crontab 每 5 分钟运行）:
```bash
*/5 * * * * cd /var/www/hospital-workorder && venv/bin/python scripts/auto_escalate.py >> logs/auto_escalate.log 2>&1
```

### 7.3 数据库备份策略

```
┌──────────────────────────────────────────────────────────────────┐
│  备份轮换策略（3份循环）                                          │
│                                                                    │
│  workorders-周一.db → workorders-周二.db → workorders-周三.db     │
│             ↓                       ↓                       ↓      │
│         覆盖周一                 覆盖周二                 覆盖周三   │
│                                                                    │
│  附加：SQLite WAL/SHM 文件完整性检查（备份前先 wal_checkpoint）    │
└──────────────────────────────────────────────────────────────────┘
```

### 7.4 常见配置项（SystemSetting 表）

| Key | 说明 | 默认值 |
|-----|------|--------|
| `default_priority` | 默认紧急程度 | `normal` |
| `module_permissions` | 模块权限矩阵（JSON） | 见权限矩阵表 |
| `wecom_webhook_url` | 企业微信群机器人 URL | 从 .env 读取 |

### 7.5 微信通知配置

**环境变量**（`.env` 文件）:

```bash
WECHAT_APPID=wxbb774dea14895624       # 小程序 AppID
WECHAT_SECRET=your_secret              # 小程序 AppSecret
WECHAT_TEMPLATE_ID=your_template_id    # 订阅消息模板 ID
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx  # 企微机器人
```

**订阅消息**为一次性订阅，每次推送需用户授权。**企业微信 Webhook** 无需授权，配置 URL 即生效。

---

## 8. 常见问题与排障

### Q1: 小程序编译报错 `Bad attr 'value' with message: unexpected token '.'`

**原因**: WXML 模板不支持在属性中直接使用方法调用（如 `.substring()`, `.startsWith()`, `.indexOf()`）。  
**解决**: 在 JS 层预计算所有需要方法调用的值，放入 `data` 或 `_displayVals` 对象传入模板。

### Q2: 已完成工单全部显示为绿色

**原因**: `original_priority` 字段被错误回填为 `normal`，或者 `priority` 被自动升级脚本升高后未保留原始值。  
**解决**: 已完成工单显示 `original_priority`（创建时的原始紧急程度），而非被升级后的 `priority`。

### Q3: 工单状态标签变红/变绿闪烁

**原因**: 优先级循环切换逻辑（`toggle_priority`）污染了已完成工单的 `priority` 值。  
**解决**: 已结单工单通过 `toggle_priority` 路由返回 403 禁止修改；自动升级脚本过滤 `status != 'completed'`。

### Q4: 企业微信通知收不到

**排查步骤**:
1. 确认 `.env` 中 `WECOM_WEBHOOK_URL` 配置正确
2. 检查用户发的消息格式 → webhook 支持 Markdown
3. 查看 Gunicorn 日志是否有 `send_wecom_notification` 错误
4. 测试 Webhook URL: `curl -X POST -H 'Content-Type: application/json' -d '{"msgtype":"text","text":{"content":"测试消息"}}' <你的WEBHOOK_URL>`

### Q5: 微信订阅消息推送失败 errcode 43101

**原因**: 用户未授权订阅（一次性订阅消息需要用户点击"允许"）。  
**解决**: 在订阅调用前使用 `wx.requestSubscribeMessage` 弹窗获取用户授权，仅在用户点击"允许"时推送。

### Q6: 微信小程序 SSL 证书不受信任

**原因**: 老版本微信客户端（Android 7.0 以下）不信任 ECDSA 证书链。  
**解决**: 使用 `certbot --key-type rsa` 生成 RSA 证书，或添加 `--preferred-chain "ISRG Root X1"` 使用经典证书链。

### Q7: 小程序登录后返回 401

**排查步骤**:
1. 检查 `config.js` 中 `API_BASE_URL` 是否配置为 HTTPS 地址
2. 检查小程序后台 `request合法域名` 是否已添加
3. 检查小程序真机调试 console 确认 Token 是否成功存储
4. 确认 `Authorization: Bearer <token>` 请求头格式正确

### Q8: Nginx 配置后访问报 502 Bad Gateway

**排查步骤**:
1. `systemctl status hospital-workorder` 确认 Gunicorn 进程运行
2. `sudo nginx -t` 检查 Nginx 配置语法
3. `tail -f /var/log/nginx/error.log` 查看 Nginx 错误日志
4. 检查 `proxy_pass http://127.0.0.1:5000;` 端口与 Gunicorn 监听端口一致

### Q9: 导入资产/备件 Excel 时报错

**排查步骤**:
1. 确认 Excel 文件格式为 `.xlsx`（非 `.xls`）
2. 下载导入模板确认列名完全匹配
3. 检查必填字段是否填写完整（如资产编号 Asset Code 不能为空）
4. 查看浏览器控制台网络请求的返回错误信息

### Q10: 导出月度报表无数据

**原因**: 报表数据依赖于当月工单统计数据，如果当月无工单或筛选条件太严格（如起止日期选择错误）。  
**解决**: 检查 `GET /report/data` 接口返回的 JSON 数据结构，确认工单数据存在且日期范围正确。

---

## 9. 附录

### A. 文件目录结构

```
hospital-workorder/
├── app.py                     # 应用工厂 & 开发入口
├── wsgi.py                    # Gunicorn 生产入口
├── config.py                  # 配置（路由规则/方案模板）
├── models.py                  # 数据模型（12+ 表）
├── requirements.txt           # Python 依赖
├── .env                       # 环境变量（微信/企微密钥）
├── deploy.sh                  # Linux 一键部署脚本
├── start.bat                  # Windows 启动（双击运行）
├── workorders.db              # SQLite 数据库文件
│
├── routes/                    # 路由蓝图
│   ├── __init__.py
│   ├── auth.py                # 登录认证
│   ├── main.py                # 仪表盘
│   ├── orders.py              # 工单管理（PC端）
│   ├── mobile.py              # Mobile Web 端
│   ├── api_mobile.py          # 小程序 API
│   ├── data.py                # 数据管理
│   ├── data_settings.py       # 系统参数设置
│   ├── asset.py               # 资产台账
│   ├── stock.py               # 备件库存
│   ├── report.py              # 月度报表
│   ├── inspection.py          # 巡检管理
│   ├── forms.py               # 电子表单
│   ├── repair.py              # 维修管理
│   └── audit.py               # 审计日志
│
├── services/                  # 业务逻辑
│   ├── address.py             # 全院地址数据（700+ 条）
│   ├── generator.py           # 工单生成引擎
│   ├── matcher.py             # 方案模板匹配引擎
│   └── cache.py               # 轻量缓存
│
├── templates/                 # Jinja2 模板
│   ├── base.html              # 主布局（侧边栏/权限控制）
│   ├── login.html             # 登录页
│   ├── dashboard.html         # 仪表盘
│   ├── order_edit.html        # 工单编辑
│   ├── orders/                # 工单列表/详情
│   ├── data/                  # 数据管理各子页面
│   ├── mobile/                # Mobile Web 端页面
│   ├── asset/                 # 资产台账页面
│   ├── stock/                 # 备件库存页面
│   ├── inspection/            # 巡检管理页面
│   ├── forms/                 # 电子表单页面
│   ├── repair/                # 维修管理页面
│   ├── report/                # 月度报表页面
│   └── audit/                 # 审计日志页面
│
├── static/                    # 静态资源
│   ├── css/
│   ├── js/
│   └── vendor/                # 本地化 CDN（Bootstrap/FontAwesome）
│
├── scripts/                   # 工具脚本
│   ├── auto_escalate.py       # 工单自动升级脚本
│   ├── populate_*.py          # 数据填充脚本
│   └── fix_*.py               # 数据修复脚本
│
└── miniprogram/               # 微信小程序源码
    ├── app.js / app.json / app.wxss
    ├── config.js              # API 地址配置
    ├── utils/
    │   └── api.js             # API 封装层（19 个方法）
    └── pages/
        ├── login/             # 登录页
        ├── orders/            # 工单列表页（三标签）
        ├── order/             # 工单详情页
        └── form/              # 电子表单页
```

### B. 数据库表关系图

```
┌──────────────┐       ┌──────────────────┐
│    User      │       │   WorkOrder      │
│──────────────│       │──────────────────│
│ id (PK)      │◄──────│ created_by       │
│ username     │       │ person           │
│ display_name │       │ status           │
│ is_admin     │       │ priority         │
│ wx_openid    │       │ original_priority│
│ phone        │       │ device_type      │
│ group        │       │ fault_type       │
└──────┬───────┘       │ building/floor   │
       │               │ department/loc   │
       │               │ solution         │
       │               │ work_type        │
       │               └────────┬─────────┘
       │                        │
       │               ┌────────┴─────────┐
       │               │ InspectionPlan   │
       │               │──────────────────│
       │               │ template_id (FK) │
       │               │ work_order_id(FK)│
       │               │ scheduled_time   │
       │               └──────────────────┘
       │
┌──────┴───────┐       ┌──────────────────┐
│ MobileToken  │       │  InspectionTmp   │
│──────────────│       │──────────────────│
│ user_id (FK) │       │ name             │
│ token        │       │ items (JSON)     │
└──────────────┘       └──────────────────┘

┌──────────────┐       ┌──────────────────┐
│ SubscribeUser│       │  FormTemplate    │
│──────────────│       │──────────────────│
│ user_id (FK) │       │ name             │
│ openid       │       │ fields_json(JSON)│
└──────────────┘       └────────┬─────────┘
                                │
┌──────────────┐       ┌────────┴─────────┐
│ AuditLog     │       │   PaperForm      │
│──────────────│       │──────────────────│
│ action       │       │ template_id (FK) │
│ target_type  │       │ work_order_id(FK)│
│ target_id    │       │ form_data (JSON) │
│ operator     │       │ status           │
│ detail       │       └──────────────────┘
└──────────────┘

┌──────────────┐       ┌──────────────────┐
│    Asset     │       │   SparePart      │
│──────────────│       │──────────────────│
│ asset_no (UK)│       │ name             │
│ device_type  │       │ model_no         │
│ brand/sn     │       │ stock            │
│ department   │       │ min_stock        │
│ warranty_end │       │ ──────────────── │
│ status       │       │ StockRecord      │
└──────────────┘       │ part_id (FK)     │
                       │ type (in/out)    │
┌──────────────┐       │ quantity/balance │
│   Supplier   │       └──────────────────┘
│──────────────│
│ name (UK)    │       ┌──────────────────┐
│ contact      │       │   Person         │
│ phone        │       │──────────────────│
│ service_scope│       │ name (UK)        │
│ contract_end │       │ phone/team/notes │
└──────────────┘       │ is_active        │
                       └──────────────────┘
```

### C. 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| 1.0 | 2025-Q4 | 基础工单管理（发布/接单/完成），PC端+Mobile Web |
| 1.5 | 2026-Q1 | 微信小程序端上线，仪表盘图表，资产台账 |
| 1.8 | 2026-Q2 | 电子表单系统，巡检管理，Android 接单端，备件库存 |
| 2.0 | 2026-06 | 紧急程度冻结机制，今日总结，批量操作优化，权限矩阵重构 |

### D. 联系与支持

- **系统演示**: [https://demolin.cn](https://demolin.cn)
- **默认管理员**: admin / admin123
- **技术支持**: 信息科内部运维团队

---

> **© 2026 医院IT工单管理系统** | 本文档为内部使用，未经授权不得外传。
