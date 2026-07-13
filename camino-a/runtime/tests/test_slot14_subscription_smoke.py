from scripts.run_slot14_subscription_smoke import _prior_slot_history


def test_smoke_fixture_records_hash_bound_evidence_for_slots_1_to_13() -> None:
    candidate_sha = "a" * 64
    history = _prior_slot_history(candidate_sha)

    assert [item["slot_id"] for item in history] == [str(value) for value in range(1, 14)]
    assert all(item["event"] == "canonical_slot_completed" for item in history)
    assert all(len(item["evidence"]) == 1 for item in history)
    assert all(item["evidence"][0]["status"] == "ok" for item in history)
    assert all(
        item["evidence"][0]["candidate_sha256"] == candidate_sha
        for item in history
    )
