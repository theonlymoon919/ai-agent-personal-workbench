# AI Agent 个人工作台 v0.3.0-alpha.4

这是修复 Hermes 财务删除能力的公开预发布安装版。网页端原本已经支持财务流水软删除和恢复，但 Hermes MCP 没有暴露对应工具；本版补齐了完整、安全且可恢复的聊天操作流程。项目仍处于 Alpha 阶段，适合自托管体验、测试和反馈；保存重要数据前请先建立备份方案。

## 下载安装

- [中文发行版安装指南](https://github.com/theonlymoon919/ai-agent-personal-workbench/blob/v0.3.0-alpha.4/docs/RELEASE_INSTALL.zh-CN.md)
- [完整中文安装与使用说明书](https://github.com/theonlymoon919/ai-agent-personal-workbench/blob/v0.3.0-alpha.4/docs/USER_GUIDE.zh-CN.md)
- 服务器镜像：`ghcr.io/theonlymoon919/ai-agent-personal-workbench:0.3.0-alpha.4`
- Android：下载本 Release 中的 APK，并使用同名 `.sha256` 文件核对校验值。

当前 GitHub 仓库尚未配置维护者 Android 正式签名 Secrets，因此本次 Android 文件名明确带有 `-debug.apk`，属于 GitHub CI 构建并验证的测试安装包，不是应用商店正式签名版。

## 重要说明

- APK 是工作台的手机访问外壳，不包含服务器；首次使用必须填写你自己的 HTTP/HTTPS 工作台地址。
- 仅在电脑本地使用时可打开 `http://localhost:8787`；手机远程访问建议部署自己的 HTTPS 域名。
- AI Agent 是可选接入。生成课程、分析健康图片、联网整理今日资讯等能力需要连接兼容 MCP 且具备相应模型/工具能力的 Agent。
- 项目不内置微信、飞书或 QQ 连接器；已经接入这些渠道的 Agent 可以通过 MCP 使用工作台。
- 本 Release、演示和测试只包含合成数据，不包含维护者的正式服务器、账号、Token、数据库、附件或签名材料。

## 本版重点

- Hermes 可以查询财务流水、软删除错误流水并从回收站恢复；
- Hermes 可以查询并归档财务预算；
- 流水删除和预算归档都必须先返回只读确认摘要，由用户核对日期、金额、账户、用途或预算周期后明确确认；
- 账户与分类继续采用停用而非硬删除，避免破坏历史账目；
- 项目、网页、Android、说明书与 GitHub 仓库统一升级为“AI Agent 个人工作台”；
- 隐私清理后的独立 Apache-2.0 开源发行；
- Docker 本地安装、GHCR 镜像与 Ubuntu HTTPS 部署；
- 首位管理员初始化、邀请、多租户隔离和用户数据控制；
- MCP Agent 接入及 Hermes 参考安装器；
- 健康图片交接、学习计划、任务、项目、财务、书影音、今日资讯和短视频热点；
- 电脑端“今日资讯”导航与新版合成数据 Demo；
- 前端、后端、Android、数据库迁移、首次部署与隐私 CI。
