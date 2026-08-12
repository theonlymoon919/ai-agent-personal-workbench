from datetime import datetime, timezone
import unittest

from pydantic import ValidationError

from backend.app.cloud.growth_schemas import LearningResource


class LearningResourceSchemaTests(unittest.TestCase):
    def test_bilibili_learning_resource_requires_verification_evidence(self) -> None:
        resource = LearningResource(
            title="Python 入门课程",
            url="https://www.bilibili.com/video/BV1abc123XYZ",
            resource_type="video",
            platform="B站",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            verified_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            search_keywords=["Python 入门", "Python 3.14"],
            relevance_reason="课程覆盖用户目标中的语法基础和小项目练习。",
        )

        self.assertEqual(resource.url.path, "/video/BV1abc123XYZ")
        self.assertEqual(resource.search_keywords, ["Python 入门", "Python 3.14"])

    def test_bilibili_learning_resource_rejects_unverified_or_noncanonical_links(self) -> None:
        invalid_cases = [
            ("https://search.bilibili.com/all?keyword=Python", {}),
            ("https://www.bilibili.com/video/BV1abc123XYZ", {"published_at": None}),
            ("https://www.bilibili.com/video/BV1abc123XYZ", {"verified_at": None}),
            ("https://www.bilibili.com/video/BV1abc123XYZ", {"search_keywords": []}),
            ("https://www.bilibili.com/video/BV1abc123XYZ", {"relevance_reason": ""}),
        ]
        for url, overrides in invalid_cases:
            with self.subTest(url=url, overrides=overrides):
                payload = {
                    "title": "Python 入门课程",
                    "url": url,
                    "resource_type": "video",
                    "platform": "B站",
                    "published_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "verified_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
                    "search_keywords": ["Python 入门"],
                    "relevance_reason": "与用户目标匹配。",
                    **overrides,
                }
                with self.assertRaises(ValidationError):
                    LearningResource(**payload)
