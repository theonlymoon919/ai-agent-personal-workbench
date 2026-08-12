# AI Agent 个人工作台：中文安装与使用说明书

这份说明书面向第一次接触 AI Agent 个人工作台的普通用户。你不需要预先了解 Docker、MCP 或 Hermes；先选择自己的使用方式，再按对应步骤操作即可。

AI Agent 个人工作台是用户自己的长期记录和行动系统。它可以单独使用，也可以连接 AI Agent。工作台负责保存、展示、修改、删除和导出数据；AI Agent 负责理解图片、生成课程、联网查找热点等智能处理。

## 一、先选择使用方式

| 你想怎么用 | 工作台地址 | 是否必须配置 Agent | 适合谁 |
| --- | --- | --- | --- |
| 只在当前电脑使用 | `http://localhost:8787` | 否 | 想先体验记录、日历、健康、学习和财务管理 |
| 当前电脑同时连接通用 Agent | `http://localhost:8787/mcp/` | 是 | Agent 与工作台在同一台电脑，且 Agent 支持本地 HTTP MCP |
| 手机浏览器或 Android 使用 | 自己的 `https://工作台域名` | 否 | 希望随时用手机查看和管理数据 |
| 手机聊天端通过任意 Agent 使用 | 自己的 HTTPS 工作台、MCP 地址和 Agent Token | 是 | 已经把微信、飞书、QQ 等聊天渠道接入某个 Agent |
| 使用 Hermes 参考集成 | 自己的 HTTPS 工作台和 Agent Token | 是 | Windows 上已经安装并能正常运行 Hermes |

需要特别注意：

- 手机不需要安装 Agent 才能使用工作台。手机浏览器或 Android 客户端可以直接连接工作台。
- `localhost` 只代表当前设备。手机无法打开电脑上的 `http://localhost:8787`。
- 当前 Docker 本地配置只监听电脑自身的 `127.0.0.1`。需要手机访问时，请部署自己的 HTTPS 地址，不要直接把本地端口暴露到公网。
- 项目不提供公共服务器，也不会默认连接维护者的服务器。每位部署者都使用自己的地址、账号和数据。

## 二、工作台单独能做什么

不连接 Agent 时，仍然可以使用以下功能：

- 创建和管理任务、项目、阶段、四象限及日历事项；
- 记录体重、饮水，上传饮食或运动图片，查看长期健康历史；
- 创建学习计划名称和目标，记录学习进度；
- 管理书籍、电影、纪录片和自己的心得；
- 管理财务账户、分类、收支、转账、预算和储蓄目标；
- 设置个人关注方向，查看已经保存的资讯；
- 邀请其他用户、导出自己的数据、修改或删除记录。

以下能力需要一个已经接入的 AI Agent：

| 功能 | 没有 Agent | 接入具备相应能力的 Agent 后 |
| --- | --- | --- |
| 学习计划 | 保存目标并进入待处理队列 | 根据目标和偏好生成分阶段课程，核验并写入学习资源 |
| 健康图片 | 保存原图和记录 | 查看图片，写回有依据的分析与建议 |
| 短视频热点和今日资讯 | 查看已有内容 | 根据关注方向联网搜索、核验来源并刷新内容 |
| 每日建议和长期跟进 | 保存用户数据 | 跨会话读取历史，生成并写回持续建议 |
| 聊天中记录 | 通过网页手动填写 | Agent 通过 MCP 读取或写入当前用户的工作空间 |

工作台自带的后台 Worker 负责周期财务规则和账户删除等确定性任务，但不会冒充 AI 模型生成课程、分析图片或编造热点。没有 Agent 时，相关任务会显示为“等待 AI Agent 处理”。

## 三、在电脑上本地安装

### 3.1 准备软件

需要：

- Git；
- Docker Desktop，或包含 Docker Compose v2 的 Docker Engine；
- Python 3.10 或更新版本；
- 首次构建建议至少预留 2 GB 内存。

Windows 用户安装 Docker Desktop 后，应确认 Docker Desktop 已经启动。Linux 用户可运行 `docker compose version` 检查 Compose v2。

### 3.2 下载并启动

