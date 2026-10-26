from app.agent.planner import build_plan
from uuid import NAMESPACE_OID, uuid5
from app.db.models import (
    Checkpoint,
    Hold,
    OperationLedger,
    Quote,
    Revision,
    Run,
    Step,
    Stock,
    now,
    uid,
)
from app.engine.contracts import SagaError
from app.engine.runtime import operation_id
from app.engine.state_machine import CompensationStatus, ExecutionMode, StepStatus


async def fork_run(runtime, run_id, index, revision_no=None, override_plan=None):
    if index not in (0, 1, 2, 3):
        raise SagaError("INVALID_FORK_BOUNDARY", "Fork index must be 0, 1, 2 or 3", 422)
    async with runtime.invocation(run_id):
        parent = await runtime._run(run_id)
        revision_no = revision_no or parent.active_revision_no
        async with runtime.db.sessions() as session:
            checkpoint = await session.get(
                Checkpoint, (run_id, revision_no, index, "BEFORE_STEP")
            )
        if not checkpoint:
            raise SagaError(
                "CHECKPOINT_NOT_FOUND",
                "Requested historical checkpoint does not exist",
                404,
            )
        snapshot = checkpoint.revision_snapshot
        # Altered plans cannot reuse inventory effects for a different payload.
        if (
            override_plan is not None
            and index > 1
            and override_plan != snapshot["agent_plan"]
        ):
            raise SagaError(
                "OVERRIDE_CONFLICTS_WITH_PREFIX",
                "Changed plan requires a fork before inventory reservation (step 0 or 1)",
                422,
            )
        child = Run(
            parent_run_id=run_id,
            forked_from_step_index=index,
            execution_mode=ExecutionMode.SANDBOX,
            rfq_payload=snapshot["rfq_payload"],
            agent_plan=snapshot["agent_plan"],
        )
        if override_plan is not None:
            checkpoint_stock = {
                value["sku"]: Stock.model_validate(value)
                for value in checkpoint.inventory_snapshot["stock"]
            }
            child.agent_plan = build_plan(
                checkpoint_stock, child.rfq_payload, override_plan
            )
        child.sandbox_namespace = f"sandbox_{child.id}"
        mapping = {}
        current_records = {
            value["step_index"]: value["external_record_id"]
            for value in snapshot["steps"]
            if value["step_index"] < index
        }
        async with runtime.db.transaction() as session:
            session.add(child)
            await session.flush()
            session.add(
                Revision(
                    run_id=child.id,
                    revision_no=1,
                    rfq_payload=child.rfq_payload,
                    agent_plan=child.agent_plan,
                )
            )
            for value in checkpoint.inventory_snapshot["stock"]:
                value = {**value, "namespace": child.sandbox_namespace}
                session.add(Stock.model_validate(value))
            for model, values, id_key, step_index in [
                (Hold, checkpoint.inventory_snapshot["holds"], "hold_id", 1),
                (Quote, checkpoint.crm_quotes_snapshot, "quote_id", 2),
            ]:
                for value in values:
                    new_id = uid()
                    mapping[value[id_key]] = new_id
                    new_op = (
                        operation_id(child.id, 1, step_index)
                        if current_records.get(step_index) == value[id_key]
                        else str(
                            uuid5(
                                NAMESPACE_OID,
                                f"fork:{child.id}:{value['operation_id']}",
                            )
                        )
                    )
                    mapping[value["operation_id"]] = new_op
                    cloned = {
                        **value,
                        id_key: new_id,
                        "namespace": child.sandbox_namespace,
                        "run_id": child.id,
                        "operation_id": new_op,
                    }
                    correction_field = (
                        "released_by_op_id" if model is Hold else "voided_by_op_id"
                    )
                    if value[correction_field]:
                        new_comp_op = str(
                            uuid5(
                                NAMESPACE_OID,
                                f"fork:{child.id}:{value[correction_field]}",
                            )
                        )
                        mapping[value[correction_field]] = new_comp_op
                        cloned[correction_field] = new_comp_op
                    session.add(model.model_validate(cloned))
            for value in snapshot["steps"]:
                if value["step_index"] >= index:
                    continue
                if value["status"] != StepStatus.COMMITTED.value:
                    raise SagaError(
                        "INVALID_CHECKPOINT_PREFIX",
                        "Fork prefix contains an uncommitted step",
                    )
                step_index = value["step_index"]
                record_id = mapping.get(value["external_record_id"])
                output = {
                    key: mapping.get(item, item) if isinstance(item, str) else item
                    for key, item in value["output_payload"].items()
                }
                if step_index == 0:
                    output = child.agent_plan
                cloned = Step.model_validate(
                    {
                        **value,
                        "id": uid(),
                        "run_id": child.id,
                        "revision_no": 1,
                        "operation_id": operation_id(child.id, 1, step_index),
                        "external_record_id": record_id,
                        "output_payload": output,
                        "verification_evidence": {
                            "source_run_id": run_id,
                            "source_revision_no": revision_no,
                            "source_step_id": value["id"],
                        },
                        "compensation_operation_id": operation_id(
                            child.id, 1, step_index, True
                        ),
                        "compensation_status": CompensationStatus.PENDING
                        if step_index in (1, 2)
                        else CompensationStatus.NOT_NEEDED,
                        "compensation_attempt_count": 0,
                        "compensation_evidence": {},
                    }
                )
                session.add(cloned)
                if step_index in (1, 2):
                    session.add(
                        OperationLedger(
                            namespace=child.sandbox_namespace,
                            tool_name=cloned.tool_name,
                            operation_id=cloned.operation_id,
                            status="COMMITTED",
                            external_record_id=record_id,
                            output_payload=output,
                            deadline_at=now(),
                        )
                    )
            child.source_record_map = mapping
    return await runtime.resume(child.id)
