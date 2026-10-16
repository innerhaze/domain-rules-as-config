"""Minimal illustration of a rules-registry layer before a language-model
reviewer.

Each rule in the registry declares a predicate, a correction, and the
originating incident that caused the rule to exist. A rule firing is
written to an audit record that references the incident, so a reader who
encounters the rule later can reconstruct why it is there.

Market context is carried as structured input per country. Archetypes
route records the automation is not qualified to resolve.

All data is synthetic.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Callable


# ---------------------------------------------------------------------------
# Record and rule types.
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class Record:
    record_id: str
    name: str
    category: str
    country: str
    extra: dict


@dataclasses.dataclass
class Rule:
    rule_id: str
    description: str
    incident_id: str
    incident_summary: str
    predicate: Callable[[Record], bool]
    correction: Callable[[Record], Record]
    added_on: dt.date


# ---------------------------------------------------------------------------
# Market context: per-country rules carried as structured input, not as prompt.
# ---------------------------------------------------------------------------
MARKET_CONTEXT: dict[str, dict] = {
    "CA": {
        "allow_provisional_records": False,
        "holding_entity_patterns": ("trading inc", "international ltd", "ventures inc"),
    },
    "MX": {
        "allow_provisional_records": True,
        "holding_entity_patterns": ("servicios sa de cv", "comercializadora sa de cv"),
    },
}


# ---------------------------------------------------------------------------
# Registries. Each rule carries its originating incident.
# ---------------------------------------------------------------------------
MISCATEGORISATION_REGISTRY: list[Rule] = [
    Rule(
        rule_id="miscat-01",
        description="credit-union cooperative category → bank",
        incident_id="INC-2024-11-03-credit-union",
        incident_summary=(
            "A cleanup pass removed credit-union records because their category "
            "was 'cooperative', not 'bank'. For the foot-traffic question the "
            "client asks, credit unions and banks behave the same way. Fix: "
            "broaden the accepted category set to include the cooperative tag "
            "when the name explicitly identifies a credit union."
        ),
        predicate=lambda r: (
            r.category == "cooperative" and "credit union" in r.name.lower()
        ),
        correction=lambda r: dataclasses.replace(r, category="bank"),
        added_on=dt.date(2024, 11, 3),
    ),
]

FALSE_POSITIVE_REGISTRY: list[Rule] = [
    Rule(
        rule_id="fp-restore-01",
        description="reinstate retail records that a name-token filter removed",
        incident_id="INC-2025-02-18-name-token",
        incident_summary=(
            "A false-positive filter removed every record whose name contained "
            "the literal token 'International'. One retail chain carries that "
            "token in its official store names. 37 valid locations were missing "
            "from a delivery. Fix: for this chain, ignore the name-token "
            "filter and keep the record."
        ),
        predicate=lambda r: (
            r.extra.get("chain_slug") == "chain-sentinel"
            and r.extra.get("removed_by") == "name-token-filter"
        ),
        correction=lambda r: dataclasses.replace(
            r,
            extra={**r.extra, "removed_by": None, "reinstated": True},
        ),
        added_on=dt.date(2025, 2, 18),
    ),
]


# ---------------------------------------------------------------------------
# Archetype routing: records the automation is not qualified to resolve.
# ---------------------------------------------------------------------------
def archetype_for(record: Record) -> str | None:
    name_lower = record.name.lower()

    patterns = MARKET_CONTEXT.get(record.country, {}).get(
        "holding_entity_patterns", ()
    )
    if any(p in name_lower for p in patterns):
        return "holding-entity-review"

    overlap_count = record.extra.get("overlap_count", 0)
    overlap_names = record.extra.get("overlap_names", [])
    if overlap_count >= 3 and len({n.lower() for n in overlap_names}) >= 2:
        return "container-tenant-review"

    return None


# ---------------------------------------------------------------------------
# The main loop: archetype first, registry second, LLM stand-in last.
# ---------------------------------------------------------------------------
_AUDIT: list[dict] = []


def _log(action: str, record: Record, rule: Rule | None = None, note: str = "") -> None:
    _AUDIT.append({
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "record_id": record.record_id,
        "action": action,
        "rule_id": rule.rule_id if rule else None,
        "incident_id": rule.incident_id if rule else None,
        "note": note,
    })


def _llm_stand_in(record: Record) -> dict:
    """Dummy LLM stand-in. A real pipeline runs reviewer + verifier here."""
    even_name = len(record.name) % 2 == 0
    if even_name:
        _log("llm-accept", record)
        return {"status": "accepted-by-model", "record": record}
    _log("llm-review", record)
    return {"status": "model-flagged-for-review", "record": record}


def process(record: Record) -> dict:
    archetype = archetype_for(record)
    if archetype is not None:
        _log("route-to-human", record, note=f"archetype={archetype}")
        return {"status": "human-review", "archetype": archetype}

    for rule in MISCATEGORISATION_REGISTRY + FALSE_POSITIVE_REGISTRY:
        if rule.predicate(record):
            corrected = rule.correction(record)
            _log("registry-hit", corrected, rule=rule)
            return {
                "status": "corrected-by-registry",
                "record": corrected,
                "rule_id": rule.rule_id,
                "incident_id": rule.incident_id,
            }

    return _llm_stand_in(record)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------
def main() -> None:
    records = [
        Record("r-001", "Riverside Credit Union", "cooperative", "CA", {}),
        Record(
            "r-002",
            "Chain Sentinel International Store 42",
            "retail",
            "CA",
            {"chain_slug": "chain-sentinel", "removed_by": "name-token-filter"},
        ),
        Record("r-003", "Northfield International Ventures Inc", "retail", "CA", {}),
        Record("r-004", "Comercializadora Alfa SA de CV", "retail", "MX", {}),
        Record(
            "r-005",
            "Plaza Centro",
            "retail",
            "MX",
            {
                "overlap_count": 4,
                "overlap_names": ["Plaza Centro", "Tenant A", "Tenant B", "Tenant C"],
            },
        ),
        Record("r-006", "Local Retailer One", "retail", "CA", {}),
        Record("r-007", "Local Retailer Twenty-two", "retail", "CA", {}),
    ]

    print("=== Processing synthetic records ===\n")
    for r in records:
        result = process(r)
        print(f"  {r.record_id:6}  →  {result['status']}")

    print()
    print(f"=== Audit log ({len(_AUDIT)} entries) ===")
    for entry in _AUDIT:
        print("  " + json.dumps(entry, default=str))


if __name__ == "__main__":
    main()
