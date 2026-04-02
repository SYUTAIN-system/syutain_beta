"""
SYUTAINβ V25 Karpathy Loop（自律改善サイクル）

"Modify a parameter -> run experiment -> measure metric -> keep if improved, discard if not -> repeat"

安全な非クリティカルパラメータのみを対象とした、穏やかな計測可能最適化ループ。
突然変異エンジン（第24章）とは別。こちらは小さな変更を1日1個ずつ試す。

Tunable parameters:
  1. SNS品質閾値 (x, bluesky, threads)
  2. テーマ選択の時間帯重み
  3. 2段階精錬の品質閾値
  4. 投稿オフセット分数の範囲

Process:
  1. 24h経過した実行中実験を評価 → keep or rollback
  2. 現在のメトリクスを観察
  3. パラメータをローテーションで1つ選択
  4. ±5-10%の小さなランダム変更を適用
  5. 24h後に次のサイクルで評価
  6. 全てevent_logに記録
"""

import json
import random
import logging
from datetime import datetime, timezone

from tools.db_pool import get_connection

logger = logging.getLogger("syutain.karpathy_loop")


# ============================================================
# Tunable Parameter Registry
# ============================================================
# key: パラメータ識別子
# module: 変更を適用するモジュールパス
# attr: モジュール内の属性名（dict keyの場合は "DICT_NAME.key"）
# default: 初期値
# min_val / max_val: 安全範囲
# step_pct: 1回の変更率（5-10%）
# metric: 改善を測定するメトリクス名
# direction: "lower_is_better" or "higher_is_better"

TUNABLE_PARAMS = [
    {
        "key": "quality_threshold_x",
        "module": "brain_alpha.sns_batch",
        "attr": "PLATFORM_QUALITY_THRESHOLDS.x",
        "default": 0.68,
        "min_val": 0.55,
        "max_val": 0.80,
        "step_pct": 0.05,
        "metric": "x_engagement_rate",
        "direction": "higher_is_better",
        "description": "X品質閾値",
    },
    {
        "key": "quality_threshold_bluesky",
        "module": "brain_alpha.sns_batch",
        "attr": "PLATFORM_QUALITY_THRESHOLDS.bluesky",
        "default": 0.62,
        "min_val": 0.50,
        "max_val": 0.75,
        "step_pct": 0.05,
        "metric": "bluesky_engagement_rate",
        "direction": "higher_is_better",
        "description": "Bluesky品質閾値",
    },
    {
        "key": "quality_threshold_threads",
        "module": "brain_alpha.sns_batch",
        "attr": "PLATFORM_QUALITY_THRESHOLDS.threads",
        "default": 0.64,
        "min_val": 0.50,
        "max_val": 0.78,
        "step_pct": 0.05,
        "metric": "threads_engagement_rate",
        "direction": "higher_is_better",
        "description": "Threads品質閾値",
    },
    {
        "key": "refiner_quality_threshold",
        "module": "tools.two_stage_refiner",
        "attr": "QUALITY_THRESHOLD",
        "default": 0.70,
        "min_val": 0.55,
        "max_val": 0.85,
        "step_pct": 0.05,
        "metric": "sns_quality_avg",
        "direction": "higher_is_better",
        "description": "2段階精錬品質閾値",
    },
    {
        "key": "default_quality_threshold",
        "module": "brain_alpha.sns_batch",
        "attr": "DEFAULT_QUALITY_THRESHOLD",
        "default": 0.70,
        "min_val": 0.55,
        "max_val": 0.82,
        "step_pct": 0.05,
        "metric": "reject_rate",
        "direction": "lower_is_better",
        "description": "デフォルト品質閾値",
    },
]

# 安全に変更してはいけないもの（念のためブラックリスト）
_NEVER_TOUCH = frozenset([
    "budget", "emergency_kill", "taboo", "approval",
    "loop_guard", "max_steps", "daily_budget",
])


# ============================================================
# DB Table
# ============================================================

