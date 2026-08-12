from mcp.server.fastmcp import FastMCP
from datetime import date

from .store import MarkdownStore


def create_mcp_server(store: MarkdownStore) -> FastMCP:
    mcp = FastMCP(
        name="AI Agent 个人工作台",
        instructions=(
            "用于读取和更新用户的个人工作台。Markdown 是数据真源。"
            "只使用这里提供的工具，不要直接修改 Obsidian 文件。"
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    def connected() -> None:
        store.touch_hermes()

    @mcp.tool()
    def get_dashboard() -> dict:
        """读取任务、健康、个人成长、个人IP和最新建议的汇总。"""
        connected()
        return store.dashboard()

    @mcp.tool()
    def get_workbench_preferences() -> dict:
        """读取用户称呼、每日寄语风格、健康目标和个人IP关注方向。"""
        connected()
        return {
            "profile": store.get_profile_settings(),
            "health": store.get_health_goals(),
            "ip": store.get_ip_preferences(),
        }

    @mcp.tool()
    def save_daily_message(message: str, tone: str = "mixed", target_date: str | None = None) -> dict:
        """写入指定日期的个性化寄语。tone 为 encouraging、comforting 或 mixed。"""
        connected()
        return store.save_daily_message(message, tone, target_date, source="hermes")

    @mcp.tool()
    def list_tasks() -> list[dict]:
        """读取全部四象限任务及完成状态。"""
        connected()
        return store.list_tasks()

    @mcp.tool()
    def create_task(
        title: str,
        quadrant: str = "important_not_urgent",
        due_at: str | None = None,
        note: str = "",
        recurrence: str = "none",
    ) -> dict:
        """创建任务。recurrence 可为 none 或 yearly；每年固定出现的生日、纪念日用 yearly。"""
        connected()
        return store.create_task(title, quadrant, due_at, note, recurrence, source="hermes")

    @mcp.tool()
    def complete_task(task_id: str, done: bool = True, occurrence_date: str | None = None) -> dict:
        """完成或重新打开任务；每年重复任务应传 occurrence_date，仅影响当年这一次。"""
        connected()
        return store.update_task(task_id, {"done": done, "occurrence_date": occurrence_date}, source="hermes")

    @mcp.tool()
    def update_task(
        task_id: str,
        title: str | None = None,
        quadrant: str | None = None,
        due_at: str | None = None,
        note: str | None = None,
        recurrence: str | None = None,
    ) -> dict:
        """修改任务标题、四象限、日期、备注或重复规则。"""
        connected()
        updates = {
            key: value for key, value in {
                "title": title,
                "quadrant": quadrant,
                "due_at": due_at,
                "note": note,
                "recurrence": recurrence,
            }.items() if value is not None
        }
        return store.update_task(task_id, updates, source="hermes")

    @mcp.tool()
    def get_calendar(start_date: str, end_date: str) -> dict:
        """读取指定周期内的任务、农历传统节日、二十四节气、法定放假和调休上班日。"""
        connected()
        return store.calendar(date.fromisoformat(start_date), date.fromisoformat(end_date))

    @mcp.tool()
    def list_projects() -> list[dict]:
        """读取项目当前阶段、进度、下一里程碑和截止日期。"""
        connected()
        return store.list_projects()

    @mcp.tool()
    def create_project(
        name: str,
        current_stage: str = "准备中",
        progress_percent: int = 0,
        next_milestone: str = "",
        due_date: str | None = None,
    ) -> dict:
        """创建一个需要持续跟进的项目。"""
        connected()
        return store.create_project(
            name, current_stage, progress_percent, next_milestone, due_date, source="hermes"
        )

    @mcp.tool()
    def update_project(
        project_id: str,
        current_stage: str | None = None,
        progress_percent: int | None = None,
        next_milestone: str | None = None,
        due_date: str | None = None,
        status: str | None = None,
    ) -> dict:
        """根据用户近期进展更新项目，并让新阶段实时显示在工作台。"""
        connected()
        updates = {
            key: value for key, value in {
                "current_stage": current_stage,
                "progress_percent": progress_percent,
                "next_milestone": next_milestone,
                "due_date": due_date,
                "status": status,
            }.items() if value is not None
        }
        return store.update_project(project_id, updates, source="hermes")

    @mcp.tool()
    def record_water(ml: int) -> dict:
        """按毫升记录一次饮水，不使用固定八杯规则。"""
        connected()
        return store.record_water(ml, source="hermes")

    @mcp.tool()
    def record_weight(kg: float) -> dict:
        """按公斤记录当前体重。"""
        connected()
        return store.record_weight(kg, source="hermes")

    @mcp.tool()
    def update_health_goals(
        gender: str,
        height_cm: float,
        current_weight_kg: float,
        target_weight_kg: float,
        cup_ml: int = 250,
        age: int | None = None,
        activity_level: str | None = None,
    ) -> dict:
        """更新减重基础信息并自动估算热量区间、每周运动量、饮水量；活动量可选 sedentary、light、moderate、active。"""
        connected()
        result = store.update_health_goals(
            gender,
            height_cm,
            current_weight_kg,
            target_weight_kg,
            cup_ml,
            age,
            activity_level,
            source="hermes",
        )
        store.record_weight(current_weight_kg, source="hermes")
        return result

    @mcp.tool()
    def create_learning_plan(name: str, goal: str = "") -> dict:
        """创建一个待规划的新技能学习计划。"""
        connected()
        return store.create_learning_plan(name, goal, source="hermes")

    @mcp.tool()
    def update_learning_plan(
        plan_id: str,
        roadmap_markdown: str,
        status: str = "active",
        total_lessons: int = 0,
        completed_lessons: int = 0,
    ) -> dict:
        """为已有学习计划写入分阶段路线、课时数和学习进度。"""
        connected()
        return store.update_learning_plan(
            plan_id,
            roadmap_markdown,
            status,
            total_lessons,
            completed_lessons,
            source="hermes",
        )

    @mcp.tool()
    def get_learning_plan(plan_id: str) -> dict:
        """读取一个学习计划的目标、进度、AI Agent任务状态、Markdown路线和学习资源。"""
        connected()
        return store.get_learning_plan(plan_id)

    @mcp.tool()
    def list_pending_jobs(limit: int = 20) -> list[dict]:
        """列出等待 AI Agent 处理的寄语、规划、学习、健康、书影音讨论和内容刷新任务。"""
        connected()
        return store.list_agent_jobs(status="pending", limit=limit)

    @mcp.tool()
    def claim_job(job_id: str) -> dict:
        """领取一个待处理任务，使工作台向用户显示 AI Agent 正在处理。"""
        connected()
        return store.claim_agent_job(job_id, source="hermes")

    @mcp.tool()
    def complete_job(job_id: str, result_summary: str = "", succeeded: bool = True) -> dict:
        """完成或标记失败一个 AI Agent 任务。学习计划写回成功时会自动完成对应任务。"""
        connected()
        return store.complete_agent_job(job_id, result_summary, succeeded, source="hermes")

    @mcp.tool()
    def list_pending_health_records(limit: int = 20) -> list[dict]:
        """列出等待分析的饮食、体重秤和运动报告图片；饮食记录会包含 record_date、meal_slot、meal_label，asset 是 Obsidian 工作台内的相对路径。"""
        connected()
        return store.list_health_records(status="queued", limit=limit)

    @mcp.tool()
    def list_health_records(record_date: str | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
        """读取健康图片记录；传 record_date 可读取某一天已分析的饮食、体重和运动记录。"""
        connected()
        records = store.list_health_records(status=status, limit=limit)
        if record_date:
            records = [item for item in records if item.get("record_date") == record_date]
        return records

    @mcp.tool()
    def get_health_history(start_date: str, end_date: str) -> dict:
        """读取一个周期的健康统计和每日卡片；可用同一天作为起止日期重做当天总结。"""
        connected()
        return store.health_history(
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )

    @mcp.tool()
    def update_health_record(record_id: str, record_date: str | None = None, meal_slot: str | None = None) -> dict:
        """纠正一条健康图片记录的日期或餐次；修改后会生成需要重做全天总结的任务。"""
        connected()
        return store.update_health_record(record_id, record_date, meal_slot, source="hermes")

    @mcp.tool()
    def analyze_health_record(
        record_id: str,
        summary: str,
        advice: str = "",
        calories_kcal: int | None = None,
        exercise_kcal: int | None = None,
        weight_kg: float | None = None,
    ) -> dict:
        """回写图片分析。饮食传 calories_kcal，运动报告传 exercise_kcal，体重秤传 weight_kg。"""
        connected()
        return store.analyze_health_record(
            record_id,
            summary,
            advice,
            calories_kcal,
            exercise_kcal,
            weight_kg,
            source="hermes",
        )

    @mcp.tool()
    def save_daily_health_advice(
        summary: str = "",
        status: str = "neutral",
        target_date: str | None = None,
        overall_summary: str = "",
        diet_summary: str = "",
        hydration_summary: str = "",
        exercise_summary: str = "",
    ) -> dict:
        """按分段结构写入每日健康建议。每餐建议由 analyze_health_record 保存；这里填写全天 overall_summary、diet_summary、hydration_summary、exercise_summary。status 可为 on_track、attention、celebrate、neutral。summary 仅用于兼容旧格式。"""
        connected()
        return store.save_daily_health_advice(
            summary,
            status,
            target_date,
            source="hermes",
            overall_summary=overall_summary,
            diet_summary=diet_summary,
            hydration_summary=hydration_summary,
            exercise_summary=exercise_summary,
        )

    @mcp.tool()
    def save_library_item(title: str, kind: str, reason: str = "", status: str = "want") -> dict:
        """把推荐书籍、电影或纪录片保存到成长专栏。kind 为 book、movie 或 documentary。"""
        connected()
        return store.create_library_item(title, kind, reason, status, source="hermes")

    @mcp.tool()
    def update_library_item(
        item_id: str,
        status: str | None = None,
        reflection: str | None = None,
        agent_comment: str | None = None,
        progress_percent: int | None = None,
        current_position: str | None = None,
        organized_notes: str | None = None,
    ) -> dict:
        """更新阅读/观影进度，回应用户心得，并把讨论整理为笔记。"""
        connected()
        return store.update_library_item(
            item_id,
            status,
            reflection,
            agent_comment,
            progress_percent,
            current_position,
            organized_notes,
            source="hermes",
        )

    @mcp.tool()
    def get_library_item(item_id: str) -> dict:
        """读取一个书籍、电影或纪录片的进度、用户心得、AI Agent意见和整理笔记。"""
        connected()
        return store.get_library_item(item_id)

    @mcp.tool()
    def save_content_item(
        title: str,
        category: str,
        source_url: str = "",
        summary: str = "",
        details_markdown: str = "",
        media_url: str = "",
        thumbnail_url: str = "",
        platform: str = "",
    ) -> dict:
        """保存今日资讯、短视频热点或选题灵感；资讯主题由用户的关注方向决定。"""
        connected()
        return store.save_content_item(
            title,
            category,
            source_url,
            summary,
            details_markdown,
            media_url,
            thumbnail_url,
            platform,
            source="hermes",
        )

    @mcp.tool()
    def get_content_item(item_id: str) -> dict:
        """读取热点或资讯的完整详情、来源和媒体地址。"""
        connected()
        return store.get_content_item(item_id)

    @mcp.tool()
    def save_suggestion(title: str, content: str, action_label: str = "") -> dict:
        """把建议写入工作台，供电脑和手机实时显示。"""
        connected()
        return store.save_suggestion(title, content, action_label, source="hermes")

    @mcp.tool()
    def rebuild_search_index() -> dict:
        """从 Markdown 重新构建可丢弃的 SQLite 搜索索引。"""
        connected()
        return store.rebuild_index()

    return mcp
