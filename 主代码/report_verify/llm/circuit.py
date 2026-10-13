"""Provider 级断路器（任务 1.4）。

本模块把 CertAgent “连续失败后冷却” 的思想固化为一个线程安全的
:class:`CircuitBreaker`，供 :mod:`report_verify.llm.client` 在发起 provider 请求
前后使用。它不发起任何网络请求、不接触凭据，也不记录响应正文。

状态机（与 design.md Error Handling / 环境变量表一致）：

- ``closed``：正常放行请求。连续失败累加到 ``failure_threshold`` 时转 ``open``。
- ``open``：冷却期内 :meth:`allow` 返回 ``False``，client 不发请求并回
  ``llm_circuit_open``。冷却 ``cooldown_seconds`` 到期后进入 ``half_open``。
- ``half_open``：只放行一次“探测”请求。探测成功 → ``closed`` 并清零失败计数；
  探测失败 → 重新 ``open`` 并重置冷却窗口。

线程安全：所有状态转移都在同一把 :class:`threading.Lock` 下完成，可安全用于
``asyncio.to_thread`` 背景任务下的并发调用（任务 3.2 会用到）。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

# 断路器状态标识。
STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"


class CircuitBreaker:
    """线程安全的 provider 级断路器。

    Parameters
    ----------
    failure_threshold:
        连续失败达到该值时打开断路器（必须 >= 1）。
    cooldown_seconds:
        打开后在放行探测请求前的冷却墙钟秒数（必须 >= 1）。
    clock:
        返回单调秒数的时钟；默认 :func:`time.monotonic`，测试可注入假时钟以
        免真实 sleep。
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold 必须 >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds 必须 >= 0")
        self._failure_threshold = int(failure_threshold)
        self._cooldown_seconds = float(cooldown_seconds)
        self._clock = clock
        self._lock = threading.Lock()

        self._state = STATE_CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        # half_open 下是否已放出探测请求（同一时间只允许一个探测在途）。
        self._probe_in_flight = False

    # ---- 查询 ---------------------------------------------------------------

    @property
    def state(self) -> str:
        """当前逻辑状态；读取时会先按冷却是否到期做惰性转移。"""

        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return self._state

    def snapshot(self) -> dict[str, object]:
        """返回脱敏的状态快照（无凭据、无响应正文），便于诊断/trace。"""

        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return {
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown_seconds,
                "probe_in_flight": self._probe_in_flight,
            }

    # ---- 放行决策 -----------------------------------------------------------

    def allow(self) -> bool:
        """是否允许发起一次请求。

        - ``closed``：始终允许。
        - ``open``：冷却未到期返回 ``False``；到期则转 ``half_open`` 并放行一次探测。
        - ``half_open``：只允许一个在途探测；已有探测在途时返回 ``False``。
        """

        with self._lock:
            self._maybe_transition_to_half_open_locked()

            if self._state == STATE_CLOSED:
                return True

            if self._state == STATE_OPEN:
                return False

            # half_open：仅放行一个探测。
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    # ---- 结果反馈 -----------------------------------------------------------

    def record_success(self) -> None:
        """记录一次成功：清零失败计数并关闭断路器。"""

        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False
            self._state = STATE_CLOSED

    def record_failure(self) -> None:
        """记录一次失败。

        - ``half_open`` 下的探测失败：重新打开并重置冷却窗口。
        - ``closed`` 下累加失败；达到阈值则打开。
        """

        with self._lock:
            if self._state == STATE_HALF_OPEN:
                # 探测失败 → 重新打开。
                self._open_locked()
                return

            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._open_locked()

    # ---- 内部（须持锁调用） -------------------------------------------------

    def _open_locked(self) -> None:
        self._state = STATE_OPEN
        self._opened_at = self._clock()
        self._probe_in_flight = False

    def _maybe_transition_to_half_open_locked(self) -> None:
        if self._state != STATE_OPEN or self._opened_at is None:
            return
        if (self._clock() - self._opened_at) >= self._cooldown_seconds:
            self._state = STATE_HALF_OPEN
            self._probe_in_flight = False
