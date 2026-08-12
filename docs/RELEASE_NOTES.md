# AI Agent 个人工作台 v0.3.0-alpha.5

这是补齐历史体重录入、单条手动体重删除/恢复和安全演示流程的公开预发布安装版。项目仍处于 Alpha 阶段，适合自托管体验、测试和反馈；保存重要数据前请先建立备份方案。

## 下载安装

- [中文发行版安装指南](https://github.com/theonlymoon919/ai-agent-personal-workbench/blob/v0.3.0-alpha.5/docs/RELEASE_INSTALL.zh-CN.md)
- [完整中文安装与使用说明书](https://github.com/theonlymoon919/ai-agent-personal-workbench/blob/v0.3.0-alpha.5/docs/USER_GUIDE.zh-CN.md)
- 服务器镜像：`ghcr.io/theonlymoon919/ai-agent-personal-workbench:0.3.0-alpha.5`
- Android：下载本 Release 中的 APK，并使用同名 `.sha256` 文件核对校验值。

如果 GitHub 仓库未配置维护者 Android 正式签名 Secrets，Android 文件名会明确带有 `-debug.apk`，属于 GitHub CI 构建并验证的测试安装包，不是应用商店正式签名版。

## 重要说明

- APK 是工作台的手机访问外壳，不包含服务器；首次使用必须填写你自己的 HTTP/HTTPS 工作台地址。
- 仅在电脑本地使用时可打开 `http://localhost:8787`；手机远程访问建议部署自己的 HTTPS 域名。
- AI Agent 是可选接入。生成课程、分析健康图片、联网整理今日资讯等能力需要连接兼容 MCP 且具备相应模型/工具能力的 Agent。
- 项目不内置微信、飞书或 QQ 连接器；已经接入这些渠道的 Agent 可以通过 MCP 使用工作台。
- 本 Release、演示和测试只包含合成数据，不包含维护者的正式服务器、账号、Token、数据库、附件或签名材料。

## 本版重点

- `record_weight` 支持通过 `record_date` 补录历史日期，并拒绝未来日期；
- 新增 `list_weight_entries`、`delete_weight_entry` 和 `restore_weight_entry`；
- 删除手动体重必须先查看只读确认摘要，再按准确 ID 软删除单条记录；同日饮水和健康图片不受影响；
- 网页快速记录体重可选择历史日期；
- Hermes 技能和提示词明确要求演示使用独立账号、工作空间、浏览器配置和 Hermes Profile；
- 新增中文录像演示安全工作流，禁止为演示删除、隐藏或改写真实工作空间；
- 隐私清理后的独立 Apache-2.0 开源发行；
- Docker 本地安装、GHCR 镜像与 Ubuntu HTTPS 部署；
- 首位管理员初始化、邀请、多租户隔离和用户数据控制；
- MCP Agent 接入及 Hermes 参考安装器；
- 健康图片交接、学习计划、任务、项目、财务、书影音、今日资讯和短视频热点；
- 电脑端“今日资讯”导航与新版合成数据 Demo；
- 前端、后端、Android、数据库迁移、首次部署与隐私 CI。
