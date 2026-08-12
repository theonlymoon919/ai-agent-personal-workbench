# AI Agent 个人工作台发行版安装指南

本指南面向第一次接触“AI Agent 个人工作台”的普通用户。当前版本是 `v0.3.0-alpha.4` 预发布测试版，重要数据请自行备份。

## 先理解三个组成部分

1. **AI Agent 个人工作台服务器**保存你的任务、健康、学习、财务、今日资讯和附件，是必须先安装的主体。
2. **网页和 Android APK**只是访问工作台的界面。APK 本身不是服务器，不能脱离工作台地址单独保存数据。
3. **AI Agent**是可选能力。接入兼容 MCP 的 Agent 后，才能生成课程、分析健康图片、搜索并整理今日资讯等。

只想在一台电脑上体验时，安装本地工作台即可；希望手机在外网访问时，需要部署自己的 HTTPS 地址。

## 方式一：在电脑本地安装

### 准备软件

- Docker Desktop（Windows/macOS）或 Docker Engine + Compose v2（Linux）；
- Python 3.10 或更新版本；
- Git，或者从 GitHub Release 下载并解压 Source code；
- 首次构建建议至少预留 2 GB 内存。

### 下载并启动

使用 Git：

```bash
git clone --branch v0.3.0-alpha.4 https://github.com/theonlymoon919/ai-agent-personal-workbench.git
cd ai-agent-personal-workbench
python scripts/generate_env.py
docker compose up -d --build
docker compose ps
```

如果下载的是 GitHub Release 自动提供的源码压缩包，请解压并在解压目录运行后三条命令。Windows 找不到 `python` 时可改用 `py`。

浏览器打开：

```text
http://localhost:8787
```

第一次打开会要求创建首位管理员。用户名、昵称和密码由你自己设置，初始化成功后该入口永久关闭。

### 使用预构建镜像

运行 `generate_env.py` 后，打开本机私密的 `.env` 文件，把最后两项改成：

```dotenv
WORKBENCH_IMAGE=ghcr.io/theonlymoon919/ai-agent-personal-workbench
WORKBENCH_IMAGE_TAG=0.3.0-alpha.4
```

然后运行：

```bash
docker compose pull
docker compose up -d --no-build
```

`.env` 内含随机数据库密码和服务器密钥，禁止上传、截图或发送给别人。

## 方式二：在手机使用

### 手机浏览器

需要先把工作台部署到你自己控制的 HTTPS 域名。完成后，直接在手机浏览器打开：

```text
https://你的工作台域名
```

不要把本地电脑的 `localhost` 填到手机里；手机上的 `localhost` 指向手机自身。

### Android APK

1. 在 GitHub Release 下载 APK 和同名 `.sha256` 文件；
2. 核对 SHA-256 后安装 APK；
3. 打开“连接设置”；
4. 填写 `https://你的工作台域名`，不要添加 `/mcp/`；
5. 登录你自己的工作台账号。

文件名以 `-debug.apk` 结尾的是 GitHub CI 生成并验证的 Alpha 测试安装包，使用 Android 调试签名，不是应用商店正式签名版。Android 8.0（API 26）或更新版本可安装。

Windows 可使用 `Get-FileHash <APK文件> -Algorithm SHA256`，Linux/macOS 可使用 `sha256sum <APK文件>`；结果必须与 `.sha256` 文件中的值完全一致。

## 接入 AI Agent

在“我的 → 账号与 AI Agent”生成当前用户自己的 Agent Token，并复制页面显示的 MCP 地址。典型格式为：

```text
https://你的工作台域名/mcp/
Authorization: Bearer <只显示一次的 Agent Token>
```

Token 只能访问对应用户的工作空间。请保存在 Agent 的 Secret Store 或私密环境变量中，不能写入源码、聊天、截图或公开配置。

项目不内置微信、飞书、QQ 等聊天连接器；已经接入这些渠道的兼容 Agent，可以再通过 MCP 使用 AI Agent 个人工作台。Hermes 是当前完整验证过的参考接入之一，并非唯一选择。

## 安装后检查

- 能打开页面并创建首位管理员；
- 能登录、创建任务并刷新页面；
- 手机使用时，HTTPS 证书有效；
- Android APK 能连接自己的工作台地址；
- 如接入 Agent，MCP 调用能读回当前用户的工作空间；
- 没有把 `.env`、Agent Token、数据库或附件上传到 GitHub。

## 停止、升级和备份

停止与重新启动：

```bash
docker compose stop
docker compose start
```

升级前必须同时备份 PostgreSQL 与私有附件卷，并阅读对应版本的 Release Notes。不要运行 `docker compose down -v`，除非你明确准备永久删除数据库和附件。

更完整的手机、HTTPS、Agent、Hermes、备份和故障排查说明见[《中文安装与使用说明书》](https://github.com/theonlymoon919/ai-agent-personal-workbench/blob/v0.3.0-alpha.4/docs/USER_GUIDE.zh-CN.md)。
