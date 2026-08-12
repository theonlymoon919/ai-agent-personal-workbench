# AI Agent 个人工作台录像演示数据方案

这套流程用于拍摄产品演示视频。目标只有一个：**演示数据与真实数据永远不进入同一个工作空间**。

## 一、禁止采用的旧方案

不要在真实账号中执行“备份 → 删除真实数据 → 写入虚拟数据 → 逐条恢复”。软删除或一份记录 ID 清单都不是完整备份；图片、数据库和 Agent 任务也可能在演示期间继续变化。

## 二、安全方案

1. 新建专用账号，例如 `video_demo`，显示名使用“演示用户”；每个账号自动拥有独立工作空间。
2. 为演示账号单独签发 Agent Token，不与真实账号共用。
3. 用独立浏览器配置文件或无痕窗口登录演示账号。
4. 如需展示 Hermes，使用独立 Hermes Profile（独立 `HERMES_HOME`）连接演示 Token，不覆盖日常连接。
5. 写入前调用 `get_workspace_overview` 核对工作空间；不一致就停止。

密码和 Agent Token 只能保存到私密环境，不能放进视频、聊天、源码、命令参数或 GitHub。

## 三、建议演示内容

- 6–8 条四象限任务和 1 个三阶段项目；
- 最近 14 天的 5–7 个体重点、当日饮水和无个人信息的合成健康图片；
- 6–10 笔虚构财务流水；
- 1 个由 Agent 生成路径的学习目标；
- 2–3 个兴趣方向及带真实来源链接的今日资讯、短视频热点。

历史体重示例：

```text
record_weight(weight_kg=56.0, record_date="2026-07-30")
record_weight(weight_kg=55.6, record_date="2026-08-02")
record_weight(weight_kg=55.2, record_date="2026-08-05")
record_weight(weight_kg=54.7, record_date="2026-08-08")
record_weight(weight_kg=54.2, record_date="2026-08-10")
record_weight(weight_kg=53.8, record_date="2026-08-12")
```

保存每次返回的 `entry.id`。删除时先用 `list_weight_entries` 核对，再两步调用 `delete_weight_entry`；它不会删除同日饮水或健康图片。

## 四、拍摄与收尾

拍摄前确认昵称是“演示用户”、工作空间 ID 正确、画面中没有真实账号、消息、文件名、财务、健康图片、Token 或自动填充内容。手机与电脑连接同一个演示 HTTPS 工作台。

拍摄后首选停用或重建整个演示账号，不在真实空间中做逐条回滚。误删体重可用 `restore_weight_entry` 恢复。

## 五、发给 Agent 的安全指令

```text
这是视频演示任务。你只能操作当前专用的“演示用户”工作空间，禁止删除、隐藏、软删除或改写真实工作空间数据。先调用 get_workspace_overview，只有我确认它是演示空间后才继续。历史体重使用 record_weight 的 record_date 参数，并保存每条 entry.id。删除前必须列出准确候选、复述日期和数值并等待明确确认。软删除和 ID 清单都不能称为备份。
```