async def ensure_table():
    """実験テーブル作成"""
    try:
        async with get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS karpathy_experiments (
                    id SERIAL PRIMARY KEY,
                    param_key TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    old_value DOUBLE PRECISION,
                    new_value DOUBLE PRECISION,
                    config_change JSONB DEFAULT '{}',
                    baseline_metrics JSONB DEFAULT '{}',
                    result_metrics JSONB,
                    status TEXT DEFAULT 'running',
                    outcome TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    evaluated_at TIMESTAMPTZ
                )
            """)
            # param_key列が既存テーブルにない場合のマイグレーション
            has_col = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'karpathy_experiments' AND column_name = 'param_key'
                )
            """)
            if not has_col:
                await conn.execute(
                    "ALTER TABLE karpathy_experiments ADD COLUMN param_key TEXT DEFAULT ''"
                )
                await conn.execute(
                    "ALTER TABLE karpathy_experiments ADD COLUMN old_value DOUBLE PRECISION"
                )
                await conn.execute(
                    "ALTER TABLE karpathy_experiments ADD COLUMN new_value DOUBLE PRECISION"
                )
    except Exception as e:
        logger.error(f"karpathy table creation failed: {e}")


# ============================================================
# Parameter Manipulation
# ============================================================

def _get_current_value(param: dict) -> float:
    """モジュールから現在のパラメータ値を読み取る"""
    try:
        import importlib
        mod = importlib.import_module(param["module"])
        attr = param["attr"]

        if "." in attr:
            dict_name, dict_key = attr.split(".", 1)
            d = getattr(mod, dict_name)
            return float(d.get(dict_key, param["default"]))
        else:
            return float(getattr(mod, attr, param["default"]))
    except Exception as e:
        logger.warning(f"パラメータ読み取り失敗 {param['key']}: {e}")
        return param["default"]


def _apply_value(param: dict, value: float) -> bool:
    """モジュール内のパラメータ値を変更する（ランタイムのみ、ファイル書き換えなし）"""
    try:
        import importlib
        mod = importlib.import_module(param["module"])
        attr = param["attr"]

        # クランプ
        value = max(param["min_val"], min(param["max_val"], value))
        value = round(value, 4)

        if "." in attr:
            dict_name, dict_key = attr.split(".", 1)
            d = getattr(mod, dict_name)
            d[dict_key] = value
        else:
            setattr(mod, attr, value)

        logger.info(f"パラメータ適用: {param['key']} = {value}")
        return True
    except Exception as e:
        logger.error(f"パラメータ適用失敗 {param['key']}: {e}")
        return False


def _generate_perturbation(param: dict) -> float:
    """小さなランダム変更を生成（±5-10%）"""
    current = _get_current_value(param)
    step = param["step_pct"]
    # ±step_pct の範囲でランダム
    delta = current * random.uniform(-step, step)
    new_val = current + delta
    # 安全範囲にクランプ
    new_val = max(param["min_val"], min(param["max_val"], new_val))
    return round(new_val, 4)


# ============================================================
# Metrics Collection
# ============================================================

