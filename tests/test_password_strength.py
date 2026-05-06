from services.security.password_strength import enforce_password_strength, score_password_strength


def test_password_strength_scores_missing_requirements():
    result = score_password_strength("Password!")

    assert result["score"] == 3
    assert "包含數字" in result["missing"]
    assert result["checks"]["digit"] is False


def test_password_strength_enforcement_requires_minimum_score():
    ok, msg, result = enforce_password_strength("Password!", min_score=4)

    assert ok is False
    assert "密碼強度不足" in msg
    assert result["score"] == 3


def test_password_strength_accepts_strong_password():
    ok, msg, result = enforce_password_strength("Admin@1234!A", min_score=4)

    assert ok is True
    assert msg == "OK"
    assert result["score"] == 4
