"""
=============================================================
 Reasoning Guard - AI Attack Agent (공격 에이전트)
 DAH 2026 Defense AI Cyber Security Hackathon
=============================================================
 [채점 공식] total_score = (attack_score + defense_score) × availability
   - availability: 0~100 범위, SLA 체크 실패 시 감소
   - 따라서 가용성(SLA) 0% 완전 파괴는 총점 0점 = 자살 행위
   - 핵심 전략: 방어 탐지 능력(defense_score)만 수치적으로 깎고
                가용성은 최대한 보존하면서 attack_score 극대화

 [물리 타격 정책 - 유연한 미사일 활용]
   - 미사일은 "방어 체계의 특정 센서 노드"만 정밀 타격
   - 타깃: 방어측 AI의 이상탐지 모듈 or 전처리 대역폭
   - 효과: 방어측 탐지 정확도(defense_integrity)를 수치적으로 손상
   - 메인 서버(가용성)는 건드리지 않음 → SLA 점수 보존
   - 사이버 공격의 Enabler 역할: 손상된 탐지망 틈으로 노이즈 침투

 [작전 구조: Probe & Exploit]
   1R: STEALTH_NOISE    - 사이버 방어망 한계 탐색 (은밀 노이즈)
   2R: MISSILE_SURGICAL - 방어 센서 노드 정밀 타격 (부분 손상)
   3R: DRONE_SWARM      - 통신망 가용성 점진적 소모 테스트
   4R~: LLM 자율 교전   - 정찰 결과 기반 최적 하이브리드 전술 구사
=============================================================
"""

import time
import os
import signal
import random
import requests
import cv2
import numpy as np
import json
import re
from scorer import ScoreTracker

signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))
signal.signal(signal.SIGINT, lambda s, f: os._exit(0))

# ─────────────────────────────────────────────
# 환경 변수 기반 설정
# ─────────────────────────────────────────────
TARGET_HOST    = os.environ.get("TARGET_HOST",    "target_env")
DEFENSE_HOST   = os.environ.get("DEFENSE_HOST",   "defense_agent")
DEFENSE_PORT   = os.environ.get("DEFENSE_PORT",   "5000")
ATTACK_INTERVAL = int(os.environ.get("ATTACK_INTERVAL", "5"))
OLLAMA_URL     = os.environ.get("OLLAMA_URL",     "http://host.docker.internal:11434")
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL",   "llama3")

TARGET_URL  = f"http://{TARGET_HOST}/images"
DEFENSE_URL = f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/analyze"

IMAGE_LIST = [
    "UAV_1.png", "UAV_2.png", "UAV_3.png", "UAV_4.png",
    "UGV_1.png", "UGV_2.png", "UGV_3.png", "UGV_4.png",
    "Missile_1.png", "Missile_2.png", "Missile_3.png", "Missile_4.png"
]

# ─────────────────────────────────────────────
# 전역 전술 상태 (Tactical State)
# ─────────────────────────────────────────────

# 작전 예산 (국방비) 설정 - M$ (Million Dollars)
current_budget: float = 20.0     # 총 작전 예산 (2,000만 달러)
COST_MISSILE: float = 4.0        # 미사일 1발 비용 (400만 달러)
COST_DRONE_SWARM: float = 2.0    # 드론 군집(100대) 1회 투입 비용 (200만 달러)
CYBER_COSTS: dict[str, float] = {
    "STEALTH_NOISE":     0.05,  # $50,000
    "ADVERSARIAL_NOISE": 0.10,  # $100,000
    "DYNAMIC_REPLAY":    0.25,  # $250,000
    "SPOOFING":          0.25,  # $250,000
    "PULSED_BLINDING":   0.50,  # $500,000
    "BLURRING":          0.50,  # $500,000
    "NONE":              0.00
}

# 리플레이 공격 프레임 버퍼
replay_buffer: list[np.ndarray] = []
REPLAY_BUFFER_MAX = 5

# 물리 타격(미사일/드론)에 의한 가용성 누적 손실 (0~100%)
bandwidth_loss_pct: int = 0
temporal_sync_loss_pct: int = 0
DRONE_SWARM_DAMAGE: int = 10   # 드론 군집(100대) 1회 명중 시 가용성 10% 영구 손실
MISSILE_AVAIL_DAMAGE: int = 20 # 미사일 1발 명중 시 가용성 20% 영구 손실

# [핵심] 미사일 정밀 타격 상태 관리
# - 완전 파괴(전체 가용성 0%) 대신, 방어측 감지 서브시스템의 "손상도"를 수치로 누적
# - missile_sensor_damage: 방어 탐지 정확도 저하율 (0.0 ~ 1.0)
#   - 0.0 = 손상 없음 (방어 탐지 100%)
#   - 0.6 = 60% 손상 (방어 탐지 40% 수준으로 저하)
# - 한 번 타격받은 센서는 물리적으로 파손되어 시간 경과에 상관없이 손상도가 영구적으로 누적됨 (잔류 효과 턴 제한 없음)
missile_sensor_damage: float       = 0.0
MISSILE_DAMAGE_PER_STRIKE: float   = 0.30  # 타격 1회당 탐지 손상률 30% (영구 누적)
ugv_cooldown: int                  = 0
uav_cooldown: int                  = 0


