import re


def score_password_strength(password):
    password = password if isinstance(password, str) else ""
    checks = {
        "length_8": len(password) >= 8,
        "length_12": len(password) >= 12,
        "lower": bool(re.search(r"[a-z]", password)),
        "upper": bool(re.search(r"[A-Z]", password)),
        "digit": bool(re.search(r"\d", password)),
        "symbol": bool(re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", password)),
    }
    score = 0
    if checks["length_8"]:
        score += 1
    if checks["lower"] and checks["upper"]:
        score += 1
    if checks["digit"]:
        score += 1
    if checks["symbol"]:
        score += 1
    if checks["length_12"] and score < 4:
        score += 1
    score = min(score, 4)
    labels = ["極弱", "弱", "普通", "強", "很強"]
    missing = []
    if not checks["length_8"]:
        missing.append("至少 8 個字元")
    if not (checks["lower"] and checks["upper"]):
        missing.append("同時包含大小寫英文字母")
    if not checks["digit"]:
        missing.append("包含數字")
    if not checks["symbol"]:
        missing.append("包含符號")
    return {
        "score": score,
        "label": labels[score],
        "missing": missing,
        "checks": checks,
    }


def enforce_password_strength(password, min_score=3):
    result = score_password_strength(password)
    if result["score"] < min_score:
        missing = "、".join(result["missing"]) if result["missing"] else "提高密碼複雜度"
        return False, f"密碼強度不足（{result['score']}/4）：{missing}", result
    return True, "OK", result