```bash
git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git
cd ai-agent-personal-workbench
python scripts/generate_env.py
docker compose up -d --build
docker compose ps
```

Windows 如果找不到 `python`，可以使用：

```powershell
py scripts\generate_env.py
docker compose up -d --build
docker compose ps
```

`generate_env.py` 会在本地创建 `.env`，其中是随机生成的数据库密码和服务器密钥。不要把这个文件发送给别人，也不要提交到 GitHub。

### 3.3 第一次打开

浏览器访问：

```text
http://localhost:8787
```

空数据库会显示一次性的“创建首位管理员”页面。请设置：

1. 3–80 个非空白字符的用户名；
2. 工作台显示的昵称；
3. 至少 12 个字符、没有在其他网站重复使用的密码。

创建成功后，首次初始化入口永久关闭。不要把尚未初始化的公网工作台长期暴露给陌生人。

如果页面无法打开，可检查：

```bash
docker compose ps
docker compose logs --tail=100 workbench worker postgres
curl http://localhost:8787/api/cloud/health
```

## 四、首次进入后的操作

### 4.1 创建自己的基础资料

先在设置中填写关注方向、健康目标和常用信息。Agent 以后会读取这些用户可见资料，而不是依赖不可检查的聊天记忆。

### 4.2 邀请其他用户

首位管理员可以在“我的 → 账号与 AI Agent”创建一次性邀请链接。被邀请者自己设置用户名、昵称和密码，并拥有完全独立的工作空间。

邀请链接属于临时凭据，只通过可信私密渠道发送。不同用户不要共用账号或 Agent Token。

### 4.3 创建 Agent Token

只有准备接入 Agent 时才需要 Token。在“我的 → 账号与 AI Agent”中创建 Agent Token：

- Token 只显示一次；
- 一个 Token 只对应当前用户的工作空间；
- 重新生成后，旧 Token 立即失效；
- Token 只能存入 Agent 的 Secret Store 或私密环境，不能放进聊天、截图、源码或公开配置。

## 五、在本地电脑接入通用 Agent

如果 Agent 与工作台运行在同一台电脑，并且 Agent 支持本地 HTTP 的 MCP Streamable HTTP，可使用：

```text
MCP 地址：http://localhost:8787/mcp/
Authorization：Bearer <当前用户的 Agent Token>
```

不同 Agent 的配置格式不完全相同，所需信息通常等价于：

```json
{
  "mcpServers": {
    "personal-workbench": {
      "url": "http://localhost:8787/mcp/",
      "headers": {
        "Authorization": "Bearer ${MCP_PERSONAL_WORKBENCH_API_KEY}"
      }
    }
  }
}
```

确认 Agent 能在请求头中引用私密环境变量。如果不能，请使用该 Agent 自己的 Secret Store，不要把真实 Token 写进可提交的 JSON 或 YAML。

要完整体验智能功能，Agent 还需要相应能力：

- 生成和核验课程：需要联网搜索或浏览网页；
- 抓取热点：需要联网搜索、打开来源页面并核验链接；
- 分析健康图片：需要读取工作台私有图片和使用视觉理解能力；
- 自动处理队列：需要领取 `claim_next_agent_job`，完成后调用 `complete_agent_job`。

仅仅“支持 MCP”不代表一定具备搜索、浏览器或图片理解能力，请以该 Agent 产品的权限和工具为准。

## 六、让手机访问工作台

手机不能使用电脑的 `localhost`。推荐把工作台部署到自己的服务器和域名，并启用 HTTPS。

### 6.1 准备条件

- 一台新的 Ubuntu 24.04 服务器；
- 一个由你控制的域名；
- 域名的 DNS A/AAAA 记录已经指向服务器；
- 服务器允许公网访问 80 和 443 端口；
- 一个可信的服务器管理员会话。

### 6.2 Ubuntu HTTPS 部署

