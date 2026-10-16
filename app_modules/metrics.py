"""One shared adult budget formula; outputs are model estimates."""
def compute_metrics(p):
    wt_kg = p["weight_jin"] / 2.0
    ht_cm = p["height"]
    age = p["age"]
    gender = p.get("gender", "female")

    if gender == "male":
        bmr = 10 * wt_kg + 6.25 * ht_cm - 5 * age + 5
    else:
        bmr = 10 * wt_kg + 6.25 * ht_cm - 5 * age - 161
    bmr = round(bmr)
    tdee = round(bmr * 1.35)

    gt = p.get("goal_type", "female_hourglass")
    if gt in ["male_v_taper", "tone", "female_hourglass"]:
        deficit = 420
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.35, 0.40, 0.25
    elif gt in ["male_lean", "loss", "female_lean"]:
        deficit = 500
        target = max(1200, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.45, 0.25
    elif gt in ["male_muscular", "muscle", "female_athletic"]:
        deficit = -250  # 盈余促肌肥大
        target = tdee + 250
        protein_ratio, carbs_ratio, fat_ratio = 0.35, 0.45, 0.20
    elif gt in ["male_steady", "tight", "female_steady"]:
        deficit = 550  # 大基数/啤酒肚稳健减脂
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.45, 0.25
    else:
        deficit = 420
        target = max(1300, tdee - deficit)
        protein_ratio, carbs_ratio, fat_ratio = 0.30, 0.40, 0.30

    rest_cal = target - 50
    workout_cal = target + 120

    return {
        "bmr": bmr,
        "tdee": tdee,
        "target_cal": target,
        "rest_cal": rest_cal,
        "workout_cal": workout_cal,
        "deficit": round(tdee-target),
        "protein_g": round(target * protein_ratio / 4),
        "carbs_g": round(target * carbs_ratio / 4),
        "fat_g": round(target * fat_ratio / 9)
    }

