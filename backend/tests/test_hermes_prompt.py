from __future__ import annotations

import unittest

from scripts.hermes_cloud_connector import task_prompt, workbench_prompt


class HermesWorkbenchPromptTests(unittest.TestCase):
    def test_prompt_teaches_cloud_workbench_workflow(self) -> None:
        prompt = workbench_prompt()
        self.assertIn("personal_workbench", prompt)
        self.assertIn("claim_next_agent_job", prompt)
        self.assertIn("6–10", prompt)
        self.assertIn("media_url", prompt)
        self.assertIn("只能处理当前令牌所属的工作空间", prompt)
        self.assertIn("get_workspace_overview", prompt)
        self.assertIn("get_project_plan", prompt)
        self.assertIn("upload_health_image.ps1", prompt)
        self.assertIn("Test-Path -LiteralPath", prompt)
        self.assertIn("ok=true", prompt)
        self.assertIn("record_id", prompt)
        self.assertIn("禁止访问、启动或重新配置", prompt)
        self.assertIn("127.0.0.1:8787", prompt)
        self.assertIn("不要调用并不存在的旧工具名", prompt)
        self.assertIn("list_finance_transactions", prompt)
        self.assertIn("delete_finance_transaction", prompt)
        self.assertIn("restore_finance_transaction", prompt)
        self.assertIn("delete_finance_budget", prompt)

    def test_realtime_job_prompt_includes_operating_rules_and_job(self) -> None:
        prompt = task_prompt({"id": "job-123", "type": "content_research_refresh", "title": "刷新热点"})
        self.assertIn("Real-time Personal Workbench job", prompt)
        self.assertIn("job-123", prompt)
        self.assertIn("content_research_refresh", prompt)
        self.assertIn("complete_agent_job", prompt)


if __name__ == "__main__":
    unittest.main()
