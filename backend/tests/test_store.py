from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend.app.backup import BackupManager
from backend.app.store import MarkdownStore


class MarkdownStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = MarkdownStore(root / "vault", root / "cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_task_round_trip_and_activity_log(self) -> None:
        task = self.store.create_task("完成测试", "important_urgent")
        updated = self.store.update_task(task["id"], {"done": True})
        self.assertTrue(updated["done"])
        task_files = list((self.store.root / "📅 每日任务" / "记录").rglob("*.md"))
        self.assertEqual(len(task_files), 1)
        self.assertIn("title: 完成测试", task_files[0].read_text(encoding="utf-8"))
        log = next((self.store.root / "🤖 AI Agent" / "操作日志").glob("*.md"))
        self.assertEqual(log.read_text(encoding="utf-8").count("# 20"), 1)

    def test_calendar_expands_yearly_tasks_and_chinese_calendar_labels(self) -> None:
        task = self.store.create_task(
            "朋友生日",
            "important_not_urgent",
            "2026-09-05T09:00:00+08:00",
            "准备礼物",
            "yearly",
        )
        calendar = self.store.calendar(date(2026, 9, 1), date(2026, 10, 10))
        occurrence = next(item for item in calendar["tasks"] if item["id"] == task["id"])
        self.assertEqual(occurrence["occurrence_date"], "2026-09-05")
        self.assertEqual(occurrence["recurrence"], "yearly")
        national_day = next(item for item in calendar["days"] if item["date"] == "2026-10-01")
        self.assertEqual(national_day["official_holiday"]["kind"], "public_holiday")
        self.assertTrue(any(item["year"] == 2026 and item["status"] == "official" for item in calendar["holiday_notices"]))

        completed = self.store.update_task(
            task["id"],
            {"done": True, "occurrence_date": "2026-09-05"},
        )
        self.assertIn("2026-09-05", completed["completed_occurrences"])
        next_year = self.store.calendar(date(2027, 9, 5), date(2027, 9, 5))["tasks"][0]
        self.assertFalse(next_year["done"])
        deleted = self.store.delete_task(task["id"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.store.calendar(date(2026, 9, 5), date(2026, 9, 5))["tasks"], [])
        restored = self.store.restore_task(task["id"])
        self.assertFalse(restored["deleted"])

    def test_water_and_weight_are_stored_in_millilitres_and_kilograms(self) -> None:
        self.store.record_water(350)
        health = self.store.record_weight(60)
        self.assertEqual(health["water_ml"], 350)
        self.assertEqual(health["weight_kg"], 60)
        self.assertEqual(health["water_target_ml"], 2100)

    def test_uploaded_meal_can_be_analyzed_idempotently(self) -> None:
        record = self.store.upload_record("meal", "breakfast.png", b"fake-png")
        pending = self.store.list_health_records(status="queued")
        self.assertEqual([item["id"] for item in pending], [record["id"]])
        self.store.analyze_health_record(record["id"], "鸡蛋和面包", "午餐清淡一些", calories_kcal=420)
        self.assertEqual(self.store.health_summary()["calories_kcal"], 420)
        analyzed = self.store.list_health_records(status="analyzed")
        self.assertEqual(analyzed[0]["analysis_status"], "analyzed")

    def test_health_history_aggregates_markdown_and_analyzed_uploads(self) -> None:
        self.store.record_water(600)
        self.store.record_weight(58.5)
        meal = self.store.upload_record("meal", "lunch.png", b"fake-png", meal_slot="lunch")
        self.store.analyze_health_record(meal["id"], "午餐", "注意蔬菜比例", calories_kcal=520)
        exercise = self.store.upload_record("exercise", "run.png", b"fake-png")
        self.store.analyze_health_record(exercise["id"], "慢跑", "注意补水", exercise_kcal=260)

        history = self.store.health_history(7)
        today = history["points"][-1]
        self.assertEqual(today["water_ml"], 600)
        self.assertEqual(today["weight_kg"], 58.5)
        self.assertEqual(today["calories_kcal"], 520)
        self.assertEqual(today["exercise_kcal"], 260)
        self.assertEqual(history["metrics"]["latest_weight_kg"], 58.5)
        self.assertEqual(len(history["records"]), 2)
        self.assertEqual(history["daily_cards"][0]["meals"][0]["meal_label"], "午餐")
        self.assertEqual(history["daily_cards"][0]["exercise_records"][0]["exercise_kcal"], 260)

    def test_meal_upload_preserves_selected_date_and_meal_slot(self) -> None:
        selected_date = (date.today() - timedelta(days=1)).isoformat()
        record = self.store.upload_record(
            "meal",
            "tea.png",
            b"fake-png",
            record_date=selected_date,
            meal_slot="afternoon_tea",
        )
        self.store.analyze_health_record(record["id"], "酸奶和水果", "坚果控制在一小把", calories_kcal=260)

        saved = self.store.list_health_records(status="analyzed")[0]
        self.assertEqual(saved["record_date"], selected_date)
        self.assertEqual(saved["meal_slot"], "afternoon_tea")
        self.assertEqual(saved["meal_label"], "下午茶")
        self.assertEqual(saved["analysis_advice"], "坚果控制在一小把")
        history = self.store.health_history(7)
        card = next(item for item in history["daily_cards"] if item["date"] == selected_date)
        self.assertEqual(card["meals"][0]["title"], f"{date.fromisoformat(selected_date).month}月{date.fromisoformat(selected_date).day}日 下午茶")

    def test_health_record_can_be_corrected_deleted_and_restored(self) -> None:
        original_date = (date.today() - timedelta(days=2)).isoformat()
        corrected_date = (date.today() - timedelta(days=1)).isoformat()
        record = self.store.upload_record(
            "meal",
            "meal.png",
            b"fake-png",
            record_date=original_date,
            meal_slot="lunch",
        )
        corrected = self.store.update_health_record(record["id"], corrected_date, "dinner")
        self.assertEqual(corrected["record_date"], corrected_date)
        self.assertEqual(corrected["meal_label"], "晚餐")
        self.assertIn(f"/{corrected_date}/", next((self.store.root / "💪 减肥健身专栏" / "饮食记录").rglob(f"{record['id']}.md")).as_posix())
        refresh_jobs = self.store.list_agent_jobs(job_type="health_daily_summary_refresh", limit=20)
        self.assertEqual({item["subject_id"] for item in refresh_jobs}, {original_date, corrected_date})

        deleted = self.store.delete_health_record(record["id"])
        self.assertTrue(deleted["deleted"])
        self.assertFalse(any(item["id"] == record["id"] for item in self.store.list_health_records(limit=100)))
        restored = self.store.restore_health_record(record["id"])
        self.assertFalse(restored["deleted"])
        self.assertTrue(any(item["id"] == record["id"] for item in self.store.list_health_records(limit=100)))

    def test_health_history_accepts_custom_date_range_up_to_one_year(self) -> None:
        end_date = date.today()
        start_date = end_date - timedelta(days=364)
        history = self.store.health_history(start_date=start_date, end_date=end_date)
        self.assertEqual(history["range_days"], 365)
        self.assertEqual(history["start_date"], start_date.isoformat())
        self.assertEqual(history["end_date"], end_date.isoformat())
        self.assertEqual(len(history["points"]), 365)

        with self.assertRaisesRegex(ValueError, "最多查看一年"):
            self.store.health_history(start_date=end_date - timedelta(days=366), end_date=end_date)

    def test_daily_health_advice_is_stored_as_sections(self) -> None:
        saved = self.store.save_daily_health_advice(
            "",
            "on_track",
            overall_summary="今天整体节奏稳定。",
            diet_summary="三餐结构基本均衡，晚餐减少油脂。",
            hydration_summary="还需补水 800 ml。",
            exercise_summary="完成了 40 分钟快走。",
        )
        self.assertEqual(saved["overall_summary"], "今天整体节奏稳定。")
        self.assertEqual(saved["diet_summary"], "三餐结构基本均衡，晚餐减少油脂。")
        self.assertEqual(saved["hydration_summary"], "还需补水 800 ml。")
        self.assertEqual(saved["exercise_summary"], "完成了 40 分钟快走。")
        self.assertEqual([item["key"] for item in saved["sections"]], ["overall", "diet", "hydration", "exercise"])

    def test_growth_and_library_records_remain_markdown(self) -> None:
        plan = self.store.create_learning_plan("吉他入门", "弹唱一首歌")
        pending = self.store.list_agent_jobs(status="pending", job_type="learning_plan_generation")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["subject_id"], plan["id"])
        self.assertEqual(plan["status"], "waiting_for_hermes")
        updated = self.store.update_learning_plan(
            plan["id"],
            "## 第一阶段\n\n练习和弦\n\n[吉他入门视频](https://www.bilibili.com/video/example)",
            total_lessons=10,
        )
        self.assertEqual(updated["total_lessons"], 10)
        self.assertEqual(updated["agent_job"]["status"], "completed")
        self.assertEqual(updated["resources"][0]["type"], "video")
        progressed = self.store.update_learning_progress(plan["id"], 1)
        self.assertEqual(progressed["completed_lessons"], 1)
        item = self.store.create_library_item("心流", "book", "理解专注")
        finished = self.store.update_library_item(item["id"], "done", "很有启发")
        self.assertEqual(finished["status"], "done")
        self.assertIn("很有启发", finished["details"])

    def test_index_is_disposable(self) -> None:
        self.store.create_task("索引测试", "important_not_urgent")
        result = self.store.rebuild_index()
        self.assertGreaterEqual(result["documents"], 2)

    def test_backup_is_portable_and_restore_keeps_newer_files(self) -> None:
        task = self.store.create_task("备份前任务", "important_urgent")
        backup_root = Path(self.temporary.name) / "backups"
        manager = BackupManager(self.store.root, backup_root)
        backup = manager.create("manual")
        self.assertTrue((backup_root / backup["name"]).is_file())

        task_file = next((self.store.root / "📅 每日任务" / "记录").rglob(f"{task['id']}.md"))
        original = task_file.read_text(encoding="utf-8")
        task_file.write_text("changed", encoding="utf-8")
        newer = self.store.root / "用户新文件.md"
        newer.write_text("保留", encoding="utf-8")
        restored = manager.restore(backup["name"])

        self.assertEqual(task_file.read_text(encoding="utf-8"), original)
        self.assertEqual(newer.read_text(encoding="utf-8"), "保留")
        self.assertEqual(restored["mode"], "safe_merge")
        self.assertTrue((backup_root / restored["safety_backup"]["name"]).is_file())

    def test_preferences_projects_and_daily_message_remain_markdown(self) -> None:
        self.store.update_profile_settings("小玥", "comforting")
        goals = self.store.update_health_goals("female", 165, 62, 55, 330, 30, "light")
        self.store.update_ip_preferences(["AI 效率"], ["智能体"])
        project = self.store.create_project("个人工作台", "功能开发", 60, "连接 AI Agent", "2026-08-10")
        self.store.save_daily_message("慢慢来，也是在向前。", "comforting")

        dashboard = self.store.dashboard()
        self.assertEqual(dashboard["profile"]["nickname"], "小玥")
        self.assertEqual(dashboard["greeting"]["message"], "慢慢来，也是在向前。")
        self.assertEqual(dashboard["health"]["target_weight_kg"], 55)
        self.assertEqual(goals["calories_target_kcal"], 1550)
        self.assertEqual(goals["exercise_target_minutes_week"], 150)
        self.assertEqual(goals["strength_target_days_week"], 2)
        self.assertEqual(dashboard["preferences"]["ip"]["video_topics"], ["AI 效率"])
        self.assertEqual(project["progress_percent"], 60)
        self.assertTrue((self.store.root / "⚙️ 工作台设置" / "个人设置.md").exists())

    def test_health_estimate_uses_range_when_optional_details_are_missing(self) -> None:
        goals = self.store.update_health_goals("female", 165, 62, 55, 300)
        self.assertEqual(goals["calculation_mode"], "reference_range")
        self.assertLess(goals["calories_target_min_kcal"], goals["calories_target_max_kcal"])
        self.assertEqual(goals["water_target_ml"], 2150)
        self.assertAlmostEqual(goals["cups_per_day"], 7.2)

    def test_daily_message_is_one_short_sentence(self) -> None:
        saved = self.store.save_daily_message(
            "今天先动起来，哪怕只推进一小步，也比停留在原地强。后面的解释不应该出现在首页。",
            "encouraging",
        )
        self.assertEqual(saved["message"], "今天先动起来，哪怕只推进一小步，也比停留在原地强。")

    def test_library_discussion_and_content_details(self) -> None:
        item = self.store.create_library_item("测试纪录片", "documentary", "了解一个新主题")
        updated = self.store.update_library_item(
            item["id"], "in_progress", "我对第二集有疑问", None, 35, "第 2 集", None
        )
        self.assertEqual(updated["progress_percent"], 35)
        self.assertEqual(updated["current_position"], "第 2 集")
        jobs = self.store.list_agent_jobs(status="pending", job_type="library_discussion")
        self.assertEqual(jobs[0]["subject_id"], item["id"])

        content = self.store.save_content_item(
            "热点视频",
            "video_trend",
            "https://example.com/source",
            "一句摘要",
            "## 为什么值得看\n\n这里是完整内容。",
            "https://example.com/video.mp4",
        )
        detail = self.store.get_content_item(content["id"])
        self.assertIn("为什么值得看", detail["details"])
        self.assertEqual(detail["media_url"], "https://example.com/video.mp4")


if __name__ == "__main__":
    unittest.main()
