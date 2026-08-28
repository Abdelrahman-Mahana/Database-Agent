from app.models.schemas.chat import apply_chat_statuses


def test_answered_status_is_distinct_from_request_completion():
    result = apply_chat_statuses({"success": True, "results": [{"count": 1}]})

    assert result["request_status"] == "completed"
    assert result["answer_status"] == "answered"


def test_unanswerable_status_is_not_reported_as_answered():
    result = apply_chat_statuses({"success": True, "error_type": "unanswerable"})

    assert result["request_status"] == "completed"
    assert result["answer_status"] == "not_answerable"


def test_empty_result_status_is_not_reported_as_answered():
    result = apply_chat_statuses({"success": True, "error_type": "empty_result"})

    assert result["request_status"] == "completed"
    assert result["answer_status"] == "empty_result"


def test_clarification_and_failure_statuses():
    clarification = apply_chat_statuses({"success": True, "error_type": "ambiguity"})
    failure = apply_chat_statuses({"success": False, "error": "database unavailable"})

    assert clarification["request_status"] == "completed"
    assert clarification["answer_status"] == "needs_clarification"
    assert failure["request_status"] == "failed"
    assert failure["answer_status"] == "failed"
