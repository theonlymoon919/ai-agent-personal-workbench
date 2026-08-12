---
name: personal-workbench
description: Use when the user mentions 个人工作台、工作台、任务、长期项目、日历、健康记录、饮食图片、体重图片、运动截图、学习计划、书影音、热点资讯或财务记账，尤其是要求把微信、飞书、QQ 等聊天附件上传或写入工作台时。Load the current personal_workbench MCP workflow, use the official local health-image bridge for attachments, and never fall back to the retired localhost workbench.
license: Apache-2.0
metadata:
version: 1.2.0
  author: AI Agent Personal Workbench
  platforms: [windows]
  hermes:
    tags: [personal-workbench, mcp, health, image-upload, tasks, finance]
    related_skills: []
---

# AI Agent 个人工作台

## Overview

把 `personal_workbench` MCP 作为任务、项目、日历、健康、成长、资讯和财务数据的唯一入口。旧的 `127.0.0.1:8787` 工作台已经退役；不得启动、访问、迁移或重新配置旧工作台，也不得直接修改数据库、Markdown 或附件目录。

开始处理工作台事项时，调用 `skill_view(name="personal-workbench", file_path="references/operating-rules.md")` 读取完整模块规则。随后调用 `get_workspace_overview` 取得当前令牌所属工作空间的真实上下文。只处理当前用户数据，不跨租户访问。

## 聊天图片上传

当用户从微信、飞书、QQ 或其他 Hermes 聊天端发送饮食、体重、运动图片，并明确要求上传、保存或记录到工作台时，严格执行以下流程。

1. 从当前消息随附的系统说明中取得附件的真实本地缓存路径。路径必须指向本机已存在文件；不要把网页地址、图片描述、文件名猜测或 base64 当成本地路径。完成标准：使用 `Test-Path -LiteralPath` 确认文件存在。
2. 判断记录类型：饮食=`meal`、体重=`weight`、运动=`exercise`。饮食餐次仅使用 `breakfast`、`lunch`、`afternoon_tea`、`dinner`、`snack`、`late_night`；无法确定餐次时先询问，不猜测。
3. 调用官方桥接脚本。保留路径的原始字符，并始终用双引号包住完整路径：

```powershell
# 运动
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\PersonalWorkbench\upload_health_image.ps1" -Kind exercise -FilePath "附件完整路径"

# 体重
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\PersonalWorkbench\upload_health_image.ps1" -Kind weight -FilePath "附件完整路径"

# 饮食；按实际情况替换餐次
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\PersonalWorkbench\upload_health_image.ps1" -Kind meal -FilePath "附件完整路径" -MealSlot lunch
```

指定记录日期时追加 `-RecordDate "YYYY-MM-DD"`；用户未指定时使用当天。不要在命令、回复或日志中输出令牌。

4. 解析脚本返回的 JSON。只有 `ok=true` 且存在 `record_id` 才算上传成功。取得 `record_id` 后调用 `get_health_record` 与 `load_health_image` 验证记录和原图；需要分析时先查看原图，再使用 `update_health_record` 保存有证据的结果。
5. 向用户报告记录类型、日期和是否已保存。不要展示本地缓存路径、令牌或底层凭据。

用户只要求查看或分析图片、没有要求保存时，不得擅自上传。

## 失败处理

不要在检查前笼统回答“做不到”或“工作台不支持图片”。按实际失败阶段回答：

- 当前消息没有附件缓存路径：说明“工作台支持上传，但当前聊天端没有把附件缓存路径交给上传工具”，再请用户临时使用工作台“快速记录”。
- 路径存在但文件不存在：说明附件缓存已失效，请用户重新发送原图。
- 脚本不存在：说明本机工作台桥接组件缺失，需要重新运行 Hermes 工作台安装脚本。
- 身份验证失败：说明当前 Hermes 专属令牌无效或缺失，不得要求用户在聊天中发送密码或令牌。
- 云端拒绝、网络超时或 MCP 验证失败：报告工具返回的非敏感错误和可执行的重试建议，不得假装成功。

同一张图片的桥接上传带有幂等键；重试时继续使用原文件、类型、日期和餐次，避免产生重复记录。

## MCP 写入纪律

1. 写入前先读取并查重；用户只是咨询时先回答，不擅自写入。
2. 项目结构使用“项目 → 阶段 → 任务”；属于长期项目的任务同时填写 `project_id` 和 `phase_id`。
3. 记账前调用 `get_finance_reference_data`，使用真实账户和分类 ID；不猜金额。
4. 删除财务流水前先调用 `list_finance_transactions` 查找候选项。向用户复述日期、类型、金额、账户、商户或用途并取得明确同意；未确认时只调用 `delete_finance_transaction(..., confirmed=false)` 读取确认摘要，确认后才允许使用同一准确 ID 调用 `confirmed=true`。删除是可恢复的软删除，恢复时先查询包含回收站记录，再调用 `restore_finance_transaction`。
5. 归档预算前先调用 `list_finance_budgets`，复述周期、金额和分类并取得明确同意，再调用 `delete_finance_budget(..., confirmed=true)`。账户和分类只停用，不为清理历史账目而硬删除。
6. 手动录入体重时可向 `record_weight` 传 `record_date=YYYY-MM-DD` 补录历史日期，并保存返回的 `entry.id`。删除前先用 `list_weight_entries` 核对独立 ID、日期和数值，再取得明确同意；未确认时只调用 `delete_weight_entry(..., confirmed=false)`，确认后才传 `true`。该工具只删除一条手动体重，不会删除同日饮水或健康图片；误删使用 `restore_weight_entry`。
7. 修改、删除和恢复必须使用当前 MCP 提供的对应工具，不直接改存储文件。
8. 涉及来源、图片、日期、金额和完成状态时，以工具返回值为准；不确定就明确标注。

## 演示数据安全

用户提到“拍视频、演示、虚拟数据、样例数据、清空后恢复”时，不得删除、隐藏、改写或软删除当前真实工作空间的数据，也不得把“软删除记录”或“一份 ID 清单”称为备份。先明确说明演示必须使用独立的演示账号和工作空间；如当前令牌不是专用演示空间，停止写入并请用户切换。演示数据只写入专用空间，拍摄完成后整体停用或重建该空间，不对真实空间执行逐条回滚。

## Common Pitfalls

1. **只看到了图片内容就声称没有路径。** 检查当前消息中的附件缓存说明；安装器会将 Hermes 图片输入配置为包含本地路径的管线。
2. **把图片网页 URL 传给 `-FilePath`。** 桥接脚本只接受真实本地文件。
3. **上传成功但没有验证。** 必须取得 `record_id` 并通过 MCP 读取记录与原图。
4. **调用旧工作台。** 任何 `127.0.0.1:8787` 操作都已禁止。
5. **在技能里保存账号或隐私。** 技能只保存操作规则；凭据只能由 Hermes 私密环境管理。

## Verification Checklist

- [ ] 已读取完整工作台规则与工作空间概览
- [ ] 用户明确要求写入或上传
- [ ] 附件本地路径真实存在
- [ ] 类型、日期和餐次来自用户信息或明确确认
- [ ] 上传返回 `ok=true` 和 `record_id`
- [ ] 已通过 MCP 验证记录与原图
- [ ] 回复未泄露路径、令牌、密码或其他隐私
