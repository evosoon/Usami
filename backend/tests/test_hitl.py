"""
Usami — HiTL Gateway 单元测试
"""

from __future__ import annotations

from core.hitl import HiTLGateway
from core.state import HiTLType, TaskOutput

# ============================================
# evaluate() — 触发与静默
# ============================================

class TestHiTLEvaluate:

    def test_high_confidence_no_trigger(self, hitl_gateway, task_output_high_confidence):
        """置信度 0.9 (≥ 0.6) → 不触发"""
        result = hitl_gateway.evaluate(task_output_high_confidence)
        assert result is None

    def test_low_confidence_triggers_clarification(self, hitl_gateway, task_output_low_confidence):
        """置信度 0.3 (< 0.6) → 触发 CLARIFICATION"""
        result = hitl_gateway.evaluate(task_output_low_confidence)
        assert result is not None
        assert result.hitl_type == HiTLType.CLARIFICATION
        assert "low_confidence" in result.context.get("trigger", "")

    def test_exact_threshold_no_trigger(self, hitl_gateway):
        """置信度 == 0.6 (not < 0.6) → 不触发"""
        output = TaskOutput(
            task_id="t_boundary",
            persona="researcher",
            summary="boundary",
            full_result="boundary",
            confidence=0.6,
        )
        result = hitl_gateway.evaluate(output)
        assert result is None

    def test_zero_confidence_triggers(self, hitl_gateway):
        """置信度 0.0 → 触发"""
        output = TaskOutput(
            task_id="t_zero",
            persona="researcher",
            summary="failed",
            full_result="failed",
            confidence=0.0,
        )
        result = hitl_gateway.evaluate(output)
        assert result is not None
        assert result.hitl_type == HiTLType.CLARIFICATION


# ============================================
# evaluate() — 成本告警
# ============================================

class TestHiTLCostAlert:

    def test_cost_at_80_percent_triggers_approval(self):
        """成本达到预算 80% → 触发 APPROVAL"""
        gw = HiTLGateway(budget_config={"max_cost_per_task_usd": 0.50})
        output = TaskOutput(
            task_id="t_cost",
            persona="researcher",
            summary="ok",
            full_result="ok",
            confidence=0.9,
        )
        # 0.50 * 0.80 = 0.40
        result = gw.evaluate(output, current_cost=0.40)
        assert result is not None
        assert result.hitl_type == HiTLType.APPROVAL
        assert "cost_alert" in result.context.get("trigger", "")

    def test_cost_below_threshold_no_trigger(self):
        """成本低于预算 80% → 不触发"""
        gw = HiTLGateway(budget_config={"max_cost_per_task_usd": 0.50})
        output = TaskOutput(
            task_id="t_cost_ok",
            persona="researcher",
            summary="ok",
            full_result="ok",
            confidence=0.9,
        )
        result = gw.evaluate(output, current_cost=0.39)
        assert result is None

    def test_zero_budget_no_cost_trigger(self):
        """预算为 0 → 不触发成本告警 (max_cost <= 0 短路)"""
        gw = HiTLGateway(budget_config={"max_cost_per_task_usd": 0})
        output = TaskOutput(
            task_id="t_zero_budget",
            persona="researcher",
            summary="ok",
            full_result="ok",
            confidence=0.9,
        )
        result = gw.evaluate(output, current_cost=100.0)
        assert result is None


# ============================================
# evaluate() — 重试触发
# ============================================

class TestHiTLRetry:

    def test_retry_at_threshold_triggers_error(self, hitl_gateway):
        """retry_count == 2 (≥ MAX_RETRIES_BEFORE_HITL) → 触发 ERROR"""
        output = TaskOutput(
            task_id="t_retry",
            persona="researcher",
            summary="ok",
            full_result="ok",
            confidence=0.9,
            metadata={"error": "timeout"},
        )
        result = hitl_gateway.evaluate(output, retry_count=2)
        assert result is not None
        assert result.hitl_type == HiTLType.ERROR
        assert "max_retries" in result.context.get("trigger", "")

    def test_retry_below_threshold_no_trigger(self, hitl_gateway):
        """retry_count == 1 (< 2) → 不触发"""
        output = TaskOutput(
            task_id="t_retry_ok",
            persona="researcher",
            summary="ok",
            full_result="ok",
            confidence=0.9,
        )
        result = hitl_gateway.evaluate(output, retry_count=1)
        assert result is None


# ============================================
# evaluate_plan()
# ============================================

class TestHiTLEvaluatePlan:

    def test_preview_needed(self, hitl_gateway):
        result = hitl_gateway.evaluate_plan(task_count=8, needs_preview=True)
        assert result is not None
        assert result.hitl_type == HiTLType.PLAN_REVIEW

    def test_preview_not_needed(self, hitl_gateway):
        result = hitl_gateway.evaluate_plan(task_count=2, needs_preview=False)
        assert result is None


# ============================================
# 事件日志 & 响应记录
# ============================================

class TestHiTLEventLog:

    def test_event_logged_on_trigger(self, hitl_gateway, task_output_low_confidence):
        """触发 HiTL 时写入事件日志"""
        hitl_gateway.evaluate(task_output_low_confidence)
        log = hitl_gateway.get_event_log()
        assert len(log) == 1
        assert log[0]["hitl_type"] == "clarification"
        assert log[0]["trigger"] == "low_confidence"
        assert log[0]["response"] is None  # 未响应

    def test_record_response(self, hitl_gateway, task_output_low_confidence):
        """记录用户响应后，事件日志更新"""
        req = hitl_gateway.evaluate(task_output_low_confidence)
        hitl_gateway.record_response(
            request_id=req.request_id,
            decision="approve",
            feedback="looks good",
        )
        log = hitl_gateway.get_event_log()
        assert log[0]["response"] == "approve"
        assert log[0]["feedback"] == "looks good"
        assert log[0]["response_time_ms"] is not None

    def test_no_event_when_not_triggered(self, hitl_gateway, task_output_high_confidence):
        """不触发 HiTL → 事件日志为空"""
        hitl_gateway.evaluate(task_output_high_confidence)
        assert hitl_gateway.get_event_log() == []

    def test_priority_low_confidence_over_retry(self, hitl_gateway):
        """低置信度优先级高于重试 (evaluate 顺序: confidence → cost → retry)"""
        output = TaskOutput(
            task_id="t_multi",
            persona="researcher",
            summary="bad",
            full_result="bad",
            confidence=0.3,
            metadata={"error": "timeout"},
        )
        result = hitl_gateway.evaluate(output, retry_count=5)
        # 低置信度先匹配 → CLARIFICATION，不是 ERROR
        assert result.hitl_type == HiTLType.CLARIFICATION
