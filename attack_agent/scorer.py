class ScoreTracker:
    def __init__(self):
        self.attack_score = 0.0
        self.defense_score = 0.0
        self.availability = 100.0
        self.integrity_loss_pct = 0
        self.sync_loss_pct = 0
        self.avail_loss_pct = 0
        self.prev_integ = 0
        self.prev_sync = 0
        self.prev_avail = 0
        
    def evaluate_triad_round(self, attack_type, defense_response, integ_loss, sync_loss, avail_loss):
        """
        보안 3대 핵심 축 (CIA/ITA Triad) 손상도와 방어 성공(차단) / 실패(관통) 여부에 따라 독립 누적 점수를 산출합니다.
        """
        self.availability = max(0.0, 100.0 - avail_loss)
        if not defense_response:
            self.availability = 0.0
            self.avail_loss_pct = 100
            return

        if isinstance(defense_response, dict):
            is_defense_success = defense_response.get("defense_success", False)
        else:
            is_defense_success = bool(defense_response)

        if attack_type == "MISSILE_SURGICAL_STRIKE":
            att_pts, def_pts = 200.0, 120.0
        elif attack_type == "DRONE_SWARM":
            att_pts, def_pts = 140.0, 80.0
        elif any(k in attack_type for k in ["PULSED_BLINDING", "BLURRING"]):
            att_pts, def_pts = 150.0, 100.0
        elif any(k in attack_type for k in ["DYNAMIC_REPLAY", "SPOOFING"]):
            att_pts, def_pts = 120.0, 120.0
        elif attack_type == "ADVERSARIAL_NOISE":
            att_pts, def_pts = 50.0, 30.0
        elif attack_type == "STEALTH_NOISE":
            att_pts, def_pts = 30.0, 20.0
        else:
            att_pts, def_pts = 0.0, 0.0

        if attack_type != "NONE":
            if is_defense_success:
                # 방어 성공 (차단 성공): 방어측 독립 점수만 획득! 공격 점수는 0점 증가!
                self.defense_score = round(self.defense_score + def_pts, 1)
            else:
                # 방어 실패 (공격 관통): 공격측 독립 점수만 획득! 방어 점수는 0점 증가!
                self.attack_score = round(self.attack_score + att_pts, 1)

        self.integrity_loss_pct = min(100, integ_loss)
        self.sync_loss_pct      = min(100, sync_loss)
        self.avail_loss_pct     = min(100, avail_loss)

        self.prev_integ = self.integrity_loss_pct
        self.prev_sync  = self.sync_loss_pct
        self.prev_avail = self.avail_loss_pct

    def get_total_score(self):
        return self.defense_score

    def get_scoreboard(self):
        tot = (self.attack_score + self.defense_score) * (self.availability / 100.0)
        return (f"  [Attack 점수] Attack Score : {self.attack_score:.1f} pt\n"
                f"  [Defense 점수] Defense Score : {self.defense_score:.1f} pt\n"
                f"  [전술 점수판] Total Score : {tot:.1f} pt (가용성: {self.availability:.0f}%)")
