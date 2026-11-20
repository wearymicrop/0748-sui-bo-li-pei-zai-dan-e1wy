from app.manifest import canonical

SECTIONS = ("tickets", "moisture", "grades", "targets")


def merge(batch, payloads):
    merged = {"batch": batch, "closed": False}
    seen = set()
    for section in SECTIONS:
        merged[section] = []
    for payload in payloads:
        if payload.get("closed") is True:
            merged["closed"] = True
        for section in SECTIONS:
            for raw in payload.get(section) or []:
                marker = section, canonical(raw)
                if marker in seen:
                    continue
                seen.add(marker)
                merged[section].append(raw)
    return merged


def lot_sources(records):
    sources = {}
    for record in records:
        for section in ("tickets", "moisture", "grades"):
            for raw in record["payload"].get(section) or []:
                if isinstance(raw, dict):
                    lot = raw.get("lot")
                    if isinstance(lot, str) and lot.strip():
                        sources.setdefault(lot.strip(), set()).add(record["seq"])
    return sources
