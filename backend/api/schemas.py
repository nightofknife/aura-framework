# -*- coding: utf-8 -*-
"""Pydantic models for the minimal backend platform API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskRunResponse(BaseModel):
    status: str
    message: str
    cid: Optional[str] = None
    trace_id: Optional[str] = None
    trace_label: Optional[str] = None


class TaskStatusItem(BaseModel):
    cid: str
    status: str
    plan_name: Optional[str] = None
    task_ref: Optional[str] = None
    started_at: Optional[int] = None
    finished_at: Optional[int] = None


class BatchTaskStatusResponse(BaseModel):
    tasks: List[TaskStatusItem]


class SystemStatusResponse(BaseModel):
    status: str = "ok"
    is_running: bool = False
    scheduler_initialized: bool = False
    scheduler_running: bool = False
    ready: bool = False


class HealthResponse(SystemStatusResponse):
    pass


class PlanSummary(BaseModel):
    name: str
    task_count: int = 0
    task_error_count: int = 0


class TaskSummary(BaseModel):
    full_task_id: str
    plan_name: str
    task_name_in_plan: str
    task_ref: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    definition: Optional[Dict[str, Any]] = None


class TaskLoadErrorResponse(BaseModel):
    plan_name: str
    source_file: str
    task_refs: List[str] = Field(default_factory=list)
    error_code: str
    message: str


class PackageSummary(BaseModel):
    canonical_id: str
    name: str
    version: str
    path: str


class ActionSummary(BaseModel):
    fqid: str
    name: str
    public: bool
    read_only: bool
    description: str = ""
    parameters: List[Dict[str, Any]] = Field(default_factory=list)
    return_schema: Dict[str, Any] = Field(default_factory=dict)
    supported_backend_domains: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    side_effect_level: str = "read"
    requires_foreground: bool = False
    requires_admin: bool = False
    stability: str = "stable"


class CapabilityBackendSummary(BaseModel):
    backend_id: str
    domain: str
    available: bool
    health_status: str
    requires_foreground: bool
    supports_background: bool
    supports_minimized: bool
    requires_admin: bool
    side_effect_level: str
    capabilities: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None
    stability: str = "stable"


class CapabilityListResponse(BaseModel):
    domains: Dict[str, List[CapabilityBackendSummary]]


class GenericMessageResponse(BaseModel):
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None


class QueueOverviewResponse(BaseModel):
    ready_count: int = 0
    running_count: int = 0
    delayed_count: int = 0
    ready_length: int = 0
    delayed_length: int = 0
    avg_wait_sec: float = 0.0


class QueueItemResponse(BaseModel):
    cid: str
    plan_name: Optional[str] = None
    task_ref: Optional[str] = None
    task_name: Optional[str] = None
    trace_id: Optional[str] = None
    trace_label: Optional[str] = None
    status: str = "queued"
    queued_at: Optional[int] = None
    enqueued_at: Optional[int] = None
    source: Optional[str] = None


class QueueListResponse(BaseModel):
    items: List[QueueItemResponse] = Field(default_factory=list)


class QueueReorderRequest(BaseModel):
    cid_order: List[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    cid: str
    plan_name: Optional[str] = None
    task_ref: Optional[str] = None
    task_name: Optional[str] = None
    trace_id: Optional[str] = None
    trace_label: Optional[str] = None
    status: str
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[Any] = None


class RunHistoryResponse(BaseModel):
    runs: List[RunSummary] = Field(default_factory=list)


class RunDetailResponse(BaseModel):
    cid: str
    plan_name: Optional[str] = None
    task_ref: Optional[str] = None
    task_name: Optional[str] = None
    trace_id: Optional[str] = None
    trace_label: Optional[str] = None
    status: str
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    duration_ms: Optional[int] = None
    error: Optional[Any] = None
    user_data: Optional[Any] = None
    framework_data: Optional[Any] = None
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    action_results: List[Dict[str, Any]] = Field(default_factory=list)
    policy_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