以下命令中的 `workbench.example.com` 必须替换为你自己的域名：

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git ~/personal-workbench-bootstrap
cd ~/personal-workbench-bootstrap
sudo sh deploy/bootstrap-ubuntu.sh
sudo git clone https://github.com/theonlymoon919/ai-agent-personal-workbench.git /opt/personal-workbench
cd /opt/personal-workbench
sudo python3 scripts/generate_env.py \
  --output .env.cloud \
  --origin https://workbench.example.com \
  --domain workbench.example.com
sudo docker compose --env-file .env.cloud -f compose.yaml -f compose.cloud.yaml up -d --build
```

Caddy 会申请和续期 TLS 证书。PostgreSQL 不对公网开放，应用端口仍绑定服务器回环地址；公网只应开放 80 和 443。

第一次 HTTPS 页面可访问后，应立即创建首位管理员。在完成初始化前，尽量把网络访问限制在可信管理员范围内。

### 6.3 手机浏览器

在手机浏览器打开：

```text
https://你的工作台域名
```

登录自己的账号即可使用。手机浏览器不要求配置 Agent。

### 6.4 Android 客户端

从 GitHub Release 下载 APK 时必须同时核对 SHA-256 校验值。文件名以 `-debug.apk` 结尾的是 CI 生成的 Alpha 测试安装包，使用 Android 调试签名，不等同于维护者正式签名版；也可以自行按 [Android 构建说明](android.md)生成调试 APK。打开 Android 客户端的“连接设置”，填写：

```text
https://你的工作台域名
```

不要填写 `/mcp/`，也不要使用其他人的账号或 Token。Android 连接工作台本身不需要 Agent。

## 七、手机聊天端通过其他 Agent 使用

AI Agent 个人工作台不内置微信、飞书、QQ、Slack 或邮件连接器，但任何已经接入这些渠道的兼容 Agent，都可以通过 MCP 使用工作台：

```text
手机聊天端
  → 用户选择的 Agent
  → HTTPS MCP + 当前用户的 Agent Token
  → AI Agent 个人工作台
```

需要同时满足：

1. Agent 能访问用户自己的 HTTPS 工作台；
2. Agent 支持 MCP Streamable HTTP，或自行实现兼容的认证调用；
3. Agent 能把 Token 保存在私密环境；
4. Agent 的请求使用 `Authorization: Bearer <Agent Token>`；
5. 如果需要分析或上传聊天图片，聊天渠道必须把真实附件内容或可用缓存路径交给 Agent。

通用公网 MCP 地址为：

```text
https://你的工作台域名/mcp/
```

文字类任务、日历、财务和学习功能通常只需要标准 MCP。聊天图片上传还取决于 Agent 是否能取得附件并调用认证上传流程；不能取得附件时，应明确说明是附件交接受阻，不能假装上传成功。

## 八、使用 Hermes 参考集成

Hermes 不是工作台的必需组件。参考安装器面向已经安装 Hermes 的 Windows 用户，并且只接受用户自己的 HTTPS 工作台地址。

准备：

1. Windows 当前用户已经能正常运行 Hermes；
2. 工作台已经部署到自己的 HTTPS 地址；
3. 当前工作台用户已经生成 Agent Token；
4. 仓库的 `scripts`、`docs` 和 `hermes` 目录保持完整。

在仓库的 `scripts` 目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_hermes_workbench.ps1 `
  -WorkbenchUrl "https://workbench.example.com"
```

把示例地址替换为用户自己的地址。出现隐藏令牌提示后粘贴 Agent Token；输入过程不会显示字符。安装器会配置 MCP、持久聊天技能、附件路径交接、健康图片上传桥接和后台任务连接器。

如果当前 Hermes 已经存在有效的 `personal_workbench` MCP 和私密 Token，可以运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_hermes_workbench.ps1 `
  -WorkbenchUrl "https://workbench.example.com" `
  -ReuseExistingConnection
```

完成后重启 Hermes，并验证：

1. 要求 Hermes 使用 `personal_workbench` 读取工作台概览；
2. 创建一条无敏感信息的测试任务，确认 Hermes 能读取；
3. 发送一张无敏感信息的运动截图并明确要求上传；
4. 只有返回记录 ID，且 MCP 能重新读取记录和原图，才算成功。

完整细节见 [Hermes 参考接入](integrations/hermes.md)。

