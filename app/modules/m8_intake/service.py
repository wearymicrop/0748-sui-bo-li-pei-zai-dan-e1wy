from app.errors import BusinessError
from app.manifest import digest
from app.modules.m8_intake.merge import SECTIONS, lot_sources, merge
from app.pipeline import calculate

DELTA_KEYS = (
    "arrived_wet_g",
    "provisional_dry_g",
    "pending_wet_g",
    "allocated_dry_g",
    "remaining_g",
)


def intake_id(batch, payload):
    return "in-" + digest({"batch": batch, "payload": payload})


def validate(payload, batch):
    if not isinstance(payload, dict):
        raise BusinessError("BAD_INTAKE", "回传须为 JSON 对象")
    if "batch" in payload and payload["batch"] != batch:
        raise BusinessError("BATCH_MISMATCH", "回传批次与台账批次不一致", 409)
    for section in SECTIONS:
        if section in payload and not isinstance(payload[section], list):
            raise BusinessError("BAD_SECTION", f"{section} 须为列表")
    if "closed" in payload and not isinstance(payload["closed"], bool):
        raise BusinessError("BAD_INTAKE", "closed 须为布尔标记")
    if not payload.get("closed") and not any(payload.get(key) for key in SECTIONS):
        raise BusinessError("EMPTY_INTAKE", "回传未携带磅单、化验、配载或封批信息")


def adjudicate(merged, result, sources):
    weighing = result["weighing"]
    drymass = result["drymass"]
    grading = result["grading"]
    loading = result["loading"]
    lots = []
    for lot in sorted(weighing["lots"]):
        row = drymass["lots"][lot]
        grade = grading["lots"][lot]
        loadable = row["dry_g"] is not None and grade["code"] is None
        remainder = loading["remaining"].get(lot, {})
        lots.append(
            {
                "lot": lot,
                "arrived_wet_g": row["wet_g"],
                "moisture_code": row["code"],
                "grade_code": grade["code"],
                "provisional_dry_g": row["dry_g"] if loadable else 0,
                "pending_wet_g": 0 if loadable else row["wet_g"],
                "allocated_dry_g": (row["dry_g"] - remainder.get("remaining_g", 0))
                if loadable
                else 0,
                "remaining_g": remainder.get("remaining_g", 0) if loadable else 0,
                "intakes": sorted(sources.get(lot, ())),
            }
        )
    totals = {key: sum(item[key] for item in lots) for key in DELTA_KEYS}
    isolated = sum(
        len(result[key]["isolated"]) for key in ("weighing", "moisture", "grading")
    )
    pending_lots = sum(1 for item in lots if item["pending_wet_g"])
    complete = bool(merged["closed"] and lots and not pending_lots and not isolated)
    return {
        "closed": merged["closed"],
        "complete": complete,
        "reconcile": result["reconcile"]["status"],
        "isolated": isolated,
        "pending_lots": pending_lots,
        "lots": lots,
        "totals": totals,
        "targets": [
            {
                "target": item["target"],
                "target_g": item["target_g"],
                "loaded_g": item["loaded_g"],
                "short_g": item["short_g"],
                "code": item["code"],
            }
            for item in loading["targets"]
        ],
        "official_remaining_g": totals["remaining_g"] if complete else None,
    }


def build(batch, records):
    intakes = []
    previous = None
    state = None
    sources = lot_sources(records)
    for index, record in enumerate(records, 1):
        merged = merge(batch, [item["payload"] for item in records[:index]])
        state = adjudicate(
            merged, calculate(merged), sources if index == len(records) else {}
        )
        intakes.append(
            {
                "seq": record["seq"],
                "id": record["id"],
                "sections": {
                    key: len(record["payload"].get(key) or []) for key in SECTIONS
                },
                "closed": bool(record["payload"].get("closed")),
                "delta": {
                    key: state["totals"][key]
                    - (previous["totals"][key] if previous else 0)
                    for key in DELTA_KEYS
                },
            }
        )
        previous = state
    return {"batch": batch, "seq": records[-1]["seq"], **state, "intakes": intakes}


def view(ledger, batch):
    records = ledger.intakes(batch)
    if not records:
        raise BusinessError("BATCH_NOT_FOUND", "批次尚无回传", 404)
    state = build(batch, records)
    published = ledger.publication(batch)
    state["published"] = (
        None
        if published is None
        else {
            "id": published["id"],
            "seq": published["seq"],
            "official_remaining_g": published["ledger"]["official_remaining_g"],
            "stale": published["seq"] < state["seq"],
        }
    )
    return state


def receive(ledger, batch, payload):
    validate(payload, batch)
    identifier = intake_id(batch, payload)
    records = ledger.intakes(batch)
    known = next((item for item in records if item["id"] == identifier), None)
    if known is None:
        calculate(merge(batch, [item["payload"] for item in records] + [payload]))
        reused, seq = ledger.put_intake(batch, identifier, payload)
    else:
        reused, seq = True, known["seq"]
    return {
        "reused": reused,
        "intake": {"id": identifier, "seq": seq},
        "ledger": view(ledger, batch),
    }


def publish(ledger, batch):
    records = ledger.intakes(batch)
    if not records:
        raise BusinessError("BATCH_NOT_FOUND", "批次尚无回传", 404)
    state = build(batch, records)
    if not state["complete"]:
        raise BusinessError(
            "INCOMPLETE_BATCH", "吨单或化验证据未齐全，正式余料不能发布", 409
        )
    if state["reconcile"] != "MATCHED":
        raise BusinessError("UNBALANCED", "湿干双账尚未对平", 409)
    body = {
        "batch": batch,
        "seq": state["seq"],
        "ledger": {
            key: state[key]
            for key in (
                "closed",
                "complete",
                "reconcile",
                "isolated",
                "pending_lots",
                "lots",
                "totals",
                "targets",
                "official_remaining_g",
                "intakes",
            )
        },
    }
    snapshot = dict(body, id="pub-" + digest(body))
    ledger.put_publication(batch, state["seq"], snapshot)
    return snapshot
