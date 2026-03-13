"""
Usami — HiTL Gateway
Pre-mortem F2 修正: Exception-only 触发 + 日志埋点

设计原则:
- Agent 自评是否需要人类介入（confidence < threshold）
- 确定性硬阈值兜底（cost/time limit）
- 每次 HiTL 事件记录到日志（为 Progressive Trust 埋数据管道）
"""

from __future__ import annotations

import uuid
import time
import structlog
from typing import Any

from core.state import HiTLRequest, HiTLType, TaskOutput

logger = structlog.get_logger()


class HiTLGateway:
    """
    HiTL Gateway — 人类介入的守门员
    
    MVP: Exception-only（不确定/出错时才触发）
    未来: Progressive Trust（学习用户审批模式，自动化放行）
    """

    # --- 触发阈值 ---
    CONFIDENCE_THRESHOLD = 0.6      # 置信度低于此值触发 HiTL
    COST_ALERT_THRESHOLD = 0.80     # 成本达到预算 80% 时告警
    MAX_RETRIES_BEFORE_HITL = 2     # 重试 N 次仍失败时触发 HiTL

    def __init__(self, budget_config: dict[str, Any] | None = None):
        self._budget = budget_config or {}
        self._max_cost = self._budget.get("max_cost_per_task_usd", 0.50)
        # HiTL 事件日志（为 Progressive Trust 埋数据管道）
        self._event_log: list[dict[str, Any]] = []

    def evaluate(
        self,
        task_output: TaskOutput,
        current_cost: float = 0.0,
        retry_count: int = 0,
    ) -> HiTLRequest | None:
        """
        评估是否需要触发 HiTL
        
        Returns:
            HiTLRequest if intervention needed, None otherwise
        """
        # Trigger 1: 置信度低
        if task_output.confidence < self.CONFIDENCE_THRESHOLD:
            return self._create_request(
                hitl_type=HiTLType.CLARIFICATION,
                title=f"Agent 不确定: {task_output.task_id}",
                description=f"执行 '{task_output.task_id}' 时置信度为 {task_output.confidence:.1%}，需要你的确认。",
                context={
                    "task_id": task_output.task_id,
                    "persona": task_output.persona,
                    "summary": task_output.summary,
                    "confidence": task_output.confidence,
                    "trigger": "low_confidence",
                },
            )

        # Trigger 2: 成本逼近预算
        if self._max_cost > 0 and current_cost >= self._max_cost * self.COST_ALERT_THRESHOLD:
            return self._create_request(
                hitl_type=HiTLType.APPROVAL,
                title="成本预警",
                description=f"当前任务已消耗 ${current_cost:.3f}，接近预算上限 ${self._max_cost:.2f}。是否继续？",
                context={
                    "current_cost": current_cost,
                    "budget": self._max_cost,
                    "trigger": "cost_alert",
                },
                options=["继续执行", "终止任务"],
            )

        # Trigger 3: 多次重试仍失败
        if retry_count >= self.MAX_RETRIES_BEFORE_HITL:
            return self._create_request(
                hitl_type=HiTLType.ERROR,
                title=f"任务执行困难: {task_output.task_id}",
                description=f"已重试 {retry_count} 次仍无法完成。",
                context={
                    "task_id": task_output.task_id,
                    "retry_count": retry_count,
                    "last_error": task_output.metadata.get("error", ""),
                    "trigger": "max_retries",
                },
                options=["重试", "跳过此任务", "手动介入"],
            )

        return None

    def evaluate_plan(
        self,
        task_count: int,
        needs_preview: bool,
    ) -> HiTLRequest | None:
        """评估 Boss 生成的计划是否需要人类预览"""
        if needs_preview:
            return self._create_request(
                hitl_type=HiTLType.PLAN_REVIEW,
                title="任务计划预览",
                description=f"Boss 生成了包含 {task_count} 个子任务的执行计划，建议预览确认。",
                context={"trigger": "complex_plan", "task_count": task_count},
                options=["批准执行", "修改计划", "取消"],
            )
        return None

    def _create_request(
        self,
        hitl_type: HiTLType,
        title: str,
        description: str,
        context: dict[str, Any],
        options: list[str] | None = None,
    ) -> HiTLRequest:
        """创建 HiTL 请求并记录事件"""
        request = HiTLRequest(
            request_id=str(uuid.uuid4()),
            hitl_type=hitl_type,
            title=title,
            description=description,
            context=context,
            options=options or [],
        )

        # 记录事件（为 Progressive Trust 埋数据管道）
        event = {
            "request_id": request.request_id,
            "hitl_type": hitl_type.value,
            "trigger": context.get("trigger", "unknown"),
            "timestamp": time.time(),
            "context_summary": title,
            # 以下字段在用户响应后填充
            "response": None,
            "response_time_ms": None,
        }
        self._event_log.append(event)

        logger.info(
            "hitl_triggered",
            request_id=request.request_id,
            type=hitl_type.value,
            trigger=context.get("trigger"),
        )

        return request

    def record_response(self, request_id: str, decision: str, feedback: str = "") -> None:
        """记录用户的 HiTL 响应（为 Progressive Trust 埋点）"""
        for event in reversed(self._event_log):
            if event["request_id"] == request_id:
                event["response"] = decision
                event["feedback"] = feedback
                event["response_time_ms"] = (time.time() - event["timestamp"]) * 1000
                logger.info(
                    "hitl_resolved",
                    request_id=request_id,
                    decision=decision,
                )
                break

    def get_event_log(self) -> list[dict[str, Any]]:
        """获取 HiTL 事件日志"""
        return self._event_log
