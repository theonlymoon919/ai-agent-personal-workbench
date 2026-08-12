from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from lunar_python import Solar


# 法定放假和调休不能由历法推算，必须按国务院办公厅逐年发布的数据维护。
OFFICIAL_HOLIDAY_SOURCE = {
    2025: {
        "title": "国务院办公厅关于2025年部分节假日安排的通知",
        "url": "https://www.gov.cn/gongbao/2024/issue_11726/material/gwygb202433.pdf",
        "document_number": "国办发明电〔2024〕12号",
    },
    2026: {
        "title": "国务院办公厅关于2026年部分节假日安排的通知",
        "url": "https://big5.www.gov.cn/gate/big5/www.gov.cn/yaowen/liebiao/202511/content_7047099.htm",
        "document_number": "国办发明电〔2025〕7号",
    },
}


def _dates(start: str, end: str) -> list[str]:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


def _holiday_rows(name: str, start: str, end: str) -> dict[str, dict[str, Any]]:
    return {
        day: {"kind": "public_holiday", "label": name, "is_day_off": True}
        for day in _dates(start, end)
    }


OFFICIAL_HOLIDAY_DAYS: dict[int, dict[str, dict[str, Any]]] = {
    2025: {
        **_holiday_rows("元旦假期", "2025-01-01", "2025-01-01"),
        **_holiday_rows("春节假期", "2025-01-28", "2025-02-04"),
        "2025-01-26": {"kind": "makeup_workday", "label": "春节调休上班", "is_day_off": False},
        "2025-02-08": {"kind": "makeup_workday", "label": "春节调休上班", "is_day_off": False},
        **_holiday_rows("清明假期", "2025-04-04", "2025-04-06"),
        **_holiday_rows("劳动节假期", "2025-05-01", "2025-05-05"),
        "2025-04-27": {"kind": "makeup_workday", "label": "劳动节调休上班", "is_day_off": False},
        **_holiday_rows("端午假期", "2025-05-31", "2025-06-02"),
        **_holiday_rows("国庆、中秋假期", "2025-10-01", "2025-10-08"),
        "2025-09-28": {"kind": "makeup_workday", "label": "国庆中秋调休上班", "is_day_off": False},
        "2025-10-11": {"kind": "makeup_workday", "label": "国庆中秋调休上班", "is_day_off": False},
    },
    2026: {
        **_holiday_rows("元旦假期", "2026-01-01", "2026-01-03"),
        "2026-01-04": {"kind": "makeup_workday", "label": "元旦调休上班", "is_day_off": False},
        **_holiday_rows("春节假期", "2026-02-15", "2026-02-23"),
        "2026-02-14": {"kind": "makeup_workday", "label": "春节调休上班", "is_day_off": False},
        "2026-02-28": {"kind": "makeup_workday", "label": "春节调休上班", "is_day_off": False},
        **_holiday_rows("清明假期", "2026-04-04", "2026-04-06"),
        **_holiday_rows("劳动节假期", "2026-05-01", "2026-05-05"),
        "2026-05-09": {"kind": "makeup_workday", "label": "劳动节调休上班", "is_day_off": False},
        **_holiday_rows("端午假期", "2026-06-19", "2026-06-21"),
        **_holiday_rows("中秋假期", "2026-09-25", "2026-09-27"),
        **_holiday_rows("国庆假期", "2026-10-01", "2026-10-07"),
        "2026-09-20": {"kind": "makeup_workday", "label": "国庆调休上班", "is_day_off": False},
        "2026-10-10": {"kind": "makeup_workday", "label": "国庆调休上班", "is_day_off": False},
    },
}


def calendar_days(start_date: date, end_date: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build lunar, solar-term and official holiday labels for a bounded date range."""
    days: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        lunar = Solar.fromYmd(cursor.year, cursor.month, cursor.day).getLunar()
        lunar_festivals = list(dict.fromkeys(lunar.getFestivals() or []))
        solar_term = str(lunar.getJieQi() or "")
        official = OFFICIAL_HOLIDAY_DAYS.get(cursor.year, {}).get(cursor.isoformat())
        days.append(
            {
                "date": cursor.isoformat(),
                "lunar_text": f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
                "traditional_festivals": lunar_festivals,
                "solar_term": solar_term,
                "official_holiday": official,
            }
        )
        cursor += timedelta(days=1)

    notices: list[dict[str, Any]] = []
    for year in range(start_date.year, end_date.year + 1):
        source = OFFICIAL_HOLIDAY_SOURCE.get(year)
        notices.append(
            {
                "year": year,
                "status": "official" if source else "not_published",
                "title": source["title"] if source else f"{year}年法定放假与调休安排尚未录入",
                "url": source["url"] if source else "",
                "document_number": source.get("document_number", "") if source else "",
            }
        )
    return days, notices