## 九、停止、重启和升级

本地部署常用命令：

```bash
docker compose stop
docker compose start
docker compose pull
docker compose up -d --build
```

公网部署升级前：

1. 同时备份 PostgreSQL 和私有附件；
2. 阅读 Release Notes 和迁移说明；
3. 固定要使用的版本标签或提交；
4. 执行 Compose 更新；
5. 验证登录、附件、MCP 和租户隔离。

除非明确准备永久删除数据库和私有附件卷，否则不要运行：

```text
docker compose down -v
```

数据库与私有附件必须来自同一个备份时间点。仅备份数据库或仅备份附件都不完整。详细说明见 [部署与备份](deployment.md#backup-export-and-recovery)。

## 十、常见问题

### 页面打不开

```bash
docker compose ps
docker compose logs --tail=100 workbench worker postgres
```

确认 Docker 已启动，`workbench` 和 `postgres` 状态正常，并检查健康接口。

### 手机打不开电脑上的地址

手机的 `localhost` 指向手机自己。当前本地模式也只监听电脑回环地址。请使用自己的 HTTPS 部署，不要直接公开本地 Docker 端口。

### 学习计划一直显示等待处理

说明工作台已经创建 Agent 任务，但没有 Agent 领取，或者 Agent 缺少队列权限。工作台本身不会调用隐藏模型自动生成内容。

### 图片已上传但没有分析

原图保存与 AI 分析是两个阶段。确认 Agent 已连接、支持视觉理解，并能调用 `load_health_image` 和分析写回工具。

### 热点没有自动刷新

确认 Agent 已连接且拥有联网搜索或浏览器能力。Agent 必须打开实际来源页面并写回可验证链接；工作台不会伪造热点。

### Agent 返回 401

Token 可能无效、已轮换或属于其他工作空间。在当前用户页面重新生成 Token，并更新 Agent 的私密配置。不要在聊天中发送 Token。

### HTTPS 证书无法申请

检查 DNS 是否已经指向服务器、80/443 端口是否开放、域名是否写错，并查看 Caddy 日志。不要用维护者示例域名作为实际地址。

## 十一、隐私与安全清单

- 不把 `.env`、密码、Agent Token、邀请链接、Cookie 或数据库上传到 GitHub；
- 不公开健康图片、财务数据、聊天附件缓存或包含个人信息的日志；
- 每个用户使用自己的账号和 Agent Token；
- 公网部署只开放 HTTPS，不开放 PostgreSQL；
- 初始化完成前限制陌生人访问；
- 定期同时备份数据库与私有附件，并在隔离环境测试恢复；
- 泄露 Token 后立即轮换，泄露密码后立即修改；
- 分享故障日志前删除用户名、Token、健康和财务信息以及本地路径。

更多边界见 [隐私与安全](privacy-and-security.md)。

## 十二、第一次使用检查表

- [ ] 已选择本地模式或自己的 HTTPS 部署
- [ ] 已生成私密 `.env`，没有复制其他人的配置或数据
- [ ] Docker 服务与健康接口正常
- [ ] 已创建首位管理员并保存好密码
- [ ] 如需多人使用，已通过一次性邀请创建独立账号
- [ ] 如需智能功能，已为当前用户生成 Agent Token
- [ ] Agent Token 只保存在 Agent 的私密环境
- [ ] Agent 已验证 `get_workspace_overview`
- [ ] 如需课程或热点，Agent 具备联网搜索和来源核验能力
- [ ] 如需图片分析，Agent 具备附件读取和视觉理解能力
- [ ] 如需手机访问，已经使用自己的 HTTPS 地址
- [ ] 已了解升级前必须同时备份数据库和私有附件

## 十三、进一步阅读

- [三分钟快速开始](quick-start.md)
- [Linux、HTTPS、升级和备份](deployment.md)
- [通用 Agent / MCP 接入](agent-integration.md)
- [Hermes 参考接入](integrations/hermes.md)
- [Android 构建与安装](android.md)
- [隐私与安全](privacy-and-security.md)
- [项目架构](../ARCHITECTURE.md)
- [安全问题报告](../SECURITY.md)
