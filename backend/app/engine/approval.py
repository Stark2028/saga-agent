import hashlib
import hmac
import json


def canonical(value):
    # All money/quantities are integers. No floating-point values enter approvals.
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def state_hash(revision_no, rfq_payload, agent_plan, dispatch_payload):
    envelope = {
        "revision_no": revision_no,
        "rfq_payload": rfq_payload,
        "agent_plan": agent_plan,
        "dispatch_payload": dispatch_payload,
    }
    return hashlib.sha256(canonical(envelope).encode("utf-8")).hexdigest()


def signature(secret, run_id, revision_no, bound_state_hash, reviewer_id):
    text = f"{run_id}:{revision_no}:{bound_state_hash}:{reviewer_id}"
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def verify_signature(secret, approval):
    if not approval.reviewer_id or not approval.reviewer_signature:
        return False
    expected = signature(
        secret,
        approval.run_id,
        approval.revision_no,
        approval.bound_state_hash,
        approval.reviewer_id,
    )
    return hmac.compare_digest(expected, approval.reviewer_signature)
