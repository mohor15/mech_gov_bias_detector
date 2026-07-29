"""Population finding signing/verification — pure, no DB. Mirrors
`tests/unit/audit/test_signing.py`'s shape, applied to
`population_finding_hash`/`verify_population_findings`. See
`audit/verify_population_findings.py`'s module docstring for why this is
a plain content hash, not `hash_chain.compute_hash`'s chained variant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gov_platform.audit.signing import load_signer
from gov_platform.audit.verify_population_findings import (
    population_finding_hash,
    verify_population_findings,
)
from gov_platform.db.repositories.population_finding import PopulationFindingRecord
from gov_platform.schemas.population_finding import PopulationFinding, PopulationFindingOutcome


def _finding(**overrides: object) -> PopulationFinding:
    defaults: dict[str, object] = {
        "population_finding_id": "pf-001",
        "population_policy_id": "adverse-impact-ratio",
        "population_policy_version": "0.1.0",
        "system_id": "sys-001",
        "window_start": datetime(2026, 1, 1, tzinfo=UTC),
        "window_end": datetime(2026, 1, 2, tzinfo=UTC),
        "outcome": PopulationFindingOutcome.FLAGGED,
        "metric_values": {"race:Black": 0.75},
        "classification_snapshot": {"race": "DIRECT"},
        "rationale": "test rationale",
        "evaluated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PopulationFinding(**defaults)  # type: ignore[arg-type]


def _signed_record(
    finding: PopulationFinding, *, signature: str | None, key_id: str = "default"
) -> PopulationFindingRecord:
    return PopulationFindingRecord(
        id=finding.population_finding_id,
        population_policy_id=finding.population_policy_id,
        population_policy_version=finding.population_policy_version,
        system_id=finding.system_id,
        window_start=finding.window_start,
        window_end=finding.window_end,
        outcome=finding.outcome,
        metric_values=finding.metric_values,
        classification_snapshot=finding.classification_snapshot,
        parameters_used=finding.parameters_used,
        rationale=finding.rationale,
        evaluated_at=finding.evaluated_at,
        signature=signature,
        signing_key_id=key_id if signature is not None else None,
    )


def test_population_finding_hash_is_deterministic_for_the_same_content() -> None:
    finding = _finding()

    assert population_finding_hash(finding) == population_finding_hash(finding)


def test_population_finding_hash_changes_if_classification_snapshot_changes() -> None:
    """The reproducibility fix (docs/milestones/M6.md §13.16): the
    classification basis is part of what gets hashed/signed, not just
    metric_values/outcome."""
    finding_a = _finding(classification_snapshot={"race": "DIRECT"})
    finding_b = _finding(classification_snapshot={"race": "PROXY"})

    assert population_finding_hash(finding_a) != population_finding_hash(finding_b)


def test_a_valid_signature_verifies() -> None:
    signer = load_signer(None)
    finding = _finding()
    record = _signed_record(finding, signature=signer.sign(population_finding_hash(finding)))

    result = verify_population_findings([record], public_key_hex=signer.public_key_hex())

    assert result.valid is True
    assert result.checked_count == 1


def test_a_tampered_finding_fails_verification() -> None:
    signer = load_signer(None)
    finding = _finding()
    signature = signer.sign(population_finding_hash(finding))
    tampered = _signed_record(
        finding.model_copy(update={"classification_snapshot": {"race": "PROXY"}}),
        signature=signature,
    )

    result = verify_population_findings([tampered], public_key_hex=signer.public_key_hex())

    assert result.valid is False
    assert result.first_invalid_id == finding.population_finding_id


def test_a_signature_from_a_different_key_fails() -> None:
    signer_a = load_signer(None)
    signer_b = load_signer(None)
    finding = _finding()
    record = _signed_record(finding, signature=signer_a.sign(population_finding_hash(finding)))

    result = verify_population_findings([record], public_key_hex=signer_b.public_key_hex())

    assert result.valid is False


def test_an_unsigned_record_is_skipped_not_failed() -> None:
    signer = load_signer(None)
    record = _signed_record(_finding(), signature=None)

    result = verify_population_findings([record], public_key_hex=signer.public_key_hex())

    assert result.valid is True


def test_a_pre_m8_finding_with_no_parameters_used_field_still_verifies() -> None:
    """The headline regression proof for docs/milestones/M8.md §4.5/§13.18:
    a finding built exactly as pre-M8 code would have built it (no
    `parameters_used` key constructed at all, not merely one explicitly
    set to `None`) must still verify against the signature it was
    actually issued under. This test fails against the *original*
    (pre-hostile-review) draft's design (an always-present
    `parameters_used` field hashed unconditionally) and passes against
    the corrected one (`exclude_none=True`)."""
    signer = load_signer(None)
    pre_m8_payload = {
        "population_finding_id": "pf-pre-m8",
        "population_policy_id": "adverse-impact-ratio",
        "population_policy_version": "0.1.0",
        "system_id": "sys-001",
        "window_start": datetime(2026, 1, 1, tzinfo=UTC),
        "window_end": datetime(2026, 1, 2, tzinfo=UTC),
        "outcome": PopulationFindingOutcome.FLAGGED,
        "metric_values": {"race:Black": 0.75},
        "classification_snapshot": {"race": "DIRECT"},
        "rationale": "pre-M8 finding",
        "evaluated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    # Simulate the exact pre-M8 hash: no parameters_used key in the dumped
    # payload at all -- what `population_finding_hash` would have computed
    # before this field existed.
    pre_m8_finding = PopulationFinding(**pre_m8_payload)  # type: ignore[arg-type]
    pre_m8_dump = pre_m8_finding.model_dump(mode="json")
    assert "parameters_used" not in pre_m8_dump or pre_m8_dump["parameters_used"] is None
    original_signature = signer.sign(population_finding_hash(pre_m8_finding))
    record = _signed_record(pre_m8_finding, signature=original_signature)

    result = verify_population_findings([record], public_key_hex=signer.public_key_hex())

    assert result.valid is True


def test_a_new_finding_with_parameters_used_signs_and_verifies_correctly() -> None:
    """The other branch of `exclude_none=True`: a finding computed from M8
    onward always has a real, non-`None` `parameters_used`, which must be
    part of what's signed (tamper-evident), not silently excluded."""
    signer = load_signer(None)
    finding = _finding(parameters_used={"threshold": 0.8, "minimum_group_size": 30.0})
    record = _signed_record(finding, signature=signer.sign(population_finding_hash(finding)))

    result = verify_population_findings([record], public_key_hex=signer.public_key_hex())

    assert result.valid is True


