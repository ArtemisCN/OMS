# 工单助手 - 微信小程序

医院维修工单手机接单端，对接现有 Flask 后端 REST API。

## 功能

| 页面 | 功能 |
|---|---|
| 登录 | 用户名+密码认证，自动存储 token |
| 工单列表 | 三标签页：待接单 / 处理中 / 已完成 |
| 工单详情 | 完整信息展示，按状态提供操作按钮 |

## 操作流程

```
管理员 PC 端发布工单 ──→ 待接单 ⏳
                               ↓
维修人员手机端查看 ──→ [立即接单] ──→ 处理中 🔧
                                            ↓
                                    [填写方案] ──→ 已完成 ✅
```

## 账号

| 姓名 | 用户名 | 密码 |
|---|---|---|
| 张程 | zhangcheng | zhang123 |
| 徐天麟 | xutianlin | xu123 |
| 季张欢 | jizhuanhuan | ji123 |
| 代茂霖 | daimaolin | dai123 |
| 姚毫 | yaohao | yao123 |

管理员账号：`admin` / `admin123`（小程序端未开放）

## 部署教程

### 1. 配置服务器地址

打开 `config.js`，修改 `API_BASE_URL` 为你的服务器地址：

```javascript
// 开发阶段（微信开发者工具勾选「不校验合法域名」）
const API_BASE_URL = 'http://118.89.69.177/api/mobile';

// 正式上线（服务器必须配置 HTTPS）
// const API_BASE_URL = 'https://你的域名.com/api/mobile';
```

### 2. 导入微信开发者工具

1. 打开 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 点击「导入项目」
3. 选择 `miniprogram/` 文件夹
4. 填入你的小程序 AppID（在[微信公众平台](https://mp.weixin.qq.com/)注册获取）
5. 开发阶段勾选「不校验合法域名、TLS版本及HTTPS证书」
6. 点击「导入」

### 3. 真机调试

1. 点击开发者工具顶栏的「真机调试」
2. 用微信扫码即可在手机上运行

### 4. 正式上线（可选）

1. 服务器配置 SSL 证书（推荐 Let's Encrypt）
2. 将 `config.js` 中 `API_BASE_URL` 改为 HTTPS 地址
3. 在微信公众平台 → 开发管理 → 服务器域名，添加 API 域名白名单
4. 点击开发者工具右上角「上传」
5. 在微信公众平台提交审核发布

## 项目结构

```
miniprogram/
├── app.js              # 全局逻辑
├── app.json            # 全局配置
├── app.wxss            # 全局样式
├── config.js           # API 地址配置 ← 部署前修改
├── project.config.json # 项目配置（AppID 需修改）
├── sitemap.json
├── utils/
│   ├── api.js          # API 请求封装
│   └── util.js         # 工具函数
└── pages/
    ├── login/          # 登录页
    ├── orders/         # 工单列表页（三标签）
    └── order/          # 工单详情页
```