async def _observe(conn) -> dict:
    """現在のシステムメトリクスを収集"""
    metrics = {}

    # SNS品質平均
    metrics["sns_quality_avg"] = float(await conn.fetchval("""
        SELECT COALESCE(AVG(quality_score), 0) FROM posting_queue
        WHERE status = 'posted' AND posted_at > NOW() - INTERVAL '24 hours'
    """) or 0)

    # reject率（24h）
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM posting_queue WHERE scheduled_at > NOW() - INTERVAL '24 hours'"
    ) or 1
    rejected = await conn.fetchval(
        "SELECT COUNT(*) FROM posting_queue WHERE status = 'rejected' AND scheduled_at > NOW() - INTERVAL '24 hours'"
    ) or 0
    metrics["reject_rate"] = round(rejected / max(total, 1), 4)

    # プラットフォーム別エンゲージメント率（24h）
    for platform in ("x", "bluesky", "threads"):
        try:
            rows = await conn.fetch(f"""
                SELECT engagement_data FROM posting_queue
                WHERE status = 'posted'
                  AND platform = $1
                  AND engagement_data IS NOT NULL
                  AND engagement_data::text != 'null'
                  AND posted_at > NOW() - INTERVAL '24 hours'
            """, platform)
            if rows:
                rates = []
                for r in rows:
                    ed = r["engagement_data"]
                    if isinstance(ed, str):
                        ed = json.loads(ed)
                    likes = int(ed.get("like_count", 0) or 0)
                    reposts = int(ed.get("repost_count", ed.get("retweet_count", 0)) or 0)
                    replies = int(ed.get("reply_count", 0) or 0)
                    impressions = int(ed.get("impression_count", ed.get("view_count", 0)) or 0)
                    if impressions > 0:
                        rates.append((likes + reposts + replies) / impressions)
                    else:
                        rates.append(likes + reposts * 3 + replies * 5)
                metrics[f"{platform}_engagement_rate"] = round(
                    sum(rates) / len(rates), 6
                ) if rates else 0.0
            else:
                metrics[f"{platform}_engagement_rate"] = 0.0
        except Exception:
            metrics[f"{platform}_engagement_rate"] = 0.0

    # LLMコスト（24h）
    metrics["daily_cost"] = float(await conn.fetchval("""
        SELECT COALESCE(SUM(amount_jpy), 0) FROM llm_cost_log
        WHERE recorded_at > NOW() - INTERVAL '24 hours'
    """) or 0)

    # ローカル率（24h）
    total_calls = await conn.fetchval(
        "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours'"
    ) or 1
    local_calls = await conn.fetchval(
        "SELECT COUNT(*) FROM llm_cost_log WHERE recorded_at > NOW() - INTERVAL '24 hours' AND amount_jpy = 0"
    ) or 0
    metrics["local_rate"] = round(local_calls / max(total_calls, 1), 4)

    # エラー数（24h）
    metrics["error_count_24h"] = await conn.fetchval(
        "SELECT COUNT(*) FROM event_log WHERE severity = 'error' AND created_at > NOW() - INTERVAL '24 hours'"
    ) or 0

    # 投稿数（24h）
    metrics["posts_24h"] = await conn.fetchval(
        "SELECT COUNT(*) FROM posting_queue WHERE status = 'posted' AND posted_at > NOW() - INTERVAL '24 hours'"
    ) or 0

    return metrics


# ============================================================
# Experiment Lifecycle
# ============================================================

def _select_next_param(last_key: str) -> dict:
    """ローテーションで次のパラメータを選択"""
    if not last_key:
        return TUNABLE_PARAMS[0]

    keys = [p["key"] for p in TUNABLE_PARAMS]
    try:
        idx = keys.index(last_key)
        next_idx = (idx + 1) % len(keys)
    except ValueError:
        next_idx = 0

    return TUNABLE_PARAMS[next_idx]


async def _start_experiment(conn, param: dict, metrics: dict) -> dict:
    """新しい実験を開始: パラメータに小さな変更を適用"""
    old_value = _get_current_value(param)
    new_value = _generate_perturbation(param)

    # 変化が小さすぎる場合は方向を決めて最小変化量を保証
    min_delta = old_value * 0.03  # 最低3%の変化
    if abs(new_value - old_value) < min_delta:
        direction = random.choice([-1, 1])
        new_value = old_value + direction * min_delta
        new_value = max(param["min_val"], min(param["max_val"], round(new_value, 4)))

    # ランタイムに適用
    applied = _apply_value(param, new_value)
    if not applied:
        return {"error": "apply_failed"}

    config_change = {
        "param_key": param["key"],
        "module": param["module"],
        "attr": param["attr"],
        "old_value": old_value,
        "new_value": new_value,
        "description": param["description"],
        "metric": param["metric"],
        "direction": param["direction"],
    }

    hypothesis = (
        f"{param['description']}を{old_value:.4f}→{new_value:.4f}に変更。"
        f"24h後に{param['metric']}が{'改善' if param['direction'] == 'higher_is_better' else '低下'}すれば採用。"
    )

    exp_id = await conn.fetchval("""
        INSERT INTO karpathy_experiments
        (param_key, hypothesis, experiment_type, old_value, new_value,
         config_change, baseline_metrics, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'running')
        RETURNING id
    """,
        param["key"],
        hypothesis,
        param["key"],
        old_value,
        new_value,
        json.dumps(config_change, ensure_ascii=False),
        json.dumps(metrics, ensure_ascii=False),
    )

    return {
        "id": exp_id,
        "param_key": param["key"],
        "old_value": old_value,
        "new_value": new_value,
        "hypothesis": hypothesis,
    }