def test_tampering_with_parameters_used_is_detected() -> None:
    """`parameters_used` is part of the signed payload for a new finding
    -- altering it after signing must invalidate the signature, the same
    tamper-evidence guarantee `classification_snapshot` already has."""
    signer = load_signer(None)
    finding = _finding(parameters_used={"threshold": 0.8, "minimum_group_size": 30.0})
    signature = signer.sign(population_finding_hash(finding))
    tampered = _signed_record(
        finding.model_copy(
            update={"parameters_used": {"threshold": 0.5, "minimum_group_size": 30.0}}
        ),
        signature=signature,
    )

    result = verify_population_findings([tampered], public_key_hex=signer.public_key_hex())

    assert result.valid is False


def test_verification_stops_at_the_first_invalid_record() -> None:
    signer = load_signer(None)
    valid_finding = _finding(population_finding_id="pf-valid")
    valid_record = _signed_record(
        valid_finding, signature=signer.sign(population_finding_hash(valid_finding))
    )
    invalid_finding = _finding(population_finding_id="pf-invalid")
    invalid_record = _signed_record(invalid_finding, signature="00" * 64)

    result = verify_population_findings(
        [valid_record, invalid_record], public_key_hex=signer.public_key_hex()
    )

    assert result.valid is False
    assert result.checked_count == 1
    assert result.first_invalid_id == "pf-invalid"