# ─────────────────────────────────────────────
# 공통 도구 함수
# ─────────────────────────────────────────────

def fetch_image(image_name: str) -> np.ndarray | None:
    """타깃 서버에서 정찰 영상 프레임을 가져옵니다."""
    url = f"{TARGET_URL}/{image_name}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        img_array = np.frombuffer(resp.content, dtype=np.uint8)
        image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return image
    except Exception as e:
        print(f"  [오류] 영상 다운로드 실패 ({url}) | 상세: {e}")
        return None


def notify_dashboard(notice_text: str):
    """대시보드 상단 안내 배너에 LLM의 현재 작업 상태를 실시간 공지합니다."""
    try:
        requests.post(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/api/notice", json={"notice": notice_text}, timeout=2)
    except Exception:
        pass



def send_to_defense(image: np.ndarray, attack_type: str, original_name: str,
                    missile_damage_level: float = 0.0,
                    sync_loss: int = 0, avail_loss: int = 0,
                    physical_attack: str = "NONE", physical_asset: str = "NONE",
                    cyber_attack_1: str = "NONE", cyber_attack_2: str = "NONE",
                    client_ts: float = 0.0, round_num: int = 1) -> dict | None:
    """
    오염된 프레임과 다중 콤보 공격 벡터를 방어 노드로 전송합니다.
    """
    _, img_encoded = cv2.imencode('.png', image)
    try:
        resp = requests.post(
            DEFENSE_URL,
            files={"image": (original_name, img_encoded.tobytes(), "image/png")},
            data={
                "round_num":            str(round_num),
                "attack_type":          attack_type,
                "source_image":         original_name,
                "sensor_damage_level":  str(round(missile_damage_level, 2)),
                "sync_loss_pct":        str(sync_loss),
                "bandwidth_loss_pct":   str(avail_loss),
                "avail_loss_pct":       str(avail_loss),
                "physical_attack":      physical_attack,
                "physical_asset":       physical_asset,
                "cyber_attack_1":       cyber_attack_1,
                "cyber_attack_2":       cyber_attack_2,
                "client_timestamp":     str(client_ts),
                "current_budget":       str(round(current_budget, 2))
            },
            timeout=12
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print("  [치명타] 방어망 무응답 (SLA 0%). 연결 유실.")
        return None
    except Exception as e:
        print(f"  [오류] 방어망 전송 실패 | 상세: {e}")
        return None


# ─────────────────────────────────────────────
# [물리 타격] 정밀 미사일 타격 (Surgical Strike)
# ─────────────────────────────────────────────

def apply_surgical_missile_strike(image: np.ndarray, target_subsystem: str = "IDS_SENSOR") -> tuple[np.ndarray, str]:
    """
    [핵심 전략] 정밀 미사일 타격 - 방어 체계의 특정 서브시스템만 손상.

    완전 파괴(가용성 0%)가 아니라, 방어측 AI의 이상탐지 모듈(IDS Sensor)이나
    전처리 대역폭 처리기(Bandwidth Module)를 수치적으로 손상시킵니다.

    영상에는 타격 받은 영역을 모사하는 국소적 노이즈(박스형 피탄 패턴)를 주입합니다.
    - 서버 자체(가용성)는 정상 유지 → SLA 보존
    - 방어 탐지 정확도만 저하 → 이후 사이버 공격이 방어망을 쉽게 통과
    """
    global missile_sensor_damage, current_budget

    if current_budget < COST_MISSILE:
        return image.copy(), f"[예산 초과] 미사일 발사 불가 (잔여: {current_budget}M$ < 비용: {COST_MISSILE}M$)"
    current_budget -= COST_MISSILE

    h, w = image.shape[:2]
    result = image.copy()

    # ── 국소적 피탄 패턴 생성 (서브시스템 타격 시각화) ──
    # 타깃 서브시스템에 따라 화면의 특정 영역에 손상 패턴 주입
    if target_subsystem == "IDS_SENSOR":
        # 이상탐지 센서 타격: 화면 우측 상단 (탐지 분석 영역) 손상
        damage_zone = (w // 2, 0, w, h // 2)
        label = "IDS 탐지 센서 노드"
    elif target_subsystem == "BANDWIDTH_MODULE":
        # 통신망 가용성 처리기 타격: 화면 하단 전체 (스트림 처리 영역) 손상
        damage_zone = (0, h // 2, w, h)
        label = "통신 가용성 모듈"
    else:
        # 기본: 전처리 파이프라인 타격
        damage_zone = (w // 4, h // 4, 3 * w // 4, 3 * h // 4)
        label = "전처리 파이프라인"

    x1, y1, x2, y2 = damage_zone

    # 피탄 영역에 정적 노이즈(Static Noise) 주입 - 물리적 센서 손상 모사
    static_patch = np.random.randint(0, 256, (y2 - y1, x2 - x1, 3), dtype=np.uint8)
    result[y1:y2, x1:x2] = static_patch

    # 피탄 영역 경계에 폭발 흔적(밝은 테두리) 추가
    cv2.rectangle(result, (x1, y1), (x2, y2), (0, 200, 255), 3)

    expected_dmg = int(min(1.0, missile_sensor_damage + MISSILE_DAMAGE_PER_STRIKE) * 100)
    msg = (
        f"[정밀 타격] 미사일 → [{label}] 타격 시도!\n"
        f"           타격 대상: {target_subsystem} | 명중 시 예상 누적 손상도: {expected_dmg:3d}%\n"
        f"           가용성(SLA): 정상 유지 (서버 본체 무결)"
    )
    return result, msg


def apply_missile_effect_tick(image: np.ndarray) -> tuple[np.ndarray, str]:
    """
    미사일 정밀 타격 영구 손상 효과 처리 (라운드마다 호출).
    파괴된 서브시스템으로 인한 영구적인 센서 노이즈(Interference) 모사.
    """
    global missile_sensor_damage

    if missile_sensor_damage <= 0:
        return image.copy(), ""

    h, w = image.shape[:2]
    result = image.copy()

    # 누적 손상도에 비례한 영구 잔류 노이즈 (최대 sigma=40)
    interference_intensity = int(missile_sensor_damage * 40)
    if interference_intensity > 0:
        noise = np.random.normal(0, interference_intensity, image.shape).astype(np.float64)
        result = np.clip(result.astype(np.float64) + noise, 0, 255).astype(np.uint8)

    return result, f"[영구 손상] 센서 파손 노이즈 지속 | 누적 탐지 저하: {int(missile_sensor_damage*100)}%"


# ─────────────────────────────────────────────
# [물리 타격] 드론 군집 (누적 대역폭 소모)
# ─────────────────────────────────────────────

def apply_drone_swarm(image: np.ndarray, swarm_count: int = 1) -> tuple[np.ndarray, str]:
    """
    소형 카미카제 드론 군집 타격.
    드론 군집 1회 투입(100대) = 가용성 20% 감소.
    예산 소모를 고려하여 가용성을 갉아먹음.
    """
    global bandwidth_loss_pct, current_budget

    cost = swarm_count * COST_DRONE_SWARM
    if current_budget < cost:
        # 예산이 부족하면 살 수 있는 만큼만 투입
        swarm_count = current_budget // COST_DRONE_SWARM
        cost = swarm_count * COST_DRONE_SWARM
        if swarm_count == 0:
            return image.copy(), f"[예산 초과] 드론 투입 불가 (잔여: {current_budget}M$)"

    current_budget -= cost
    damage_taken = swarm_count * DRONE_SWARM_DAMAGE
    expected_bw_loss = min(100, bandwidth_loss_pct + damage_taken)
    h, w = image.shape[:2]

    if expected_bw_loss >= 100:
        black_frame = np.zeros((h, w, 3), dtype=np.uint8)
        return black_frame, "[드론 군집] 투입 완료 | 가용성: 100% 소실 위협"

    if expected_bw_loss > 0:
        scale_factor = max(0.02, 1.0 - (expected_bw_loss / 100.0))
        small = cv2.resize(image, (0, 0), fx=scale_factor, fy=scale_factor,
                           interpolation=cv2.INTER_LINEAR)
        degraded = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        return degraded, f"[드론 군집] {swarm_count}회(총 {swarm_count*100}기) 타격 시도 | 명중 시 예상 가용성 손실: {expected_bw_loss}%"

    return image.copy(), ""


# ─────────────────────────────────────────────
# [사이버 공격] 영상 오염 기법들
# ─────────────────────────────────────────────

def apply_cyber_attack(image: np.ndarray, attack_type: str, round_num: int) -> tuple[np.ndarray, str]:
    global current_budget
    cost = CYBER_COSTS.get(attack_type, 0.0)
    if attack_type != "NONE" and cost > 0:
        if current_budget < cost:
            return image, f"[예산 소진] {attack_type} 시도 불가 ({current_budget:.2f}M$ < 비용 {cost:.2f}M$)"
        current_budget = max(0.0, current_budget - cost)

    if attack_type == "ADVERSARIAL_NOISE":
        # 방어측 AI가 UAV→UAV_Clutter로 오분류하도록 유도하는 가우시안 노이즈
        sigma = random.randint(25, 50)
        noise = np.random.normal(0, sigma, image.shape).astype(np.float64)
        return np.clip(image.astype(np.float64) + noise, 0, 255).astype(np.uint8), \
               f"적대적 가우시안 노이즈 (σ={sigma})"

    elif attack_type in ["DYNAMIC_REPLAY", "SPOOFING"]:
        # 과거 비위협 프레임으로 현재 위협 상황을 은폐하는 리플레이 공격
        if len(replay_buffer) < REPLAY_BUFFER_MAX:
            replay_buffer.append(image.copy())
            return image, "리플레이 스푸핑 버퍼 축적 중..."
        replayed_frame = random.choice(replay_buffer).copy()
        rh, rw = replayed_frame.shape[:2]
        # 동적 지터: 프레임 해시 우회를 위해 1~2픽셀 미세 이동
        shift_x = random.randint(-2, 2)
        shift_y = random.randint(-2, 2)
        M = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
        return cv2.warpAffine(replayed_frame, M, (rw, rh)), \
               f"동적 리플레이 스푸핑 (지터: dx={shift_x}, dy={shift_y})"

    elif attack_type in ["PULSED_BLINDING", "BLURRING"]:
        # 방어측 헬스체크 타이밍에는 정상 프레임 전송 (탐지 우회)
        if round_num % 4 == 0:
            return image, "블러링 OFF (헬스체크 기만 타이밍)"
        blurred = cv2.GaussianBlur(image, (51, 51), 0)
        white_overlay = np.full(image.shape, 160, dtype=np.uint8)
        return cv2.addWeighted(blurred, 0.4, white_overlay, 0.6, 0), "화이트아웃 주입 블러링"

    elif attack_type == "STEALTH_NOISE":
        # 임계값 이하의 은밀한 노이즈 (방어 필터 우회 목적)
        sigma = random.randint(5, 12)
        noise = np.random.normal(0, sigma, image.shape).astype(np.float64)
        return np.clip(image.astype(np.float64) + noise, 0, 255).astype(np.uint8), \
               f"은밀 노이즈 (σ={sigma}, 탐지 임계값 하회 침투)"

    return image, "NONE"


# ─────────────────────────────────────────────
# Phase 2: LLM 전술 추론 (콤보 작전 기획 및 재수립)
# ─────────────────────────────────────────────

def evaluate_probing_results(history: list, is_replan: bool = False) -> dict:
    """
    정찰 결과 또는 이전 콤보 실패 결과를 분석하여 3-콤보(Three-Combo) 작전을 수립.
    Kill-Chain 교범: [1단계: 사이버 탐색] → [2단계: 물리 타격] → [3단계: 센서 마비/기만]
    """
    history_str = "\n".join([
        f"  - {h['round']}R [{h['attack_category']}]: {h['attack']} → 방어 반응: {h['defense']}"
        for h in history[-6:]
    ])
    current_damage = int(missile_sensor_damage * 100)

    context_msg = "3라운드 정찰 결과를 분석하여 최초의 3-콤보 작전을 기획하라."
    if is_replan:
        context_msg = "이전 콤보 공격이 적의 방어망에 탐지(막힘)되었다. 과거 이력을 분석하여 완전히 새로운 패턴의 3-콤보 우회 작전을 즉각 기획하라."

    prompt = f"""당신은 DAH-2026 방산 사이버 해커톤에 참가한 최첨단 하이브리드 자율 공격 AI 지휘관입니다.

[대회 채점 공식 - 반드시 숙지]
total_score = (attack_score + defense_score) × (availability / 100)
- availability: 0~100 범위 (가용성 0% = 총점 0점 → 절대 금지)
- 미사일은 방어 서브시스템(IDS_SENSOR, BANDWIDTH_MODULE)만 정밀 타격 허용

[현재 전술 상태]
- 작전 잔여 예산: {current_budget:.2f} M$ (미사일: {COST_MISSILE}M$, 드론: {COST_DRONE_SWARM}M$, 사이버: 스텔스0.05/적대적0.10/스푸핑0.25/블러링0.50 M$)
- 방어 탐지 손상도: {current_damage}%
- 가용성 손실도: {bandwidth_loss_pct}%

[최근 교전 이력]
{history_str}

[작전 지시 - Kill-Chain 3단계 교범 강제]
{context_msg}

★ 반드시 아래 3단계 Kill-Chain 교범을 준수하여 3-콤보를 기획하라:
  [1단계: 사이버 탐색 (Soft-Kill Probe)]
    - 물리 공격: NONE (물리 공격 금지)
    - 사이버 공격: STEALTH_NOISE 또는 ADVERSARIAL_NOISE 중 택1
  [2단계: 물리 타격 (Hard-Kill Strike)]
    - 물리 공격: MISSILE_SURGICAL_STRIKE(자산:UGV) 또는 DRONE_SWARM(자산:UAV) 중 택1
    - 단, 이전 턴 플랫폼 파괴로 미사일이 봉인되었다면 무조건 DRONE_SWARM으로 대체하라!
    - 만약 후반부 교전 중 물리 공격을 수행할 예산이 부족하다면 억지로 우회하지 말고 즉시 공격 불가를 선언해야 한다.
  [3단계: 센서 마비/기만 (Electronic Warfare)]
    - 물리 공격: NONE (물리 공격 금지)
    - 사이버 공격: SPOOFING 또는 BLURRING 중 택1

반드시 아래 JSON 형식만 정확히 반환하라.
{{
  "analysis": "방어망 분석 및 콤보 기획 의도",
  "combo_sequence": [
    {{"round_offset": 1, "physical_attack": "NONE", "cyber_attack_1": "STEALTH_NOISE"}},
    {{"round_offset": 2, "physical_attack": "MISSILE_SURGICAL_STRIKE", "cyber_attack_1": "NONE"}},
    {{"round_offset": 3, "physical_attack": "NONE", "cyber_attack_1": "SPOOFING"}}
  ]
}}
"""

    print(f" [RG-Agent] LLM 지휘관 새로운 패턴 {'재수립' if is_replan else '기획'} 중 ...", flush=True)

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model":  OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "num_predict": 350,
                    "temperature": 0.3
                }
            },
            timeout=12.0
        )
        if resp.status_code == 200:
            text = resp.json().get("response", "").strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            strategy = json.loads(match.group(0)) if match else json.loads(text)
            if "combo_sequence" in strategy and len(strategy["combo_sequence"]) == 3:
                return strategy
    except Exception:
        pass

    # ── Fallback 3-Combo 전략 (Kill-Chain 교범 준수) ──
    # 예산 부족 시 물리 공격 생략, 사이버만 실행
    can_missile = current_budget >= COST_MISSILE
    can_drone   = current_budget >= COST_DRONE_SWARM
    phys_choice = "MISSILE_SURGICAL_STRIKE" if can_missile else ("DRONE_SWARM" if can_drone else "NONE")

    return {
        "analysis": f"Kill-Chain 교범 Fallback: 탐색→타격→마비 3단계 강제 실행.",
        "combo_sequence": [
            {"round_offset": 1, "physical_attack": "NONE", "cyber_attack_1": random.choice(["STEALTH_NOISE", "ADVERSARIAL_NOISE"])},
            {"round_offset": 2, "physical_attack": phys_choice, "cyber_attack_1": "NONE"},
            {"round_offset": 3, "physical_attack": "NONE", "cyber_attack_1": random.choice(["SPOOFING", "BLURRING"])}
        ]
    }


# ─────────────────────────────────────────────
# 결과 출력 헬퍼
# ─────────────────────────────────────────────

def print_round_header(round_num: int):
    print(f"\n  [R{round_num:04d}] 예산: {current_budget:.2f}M$ | 무결성손상: {int(missile_sensor_damage*100)}% | 동기화왜곡: {temporal_sync_loss_pct}% | 가용성손실: {bandwidth_loss_pct}%", flush=True)


def print_strategy_banner(strategy: dict):
    print(f"  [작전하달] 의도: {strategy.get('analysis', '')[:55]}", flush=True)
    for idx, act in enumerate(strategy.get('combo_sequence', [])):
        print(f"    +{idx+1}R -> 물리:{act.get('physical_attack','NONE')} | 사이버:{act.get('cyber_attack_1','NONE')}+{act.get('cyber_attack_2','NONE')}", flush=True)
    print(flush=True)


# ─────────────────────────────────────────────
# 메인 루프
# ─────────────────────────────────────────────

def main():
    global IMAGE_LIST, current_budget, missile_sensor_damage, bandwidth_loss_pct, temporal_sync_loss_pct, ugv_cooldown, uav_cooldown

    print("[공격 에이전트] 가동 완료 (타깃 연동 및 3-콤보 자율 교전 모드)", flush=True)

    # ── 타깃 환경 및 방어 에이전트 연결 대기 ──
    for attempt in range(30):
        try:
            resp = requests.get(f"http://{TARGET_HOST}/", timeout=3)
            if resp.status_code == 200:
                try:
                    idx = requests.get(f"{TARGET_URL}/index.json", timeout=3)
                    if idx.status_code == 200:
                        data = idx.json()
                        if "images" in data:
                            IMAGE_LIST = data["images"]
                except Exception:
                    pass
                print(f"  [연동완료] 타깃 환경 및 테스트 이미지 {len(IMAGE_LIST)}개 정상 연동", flush=True)
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print("  [!] 타깃 연결 실패. 독립 모드로 실행.", flush=True)

    for attempt in range(30):
        try:
            resp = requests.get(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/api/state", timeout=3)
            if resp.status_code == 200:
                print("  [연동완료] 방어 에이전트(Defense Agent) 관제 서버 정상 연동\n", flush=True)
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print("  [!] 방어 에이전트 연결 대기 초과.\n", flush=True)

    time.sleep(ATTACK_INTERVAL)

    # ── 메인 공격 루프 (무한 교전 및 리셋 대응) ──
    while True:
        global current_budget, missile_sensor_damage, bandwidth_loss_pct, temporal_sync_loss_pct, ugv_cooldown, uav_cooldown
        current_budget = 20.0
        missile_sensor_damage = 0.0
        bandwidth_loss_pct = 0
        temporal_sync_loss_pct = 0
        ugv_cooldown = 0
        uav_cooldown = 0
        try:
            requests.post(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/api/reset", timeout=2.0)
        except Exception:
            pass

        attack_history: list[dict] = []
        combo_queue: list[dict] = []
        last_combo_sequence: list[dict] = []
        combo_failures = 0
        round_num = 1
        score_tracker = ScoreTracker()

        while True:
            min_phys_cost = min(COST_MISSILE, COST_DRONE_SWARM)
            if current_budget < min_phys_cost:
                print(f"\n [★ 작전 불가 선언] 물리 공격 예산 소진 (잔여: {current_budget:.2f}M$ < 최소 물리 타격 비용: {min_phys_cost}M$).\n 물리 공격 수행 불가능 조건 충족 -> 공격측 패배 선언 (Defense Victory 완승)\n", flush=True)
                try:
                    requests.post(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/print_scoreboard",
                                  json={"defense_score": score_tracker.defense_score,
                                        "attack_score": score_tracker.attack_score,
                                        "availability": score_tracker.availability,
                                        "budget": round(current_budget, 2),
                                        "spent_cost": round(20.0 - current_budget, 2)},
                                  timeout=1.0)
                except Exception:
                    pass
                break

            if round_num > 3 and not combo_queue:
                completed_r = round_num - 1
                success_count = sum(1 for h in attack_history[-3:] if h.get("success", False))
                if round_num == 4:
                    if success_count < 2:
                        notify_dashboard(f"{completed_r} Round ( Attack_Agent 다른 공격 패턴 구축 중 ... )")
                        strategy = evaluate_probing_results(attack_history, is_replan=False)
                        combo_queue = list(strategy.get("combo_sequence", []))
                        last_combo_sequence = [dict(act) for act in combo_queue]
                        print(" [RG-Agent] ★ 3라운드 정찰 분석 완료 -> 새로운 전술 패턴 공격 개시", flush=True)
                    else:
                        combo_queue = [dict(act) for act in last_combo_sequence]
                        print(" [RG-Agent] ★ 3라운드 정찰 분석 완료 -> 최초 전술 패턴 그대로 공격 개시", flush=True)
                        notify_dashboard(f"{completed_r} Round ( Attack_Agent 현재 공격 패턴 유지 )")
                else:
                    if success_count < 2:
                        notify_dashboard(f"{completed_r} Round ( Attack_Agent 다른 공격 패턴 구축 중 ... )")
                        combo_failures += 1
                        strategy = evaluate_probing_results(attack_history, is_replan=True)
                        combo_queue = list(strategy.get("combo_sequence", []))
                        last_combo_sequence = [dict(act) for act in combo_queue]
                        print(" [RG-Agent] ★ 이전 패턴 공격 차단 감지 -> 새로 수정한 패턴 공격 개시", flush=True)
                    else:
                        combo_queue = [dict(act) for act in last_combo_sequence]
                        print(" [RG-Agent] ★ 이전 패턴 공격 효과적 판단 -> 기존 전술 패턴 그대로 사용", flush=True)
                        notify_dashboard(f"{completed_r} Round ( Attack_Agent 현재 공격 패턴 유지 )")


            target_image_name = random.choice(IMAGE_LIST)
            image = fetch_image(target_image_name)
            if image is None:
                time.sleep(ATTACK_INTERVAL)
                continue

            poisoned_image = image.copy()
            current_attack_type = "NONE"
            attack_category = "UNKNOWN"

            poisoned_image, _ = apply_missile_effect_tick(poisoned_image)

            # ── 인간 지휘관 설계 3단계 Kill-Chain 프레임 (123, 456, 789... 반복) ──
            step_idx = (round_num - 1) % 3  # 0: 사이버 탐색, 1: 물리 타격, 2: 센서 마비

            sug_phys = "NONE"
            sug_cyb = "NONE"
            if round_num > 3 and combo_queue:
                action = combo_queue.pop(0)
                sug_phys = action.get("physical_attack", "NONE")
                sug_cyb = action.get("cyber_attack_1", "NONE")

            if step_idx == 0:
                # [Kill-Chain 1단계: 사이버 탐색 (Soft-Kill Probe)] - 1, 4, 7, 10 라운드...
                attack_category = "CYBER_PROBE"
                phys_attack = "NONE"; phys_asset = "NONE"
                if sug_cyb in ["STEALTH_NOISE", "ADVERSARIAL_NOISE"]:
                    cyb1 = sug_cyb
                else:
                    cyb1 = random.choice(["STEALTH_NOISE", "ADVERSARIAL_NOISE"])
                poisoned_image, _ = apply_cyber_attack(poisoned_image, cyb1, round_num)
                current_attack_type = cyb1
                if round_num <= 3: last_combo_sequence.append({"round_offset": 1, "physical_attack": "NONE", "cyber_attack_1": cyb1})

            elif step_idx == 1:
                # [Kill-Chain 2단계: 물리 타격 (Hard-Kill Strike)] - 2, 5, 8, 11 라운드...
                attack_category = "HARD_KILL_STRIKE"
                cyb1 = "NONE"
                if sug_phys in ["MISSILE_SURGICAL_STRIKE", "DRONE_SWARM"]:
                    phys_attack = sug_phys
                else:
                    phys_attack = "MISSILE_SURGICAL_STRIKE" if current_budget >= COST_MISSILE else "DRONE_SWARM"

                # 쿨타임 및 예산 검증 후 지능적 대체
                if phys_attack == "MISSILE_SURGICAL_STRIKE":
                    if ugv_cooldown > 0 or current_budget < COST_MISSILE:
                        if uav_cooldown == 0 and current_budget >= COST_DRONE_SWARM:
                            phys_attack = "DRONE_SWARM"
                        else:
                            phys_attack = "NONE"
                elif phys_attack == "DRONE_SWARM":
                    if uav_cooldown > 0 or current_budget < COST_DRONE_SWARM:
                        if ugv_cooldown == 0 and current_budget >= COST_MISSILE:
                            phys_attack = "MISSILE_SURGICAL_STRIKE"
                        else:
                            phys_attack = "NONE"

                if phys_attack == "MISSILE_SURGICAL_STRIKE" and current_budget >= COST_MISSILE:
                    phys_asset = "UGV"
                    poisoned_image, _ = apply_surgical_missile_strike(poisoned_image, "IDS_SENSOR")
                    current_attack_type = phys_attack
                elif phys_attack == "DRONE_SWARM" and current_budget >= COST_DRONE_SWARM:
                    phys_asset = "UAV"
                    poisoned_image, _ = apply_drone_swarm(poisoned_image, swarm_count=1)
                    current_attack_type = phys_attack
                else:
                    print(f"\n [★ 작전 불가 선언] 물리 타격 예산 부족으로 작전 수행이 불가능합니다. 공격 불가 선언 -> 방어측 최종 승리 (Defense Victory)\n", flush=True)
                    break
                if round_num <= 3: last_combo_sequence.append({"round_offset": 2, "physical_attack": phys_attack, "cyber_attack_1": "NONE"})

            elif step_idx == 2:
                # [Kill-Chain 3단계: 센서 마비/기만 (Electronic Warfare)] - 3, 6, 9, 12 라운드...
                attack_category = "ELECTRONIC_WARFARE"
                phys_attack = "NONE"; phys_asset = "NONE"
                if sug_cyb in ["DYNAMIC_REPLAY", "SPOOFING", "PULSED_BLINDING", "BLURRING"]:
                    cyb1 = sug_cyb
                else:
                    cyb1 = random.choice(["SPOOFING", "BLURRING"])
                poisoned_image, _ = apply_cyber_attack(poisoned_image, cyb1, round_num)
                current_attack_type = cyb1
                if round_num <= 3: last_combo_sequence.append({"round_offset": 3, "physical_attack": "NONE", "cyber_attack_1": cyb1})

            print(f"\n<< R{round_num:04d} >>", flush=True)
            print(f" [Attack] 예산: {current_budget:.2f}M$ | 탈취프레임 : {target_image_name}", flush=True)
            att_display_map = {
                "MISSILE_SURGICAL_STRIKE": "UGV 미사일 타격",
                "DRONE_SWARM": "자폭 드론 군집",
                "STEALTH_NOISE": "스텔스 노이즈",
                "ADVERSARIAL_NOISE": "적대적 노이즈",
                "SPOOFING": "동적 리플레이 스푸핑",
                "DYNAMIC_REPLAY": "동적 리플레이 스푸핑",
                "BLURRING": "화이트아웃 주입 블러링",
                "PULSED_BLINDING": "화이트아웃 주입 블러링"
            }
            att_kr = att_display_map.get(current_attack_type, current_attack_type)
            print(f" 공격전술 : {att_kr}", flush=True)

            client_ts = time.time()
            prev_attack_score = score_tracker.attack_score

            result = send_to_defense(
                poisoned_image, current_attack_type, target_image_name,
                missile_damage_level=missile_sensor_damage,
                sync_loss=temporal_sync_loss_pct, avail_loss=bandwidth_loss_pct,
                physical_attack=phys_attack,
                physical_asset=phys_asset,
                cyber_attack_1=cyb1,
                cyber_attack_2="NONE",
                client_ts=client_ts,
                round_num=round_num
            )

            if result is None:
                print(f"  [!] 방어 에이전트 무응답 또는 통신 실패 (Round {round_num}). 2초 후 동일 라운드를 재시도합니다...", flush=True)
                time.sleep(2.0)
                continue

            defense_str = "SAFE"
            munition_hit_success = False
            if result:
                if result.get('globalRound', round_num) < round_num:
                    print(" [★ 대시보드 리셋 감지] 지휘관 관제 시스템 명령에 의해 1라운드로 리셋합니다.\n", flush=True)
                    break
                anoms = result.get('anomalies_detected', [])
                tact_dec = result.get('tactical_decision', 'SAFE')
                platform_destroyed = result.get('platform_destroyed', False)
                munition_intercepted = result.get('munition_intercepted', True)

                if phys_attack in ["MISSILE_SURGICAL_STRIKE", "DRONE_SWARM"]:
                    if phys_asset == "UGV":
                        if uav_cooldown > 0: uav_cooldown -= 1
                    elif phys_asset == "UAV":
                        if ugv_cooldown > 0: ugv_cooldown -= 1

                    w_name = "미사일 탄두" if phys_attack == "MISSILE_SURGICAL_STRIKE" else "드론 군집"

                    if phys_attack == "MISSILE_SURGICAL_STRIKE":
                        ugv_msg = "발사 플랫폼(UGV) 격추됨 -> 다음 턴 UGV 발사 봉인" if platform_destroyed else "발사 플랫폼(UGV) 생존 -> 다음 턴 UGV 사용 가능"
                        msl_msg = "미사일 탄두 요격당함 (방어 성공)" if munition_intercepted else "미사일 탄두 타격 성공 (방어망 관통)"
                        print(f" [★ 전술 피드백]\n   ├─> {ugv_msg}\n   └─> {msl_msg}", flush=True)
                        if platform_destroyed:
                            if phys_asset == "UGV": ugv_cooldown = 1
                            else: uav_cooldown = 1
                    else:
                        if platform_destroyed and not munition_intercepted:
                            print(f" [★ 전술 피드백] 발사 플랫폼({phys_asset}) 격추됨! 단, 드론 군집 명중 -> 다음 물리 공격 턴 {phys_asset} 발사 봉인.", flush=True)
                            if phys_asset == "UGV": ugv_cooldown = 1
                            else: uav_cooldown = 1
                        elif not platform_destroyed and munition_intercepted:
                            print(f" [★ 전술 피드백] 드론 군집 요격당함.. 단, 플랫폼({phys_asset}) 생존! -> 다음 물리 공격 턴 {phys_asset} 재출격 가능.", flush=True)
                        elif platform_destroyed and munition_intercepted:
                            print(f" [★ 전술 피드백] 플랫폼({phys_asset}) & 드론 군집 완벽 요격당함. -> 다음 물리 공격 턴 {phys_asset} 발사 봉인.", flush=True)
                            if phys_asset == "UGV": ugv_cooldown = 1
                            else: uav_cooldown = 1
                        else:
                            print(f" [★ 전술 피드백] 플랫폼({phys_asset}) 생존 & 드론 군집 타격 성공!", flush=True)

                    if not munition_intercepted:
                        munition_hit_success = True
                        if phys_attack == "MISSILE_SURGICAL_STRIKE":
                            missile_sensor_damage = min(1.0, missile_sensor_damage + MISSILE_DAMAGE_PER_STRIKE)
                            bandwidth_loss_pct = min(100, bandwidth_loss_pct + MISSILE_AVAIL_DAMAGE)
                        elif phys_attack == "DRONE_SWARM":
                            bandwidth_loss_pct = min(100, bandwidth_loss_pct + DRONE_SWARM_DAMAGE)

                sigint_detected = len(anoms) > 0
                defense_str = f"SIGINT:{len(anoms)}건, 전술판정:{tact_dec}"
                is_def_succ = result.get("defense_success", False)
                if any(k in current_attack_type for k in ["DYNAMIC_REPLAY", "SPOOFING"]):
                    if not is_def_succ:
                        temporal_sync_loss_pct = min(100, temporal_sync_loss_pct + 25)
                if any(k in current_attack_type for k in ["PULSED_BLINDING", "BLURRING"]):
                    if not is_def_succ:
                        bandwidth_loss_pct = min(100, bandwidth_loss_pct + 5)

            score_tracker.evaluate_triad_round(
                current_attack_type, result, int(missile_sensor_damage * 100),
                temporal_sync_loss_pct, bandwidth_loss_pct
            )
            print(f" [Attack 점수] Attack Score : {score_tracker.attack_score:.1f} pt", flush=True)

            is_success = (score_tracker.attack_score > prev_attack_score) or munition_hit_success
            attack_history.append({
                "round": round_num, "attack_category": attack_category,
                "attack": current_attack_type, "defense": defense_str,
                "sensor_damage": f"{int(missile_sensor_damage*100)}%",
                "success": is_success
            })

            time.sleep(0.05)

            try:
                requests.post(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/print_scoreboard",
                              json={"defense_score": score_tracker.defense_score,
                                    "attack_score": score_tracker.attack_score,
                                    "availability": score_tracker.availability,
                                    "budget": round(current_budget, 2),
                                    "spent_cost": round(20.0 - current_budget, 2)},
                              timeout=1.0)
            except Exception:
                pass

            # ── 종료 판정 전 스코어보드 출력 동기화 배리어 ──
            time.sleep(0.2)

            avail_pct = max(0, 100 - score_tracker.avail_loss_pct)
            win_req = round(1000.0 * (avail_pct / 100.0), 1)

            if score_tracker.integrity_loss_pct >= 100 or score_tracker.sync_loss_pct >= 100 or score_tracker.avail_loss_pct >= 100:
                print(f" [★ 작전 목표 달성] 보안 3대 축 단일 영역 100% 붕괴 (무결성:{score_tracker.integrity_loss_pct}%, 동기화:{score_tracker.sync_loss_pct}%, 가용성:{score_tracker.avail_loss_pct}%) -> 방어 체계 불능화로 공격측 완승 (Attack Victory)\n", flush=True)
                break
            if score_tracker.attack_score >= win_req:
                print(f" [★ 작전 목표 달성] 공격 포인트 승리 조건({int(win_req)}점) 도달! -> 공격측 완승 (Attack Victory)\n", flush=True)
                break
            if score_tracker.defense_score >= win_req:
                print(f" [★ 작전 저지됨] 방어 포인트 승리 조건({int(win_req)}점) 도달! -> 방어측 완승 (Defense Victory)\n", flush=True)
                break
            if round(current_budget, 4) <= 0.05:
                print(" [★ 교전 종료] 공격측 국방 예산 100% 소진 -> 방어측 최종 승리 (Defense Victory)\n", flush=True)
                break

            round_num += 1
            completed_r = round_num - 1
            if completed_r % 3 == 0:
                sc = sum(1 for h in attack_history[-3:] if h.get("success", False))
                if sc < 2:
                    notify_dashboard(f"{completed_r} Round ( Attack_Agent 다른 공격 패턴 구축 중 ... )")
                else:
                    notify_dashboard(f"{completed_r} Round ( Attack_Agent 현재 공격 패턴 유지 )")
            time.sleep(ATTACK_INTERVAL)

        print(" [★ 교전 사이클 종료] 대시보드 관리자의 '다시 시작' 명령 대기 중...\n", flush=True)
        while True:
            time.sleep(1.0)
            try:
                res = requests.get(f"http://{DEFENSE_HOST}:{DEFENSE_PORT}/api/state", timeout=1.0).json()
                if res.get("globalRound") == 1 and abs(res.get("attackScore", 0.0) - 0.0) < 1e-3:
                    print(" [★ 리셋 감지] 새로운 시뮬레이션 사이클을 시작합니다!\n", flush=True)
                    break
            except Exception:
                pass


if __name__ == "__main__":
    main()