async def _evaluate_experiment(conn, experiment) -> str:
    """24h経過した実験を評価。改善→keep、悪化→rollback。"""
    try:
        current_metrics = await _observe(conn)
        baseline = experiment["baseline_metrics"]
        if isinstance(baseline, str):
            baseline = json.loads(baseline)

        config = experiment["config_change"]
        if isinstance(config, str):
            config = json.loads(config)

        metric_name = config.get("metric", "")
        direction = config.get("direction", "higher_is_better")
        old_value = experiment.get("old_value") or config.get("old_value")
        new_value = experiment.get("new_value") or config.get("new_value")

        baseline_metric = baseline.get(metric_name, 0)
        current_metric = current_metrics.get(metric_name, 0)

        # 改善判定
        if direction == "higher_is_better":
            improved = current_metric > baseline_metric
        else:
            improved = current_metric < baseline_metric

        if improved:
            outcome = "improved"
            logger.info(
                f"Karpathy実験#{experiment['id']}成功: "
                f"{metric_name} {baseline_metric:.4f}→{current_metric:.4f} (KEEP)"
            )
        else:
            outcome = "reverted"
            # ロールバック: 元の値に戻す
            param = _find_param(experiment.get("param_key") or config.get("param_key", ""))
            if param and old_value is not None:
                _apply_value(param, float(old_value))
                logger.info(
                    f"Karpathy実験#{experiment['id']}ロールバック: "
                    f"{metric_name} {baseline_metric:.4f}→{current_metric:.4f}, "
                    f"値を{old_value}に復元"
                )
            else:
                logger.warning(
                    f"Karpathy実験#{experiment['id']}: ロールバック対象パラメータが見つからない"
                )

        await conn.execute("""
            UPDATE karpathy_experiments
            SET status = 'evaluated', outcome = $1, result_metrics = $2, evaluated_at = NOW()
            WHERE id = $3
        """, outcome, json.dumps(current_metrics, ensure_ascii=False), experiment["id"])

        return outcome

    except Exception as e:
        logger.error(f"experiment evaluation failed for #{experiment.get('id')}: {e}")
        # エラー時も安全のためロールバックを試みる
        try:
            config = experiment["config_change"]
            if isinstance(config, str):
                config = json.loads(config)
            old_value = experiment.get("old_value") or config.get("old_value")
            param = _find_param(experiment.get("param_key") or config.get("param_key", ""))
            if param and old_value is not None:
                _apply_value(param, float(old_value))
        except Exception:
            pass

        await conn.execute("""
            UPDATE karpathy_experiments
            SET status = 'error', outcome = 'error', evaluated_at = NOW()
            WHERE id = $1
        """, experiment["id"])
        return "error"


def _find_param(key: str) -> dict | None:
    """パラメータキーからTUNABLE_PARAMSを検索"""
    for p in TUNABLE_PARAMS:
        if p["key"] == key:
            return p
    return None


# ============================================================
# Main Cycle
# ============================================================

