from types import SimpleNamespace

from packages.aura_core.api.decorators import action_info
from packages.aura_core.api.definitions import ActionDefinition
from packages.aura_core.context.execution import ExecutionContext
from packages.aura_core.engine.action_injector import ActionInjector
from packages.aura_core.sdk import ActionContext, ActionResultBuilder, EvidenceWriter, PolicyContext


class _Plugin:
    package = SimpleNamespace(canonical_id="@tests/demo")


def test_action_info_filters_sdk_injected_parameters():
    @action_info(name="sdk_demo", read_only=True)
    def sdk_demo(action_context: ActionContext, evidence: EvidenceWriter, value: str = "ok"):
        return value

    params = sdk_demo._aura_action_meta["parameters"]

    assert [param["name"] for param in params] == ["value"]


def test_action_injector_injects_sdk_context_and_evidence():
    def sdk_action(action_context: ActionContext, evidence: EvidenceWriter, policy: PolicyContext, builder: ActionResultBuilder):
        evidence.add_ref(kind="note", payload={"ok": True})
        return {
            "cid": action_context.cid,
            "node": action_context.node_id,
            "policy": policy.decision,
            "built": builder.data({"x": 1}).build(),
        }

    action_def = ActionDefinition(
        func=sdk_action,
        name="sdk_action",
        read_only=True,
        public=True,
        service_deps={},
        plugin=_Plugin(),
        capabilities=["filesystem.read"],
    )
    context = ExecutionContext(inputs={"name": "Aura"}, cid="cid-1")
    context.data["_current_node_id"] = "step-1"
    injector = ActionInjector(context=context, engine=SimpleNamespace(), renderer=SimpleNamespace(), services={})
    injector._prepare_sdk_runtime_context(
        action_def,
        {
            "profile": "default",
            "decision": "allow",
            "reason": "",
            "capabilities": ["filesystem.read"],
            "action": action_def.fqid,
            "package_id": "tests/demo",
        },
    )

    args = injector._prepare_action_arguments(action_def, {})
    result = action_def.func(**args)
    envelope = injector._build_action_result(
        action_def=action_def,
        policy={"profile": "default", "decision": "allow", "capabilities": ["filesystem.read"]},
        ok=True,
        error_code=None,
        message="",
        duration_ms=1,
        value=result,
    )

    assert result["cid"] == "cid-1"
    assert result["node"] == "step-1"
    assert result["policy"] == "allow"
    assert envelope["evidence"][0]["kind"] == "note"
