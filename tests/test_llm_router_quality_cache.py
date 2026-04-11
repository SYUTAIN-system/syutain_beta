import unittest
from unittest.mock import patch

import tools.llm_router as llm_router


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, _query):
        return self._rows


class _FakeConnCtx:
    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return _FakeConn(self._rows)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestLlmRouterQualityCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_cache = llm_router._model_quality_cache.copy()

    def tearDown(self):
        llm_router._model_quality_cache = self._orig_cache

    def test_should_avoid_model_on_recent_decline(self):
        # 7日平均が悪化していれば、14日平均が閾値を上回っていても回避する
        self.assertTrue(
            llm_router._should_avoid_model(
                avg_recent=0.36,
                cnt_recent=5,
                avg_long=0.46,
                cnt_long=11,
            )
        )

    async def test_refresh_cache_marks_declined_model_as_avoid(self):
        rows = [
            {
                "task_type": "research",
                "model_used": "nvidia/nemotron-3-super-120b-a12b:free",
                "tier": "A",
                "avg_quality_recent": 0.72,
                "cnt_recent": 8,
                "avg_quality_long": 0.70,
                "cnt_long": 14,
            },
            {
                "task_type": "research",
                "model_used": "qwen3.5-9b",
                "tier": "L",
                "avg_quality_recent": 0.36,
                "cnt_recent": 5,
                "avg_quality_long": 0.46,
                "cnt_long": 11,
            },
        ]

        def _fake_get_connection():
            return _FakeConnCtx(rows)

        with patch("tools.db_pool.get_connection", new=_fake_get_connection):
            await llm_router.refresh_model_quality_cache()

        cache = llm_router._model_quality_cache.get("research")
        self.assertIsNotNone(cache)
        self.assertEqual(cache["model"], "nvidia/nemotron-3-super-120b-a12b:free")
        self.assertEqual(cache["quality_window"], "7d")
        self.assertIn("qwen3.5-9b", cache["avoid_models"])

    def test_choose_best_model_uses_avoid_list_on_local_fallback(self):
        llm_router._model_quality_cache = {
            "research": {
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "tier": "A",
                "avg_quality": 0.72,
                "sample_count": 8,
                "updated": 0,
                "avoid_models": ["qwen3.5-9b"],
            }
        }

        with patch.object(llm_router, "_openrouter_available", return_value=False), patch.object(
            llm_router, "_pick_local_node", return_value="bravo"
        ):
            selected = llm_router.choose_best_model_v6(
                task_type="research",
                quality="medium",
                budget_sensitive=True,
                local_available=True,
            )

        self.assertEqual(selected["provider"], "google")
        self.assertEqual(selected["model"], "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