async def run_karpathy_cycle() -> dict:
    """1サイクル実行（毎日05:00に呼ばれる）

    Flow:
    1. 24h経過した実行中実験を評価（keep or rollback）
    2. 現在のメトリクスを観察
    3. 新しい実験を1つ開始（ローテーション）
    4. 全てevent_logに記録
    """
    await ensure_table()
    result = {"cycle_at": datetime.now(timezone.utc).isoformat(), "actions": []}

    try:
        async with get_connection() as conn:
            # === Phase 1: 実行中実験の評価（24h経過したもの）===
            running = await conn.fetch("""
                SELECT * FROM karpathy_experiments
                WHERE status = 'running'
                  AND created_at < NOW() - INTERVAL '24 hours'
                ORDER BY created_at ASC
            """)
            for exp in running:
                evaluation = await _evaluate_experiment(conn, exp)
                result["actions"].append({
                    "type": "evaluated",
                    "id": exp["id"],
                    "param_key": exp.get("param_key", ""),
                    "outcome": evaluation,
                })

            # === Phase 2: 現在のメトリクスを観察 ===
            metrics = await _observe(conn)
            result["metrics"] = metrics

            # === Phase 3: 新しい実験を開始（実行中がなければ）===
            active_count = await conn.fetchval(
                "SELECT COUNT(*) FROM karpathy_experiments WHERE status = 'running'"
            ) or 0

            if active_count == 0:
                # 最後に実験したパラメータを取得してローテーション
                last_key = await conn.fetchval("""
                    SELECT param_key FROM karpathy_experiments
                    ORDER BY created_at DESC LIMIT 1
                """) or ""

                param = _select_next_param(last_key)

                # 安全チェック
                if any(forbidden in param["key"] for forbidden in _NEVER_TOUCH):
                    logger.warning(f"安全チェック: {param['key']}はブラックリスト対象")
                else:
                    exp_result = await _start_experiment(conn, param, metrics)
                    if "error" not in exp_result:
                        result["actions"].append({
                            "type": "experiment_started",
                            "id": exp_result.get("id"),
                            "param_key": exp_result["param_key"],
                            "old_value": exp_result["old_value"],
                            "new_value": exp_result["new_value"],
                            "hypothesis": exp_result["hypothesis"],
                        })
            else:
                result["actions"].append({
                    "type": "skipped",
                    "reason": f"実行中の実験が{active_count}件あるためスキップ",
                })

            # === Phase 4: event_logに記録 ===
            try:
                from tools.event_logger import log_event
                await log_event(
                    "karpathy_loop.experiment",
                    "system",
                    {
                        "cycle_at": result["cycle_at"],
                        "actions": result["actions"],
                        "metrics_snapshot": metrics,
                    },
                    severity="info",
                )
            except Exception as e:
                logger.warning(f"event_log記録失敗: {e}")

    except Exception as e:
        logger.error(f"karpathy cycle failed: {e}")
        result["error"] = str(e)

    return result


# ============================================================
# Startup: 再起動時に実行中の実験パラメータを復元
# ============================================================

async def restore_running_experiments():
    """起動時に実行中の実験のパラメータ値を復元する。
    プロセス再起動でランタイム変更が消えるため。
    """
    try:
        await ensure_table()
        async with get_connection() as conn:
            running = await conn.fetch("""
                SELECT * FROM karpathy_experiments WHERE status = 'running'
            """)
            for exp in running:
                param = _find_param(exp.get("param_key", ""))
                new_value = exp.get("new_value")
                if param and new_value is not None:
                    _apply_value(param, float(new_value))
                    logger.info(
                        f"Karpathy復元: {param['key']} = {new_value} (実験#{exp['id']})"
                    )
    except Exception as e:
        logger.warning(f"Karpathy実験復元失敗: {e}")


# ============================================================
# Status query (Web UI / Discord用)
# ============================================================

async def get_karpathy_status() -> dict:
    """現在のKarpathy Loopの状態を返す"""
    try:
        await ensure_table()
        async with get_connection() as conn:
            running = await conn.fetch(
                "SELECT id, param_key, old_value, new_value, hypothesis, created_at "
                "FROM karpathy_experiments WHERE status = 'running' ORDER BY created_at DESC"
            )
            recent = await conn.fetch(
                "SELECT id, param_key, old_value, new_value, outcome, evaluated_at "
                "FROM karpathy_experiments WHERE status = 'evaluated' "
                "ORDER BY evaluated_at DESC LIMIT 10"
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM karpathy_experiments"
            ) or 0
            improved = await conn.fetchval(
                "SELECT COUNT(*) FROM karpathy_experiments WHERE outcome = 'improved'"
            ) or 0

            # 現在のパラメータ値
            current_params = {}
            for p in TUNABLE_PARAMS:
                current_params[p["key"]] = {
                    "value": _get_current_value(p),
                    "default": p["default"],
                    "range": [p["min_val"], p["max_val"]],
                    "description": p["description"],
                }

            return {
                "running_experiments": [dict(r) for r in running],
                "recent_evaluations": [dict(r) for r in recent],
                "total_experiments": total,
                "improved_count": improved,
                "improvement_rate": round(improved / max(total, 1), 3),
                "current_params": current_params,
            }
    except Exception as e:
        return {"error": str(e)}
