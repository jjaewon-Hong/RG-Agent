import os
import time
import random
import signal
import ctypes
import numpy as np
import cv2
import onnxruntime as ort
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import logging
import urllib.request
import urllib.error
import json
import re

from scorer import ScoreTracker

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

app = Flask(__name__)
CORS(app)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

score_tracker = ScoreTracker()

global_sim_state = {
    "globalRound": 1,
    "budget": 15.0,
    "spentCost": 0.0,
    "attackScore": 0.0,
    "defenseScore": 0.0,
    "availLoss": 0,
    "syncLoss": 0,
    "integLoss": 0,
    "attackType": "대기 중",
    "defenseName": "대기 중",
    "defenseSuccess": True,
    "outcomeStatus": "대기 중",
    "notice": "1 Round ( LLM 최초 공격 패턴 구축 중 ... )",
    "historyLogs": [],
    "gameOver": False,
    "winner": "",
    "winReason": "",
    "winRequirement": 1000,
    "isPaused": False
}

signal.signal(signal.SIGTERM, lambda s, f: os._exit(0))
signal.signal(signal.SIGINT, lambda s, f: os._exit(0))

def get_cpp_engine():
    try:
        so_path = os.path.join(os.path.dirname(__file__), "tactical_engine.so")
        cpp_path = os.path.join(os.path.dirname(__file__), "tactical_engine.cpp")
        if not os.path.exists(so_path):
            print("[시스템] 전술 엔진(C++) 네이티브 컴파일 중...", flush=True)
            os.system(f"g++ -shared -fPIC -o {so_path} {cpp_path}")
        engine = ctypes.CDLL(so_path)
        engine.evaluate_threat.argtypes = [ctypes.c_float, ctypes.c_float]
        engine.evaluate_threat.restype = ctypes.c_char_p
        print("[시스템] C++ 전술 엔진 로드 완료.", flush=True)
        return engine
    except Exception as e:
        print(f"[오류] 전술 엔진 로드 실패: {e}", flush=True)
        return None

def get_onnx_session():
    try:
        onnx_path = os.path.join(os.path.dirname(__file__), "reasoning_guard_engine.onnx")
        session = ort.InferenceSession(onnx_path)
        print("[시스템] ONNX 지도학습 추론 엔진 로드 완료. (Adversarial Training 반영됨)", flush=True)
        return session
    except Exception as e:
        print(f"[오류] ONNX 모델 로드 실패: {e}", flush=True)
        return None

tactical_engine = get_cpp_engine()
ort_session = get_onnx_session()

CLASS_NAMES = ["UGV", "UAV", "Rocket", "UAV_Clutter"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

frame_phash_buffer: list[np.ndarray] = []
FRAME_PHASH_MAX = 15
PHASH_HAMMING_THRESHOLD = 10

prev_lk_gray = None
prev_lk_pts = None

zero_trust_radar_active = False

def query_llm_caution_verify(phys_attack: str, phys_asset: str, prob_dict: dict) -> tuple[bool, str]:
    main_threat = max(prob_dict.get("UGV", 0), prob_dict.get("UAV", 0), prob_dict.get("Rocket", 0))
    clutter = prob_dict.get("UAV_Clutter", 0)

    if main_threat >= 0.30 or main_threat >= clutter * 0.8:
        return True, f"LLM 지휘관 이미지 2차 검증 승인 (위협신호 {main_threat:.2f} 감지 -> 교전 발사 허가)"
    else:
        return False, f"LLM 지휘관 이미지 2차 검증 반려 (클러터 {clutter:.2f} 우세 -> 오인사격 방지 발사 취소)"


def evaluate_physical_intercept(phys_attack: str, phys_asset: str, sensor_dmg: float, decision: str = "SAFE", prob_dict: dict = None) -> tuple[bool, bool, str]:
    global countermeasure_inventory
    if prob_dict is None:
        prob_dict = {"UGV": 0.0, "UAV": 0.0, "Rocket": 0.0, "UAV_Clutter": 1.0}

    intercept_approved = False
    decision_reason = ""

    if decision == "DANGER":
        intercept_approved = True
        decision_reason = "[★ 전술 판단: DANGER] 확실한 위협 포착 -> LLM 지휘관 질의 생략 및 즉시 100% 요격 발사 확정!"
    elif decision == "CAUTION":
        llm_ok, llm_msg = query_llm_caution_verify(phys_attack, phys_asset, prob_dict)
        intercept_approved = llm_ok
        decision_reason = f"[★ 전술 판단: CAUTION] 위협 불확실 -> {llm_msg}"
    else:
        intercept_approved = False
        decision_reason = "[★ 전술 판단: SAFE/FAIL] 위협 인지 실패(기만/노이즈 관통) -> LLM 질의 없이 즉시 발사 취소"

    if phys_attack == "MISSILE_SURGICAL_STRIKE":
        asset_name = "UGV" if phys_asset == "UGV" else "UAV"

        if intercept_approved:
            platform_hit = (random.random() <= 0.70)
            munition_hit = (random.random() <= 0.70)
            ugv_msg = f"[{asset_name} 발사 플랫폼 요격 성공]" if platform_hit else f"[{asset_name} 발사 플랫폼 요격 실패 (생존)]"
            msl_msg = "[미사일 탄두 요격 성공 (70% 적중)]" if munition_hit else "[미사일 탄두 요격 실패 (30% 관통)]"
            msg = f"{decision_reason}\n   ├─> {ugv_msg}\n   └─> {msl_msg}"
        else:
            platform_hit = False
            munition_hit = False
            msg = f"{decision_reason}\n   ├─> [{asset_name} 발사 플랫폼 요격 실패 (미탐지)]\n   └─> [미사일 탄두 요격 실패 (탐지망 손상)]"

        return platform_hit, munition_hit, msg

    elif phys_attack == "DRONE_SWARM":
        if intercept_approved:
            intercept_success = (random.random() <= 0.40)
            platform_hit = intercept_success
            munition_hit = intercept_success
            if intercept_success:
                msg = f"{decision_reason}\n   └─> [UAV 모선 및 드론군집 요격 성공] 발칸포 명중 (드론 군집 물리 요격 성공률 40% 적중)"
            else:
                msg = f"{decision_reason}\n   └─> [UAV 모선 및 드론군집 요격 물리 실패] 위협 탐지 및 발칸포 사격했으나 100기 포화 공격 돌파 허용 (60% 관통 적중)"
        else:
            platform_hit = False
            munition_hit = False
            msg = f"{decision_reason}\n   └─> [UAV 모선 및 드론군집 요격 실패] 적 위협 타격 허용 (통신망 가용성 손실 입음)"

        return platform_hit, munition_hit, msg

    return True, True, "물리 공격 미탐지"


def compute_phash(image: np.ndarray) -> np.ndarray:
    # [1단계: 전처리] 조도 변화에 불변하도록 흑백 변환 후, 32x32 해상도로 축소해 미세 노이즈 1차 제거
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    
    # [2단계: 이미지 변환] 2차원 이산 코사인 변환(DCT)을 통해 이미지의 고유 특징을 좌상단에 강제 정렬
    dct = cv2.dct(resized)
    
    # [3단계: 이미지 핵심 특징 추출] 변조된 노이즈 완전히 버리고, 과거 프레임 복제 여부를 대조할 좌상단 8x8 핵심 영역만 추출
    dct_low = dct[:8, :8]
    
    # [4단계: 이미지 특징 추출본 생성] 중앙값 기준으로 이진화 하여, 동적 리플레이 스푸핑 차단하고 동기화 성능 보호
    median_val = np.median(dct_low)
    return (dct_low > median_val).flatten().astype(np.uint8)


def hamming_distance(h1: np.ndarray, h2: np.ndarray) -> int:
    return int(np.sum(h1 != h2))


def verify_replay_attack(image: np.ndarray, client_ts_str: str) -> tuple[bool, str, str]:
    global frame_phash_buffer, prev_lk_gray, prev_lk_pts
    tactic_choice = random.choice(["PHASH", "OPTICAL_FLOW"])

    try:
        if client_ts_str and client_ts_str != "0.0":
            client_ts = float(client_ts_str)
            now = time.time()
            if abs(now - client_ts) > 10.0:
                return True, "동적 타임스탬프 불일치 (과거 녹화 패킷 원천 차단)", "동적 지각 해시 검증 (Dynamic Replay Defense)"
    except ValueError:
        pass

    current_phash = compute_phash(image)
    is_phash_replay = False
    dist_val = 999

    for stored_phash in frame_phash_buffer:
        dist = hamming_distance(current_phash, stored_phash)
        if dist <= PHASH_HAMMING_THRESHOLD:
            is_phash_replay = True
            dist_val = dist
            break

    frame_phash_buffer.append(current_phash)
    if len(frame_phash_buffer) > FRAME_PHASH_MAX:
        frame_phash_buffer.pop(0)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    is_lk_anomaly = False
    lk_movement = 0.0

    if prev_lk_gray is not None and prev_lk_pts is not None and len(prev_lk_pts) > 0:
        try:
            if prev_lk_gray.shape != gray.shape:
                h_new, w_new = gray.shape
                h_old, w_old = prev_lk_gray.shape
                fx = w_new / float(w_old)
                fy = h_new / float(h_old)
                prev_lk_gray = cv2.resize(prev_lk_gray, (w_new, h_new))
                prev_lk_pts = prev_lk_pts * np.array([fx, fy], dtype=np.float32)

            # [1단계: 피라미드 Lucas-Kanade 광학 흐름 추적] 이전 프레임과 현재 프레임 간 특징점 50개의 물리적 이동 변위 추적
            next_pts, status, err = cv2.calcOpticalFlowPyrLK(prev_lk_gray, gray, prev_lk_pts, None, winSize=(15, 15), maxLevel=2)
            # 추적에 성공한 정상 특징점(status == 1)만 필터링하여 변위 계산 대상 확정
            good_new = next_pts[status == 1]
            good_old = prev_lk_pts[status == 1]
            if len(good_new) > 0:
                # [2단계: 평균 이동량 산출] 프레임 속 객체들이 이전 프레임 대비 평균 몇 픽셀 이동했는지 '실제 거리' 계산 
                lk_movement = float(np.mean(np.linalg.norm(good_new - good_old, axis=1)))
                # [3단계: 가짜 프레임 판정 및 동기화 보호]
                # 0.05px 미만 : 픽셀이 전혀 움직이지 않는 '정지 루프(Freeze) 스푸핑'으로 규정
                #  50px 초과  : 시공간 궤적이 비정상적으로 단절되는 '점프(Jump) 스푸핑'으로 규정
                if lk_movement < 0.05 or lk_movement > 50.0:
                    is_lk_anomaly = True  # 동기화 위협 감지 => 즉시 차단하여 동기화 보호
        except Exception:
            is_lk_anomaly = True

    prev_lk_gray = gray.copy()
    prev_lk_pts = cv2.goodFeaturesToTrack(gray, maxCorners=50, qualityLevel=0.01, minDistance=10)

    if tactic_choice == "PHASH":
        tactic_name = "동적 지각 해시 검증"
        if is_phash_replay:
            msg = f"pHash 유사 프레임 감지 (해밍 거리 {dist_val}bit ≤ 임계값 {PHASH_HAMMING_THRESHOLD}bit → 리플레이 스푸핑 차단)"
        else:
            msg = "타임스탬프 및 pHash 시퀀스 정상"
        return is_phash_replay, msg, tactic_name
    else:
        tactic_name = "시공간 광학 흐름 연속성 검증"
        if is_phash_replay or is_lk_anomaly:
            msg = f"Lucas-Kanade 변위 궤적 단절 감지 (이동량 {lk_movement:.2f}px → 정지/점프 스푸핑 차단)"
            return True, msg, tactic_name
        else:
            msg = f"Lucas-Kanade 변위 벡터 연속성 확인 (이동량 {lk_movement:.2f}px 정상 시공간 궤적)"
            return False, msg, tactic_name


def verify_blinding_attack(image: np.ndarray) -> tuple[bool, str, str, np.ndarray]:
    global zero_trust_radar_active
    tactic_choice = random.choice(["ZERO_TRUST", "GAMMA_GATING"])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # [1단계: 화이트아웃 수치 정량화] 화면 내 과포화 백색 픽셀(>=160) 비율 산출
    white_area_ratio = np.mean(gray >= 160)
    # [2단계: 영상 선명도 검증] 라플라시안 필터로 화면 흐림 정도를 측정하여, 인위적인 초점 블러링 강도 산출
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    # [3단계: 센서 실명 판정 기준 규정]
    # 백색 과포화 영역이 40% 이상이거나, 선명도가 80 미만(심한 블러링)일 경우 광학 센서 마비로 규정
    is_blind = (white_area_ratio >= 0.40 or lap_var < 80)

    restored_img = image.copy()

    if tactic_choice == "ZERO_TRUST":
        tactic_name = "다중 센서 교차 검증"
        if is_blind:
            # [4단계: 하드웨어 이중화 페일오버(Fail-over)]
            # 비전 센서 신뢰도를 제로(Zero-Trust)로 강등하고, 비광학 채널인 레이더 이중화 감시 체계로 즉각 전환
            zero_trust_radar_active = True
            msg = "광학 방해 감지: 비전 센서 의존도 저하 규정 → Zero-Trust 다중 센서 레이더 교차검증 즉각 전환"
        else:
            zero_trust_radar_active = False
            msg = "비전 센서 시야 명확 (레이더 연동 대기)"
    else:
        tactic_name = "적응형 감마 클리핑 및 편광 필터링"
        zero_trust_radar_active = False
        if is_blind:
            try:
                # [1단계: 빛과 색상 분리] 빛 방해만 따로 골라내서 정화하기 위해, 원본 밝기 채널이 분리된 LAB 색공간으로 변환
                lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                # [2단계: 실루엣 복원 시도] 극단적 빛 방해 속에서도 타깃 실루엣 대조비를 끌어올려 형태 복원 (타일 크기 8x8)
                clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
                cl = clahe.apply(l)
                # [3단계: 눈부심 억제 필터 적용]
                # 과포화 백색 펄스의 강한 밝기만 골라내어 비선형적으로 낮추는 보정 곡선 적용(감마 0.6) 매핑 테이블 생성
                gamma = 0.6
                invGamma = 1.0 / gamma
                table = np.array([((i / 255.0) ** invGamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
                cl_gated = cv2.LUT(cl, table)  # 생성한 고속 매핑 테이블을 적용하여 광학 마비 요소 강제 정화
                # [4단계: 화면 재조합 및 복원] 정화된 밝기 채널을 기존 색상과 다시 병합 후 정상 화면(RGB)으로 복원 => AI 타깃 식별 기능 가용성 유지
                restored_lab = cv2.merge((cl_gated, a, b))
                restored_img = cv2.cvtColor(restored_lab, cv2.COLOR_LAB2BGR)
            except Exception:
                pass
            msg = "과포화 백색 펄스 감쇄 및 CLAHE 휘도 균일화 가동 (눈부심 속 센서 실명 차단 → 영상 대조비 및 제어권 복원)"
        else:
            msg = "광학 동적 레인지 정상 (클리핑 임계값 미만)"

    return is_blind, msg, tactic_name, restored_img


def query_llm_noise_defense(cyb_attack: str, noise_std: float) -> tuple[str, int]:
    prompt = f"""당신은 AI 사이버 방어 지휘관입니다. 현재 {cyb_attack} 공격이 감지되었습니다. 
해당 프레임의 고주파 노이즈 표준편차는 {noise_std:.2f}입니다.
적대적 섭동 및 스텔스 노이즈를 제거하기 위한 최적의 디노이징 필터 강도(5~15)와 방어 전술명을 JSON으로 반환하세요.
예시: {{"tactic_name": "LLM 능동 방어: 적응형 비국소 평균(Non-Local Means) & 양방향 평활화 필터 가동", "filter_strength": 10}}"""

    try:
        url = f"{OLLAMA_URL}/api/generate"
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": 120,
                "temperature": 0.2
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            if resp.status == 200:
                text = json.loads(resp.read().decode('utf-8')).get("response", "").strip()
                match = re.search(r'\{.*\}', text, re.DOTALL)
                data = json.loads(match.group(0)) if match else json.loads(text)
                t_name = data.get("tactic_name", "LLM 능동 방어: 적응형 비국소 평균(Non-Local Means) 필터 정화")
                f_str = int(data.get("filter_strength", 10))
                return t_name, f_str
    except Exception:
        pass

    tactic_name = random.choice([
        "LLM 적응형 디노이징 (LLM Adaptive Denoising)",
        "윤곽선 무결성 보강 (Bilateral Edge-Preserving)"
    ])
    strength = 14 if "ADVERSARIAL" in cyb_attack else 8
    return tactic_name, strength


adaptive_denoise_count = 0


def denoise_preprocessing(image: np.ndarray, cyb_attack: str = "NONE") -> tuple[np.ndarray, str, bool, str]:
    global adaptive_denoise_count
    if "NOISE" in cyb_attack:
        adaptive_denoise_count += 1
        gray_before = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        noise_before = float(cv2.Laplacian(gray_before, cv2.CV_64F).std())
        tactic_name, strength = query_llm_noise_defense(cyb_attack, noise_before)

        if "ADVERSARIAL" in cyb_attack:
            tactic_display = "LLM 적응형 디노이징"
            clean = cv2.fastNlMeansDenoisingColored(image, None, float(strength), float(strength), 3, 7)
            noise_after = float(cv2.Laplacian(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY), cv2.CV_64F).std())

            prob = min(0.85, 0.40 + 0.15 * (adaptive_denoise_count - 1))
            is_success = random.random() <= prob

            if is_success:
                msg = f"방어전술 : [{tactic_display}] | 방어 성공 (노이즈 편차 {noise_before:.1f} → {noise_after:.1f} 감쇄, 방어율 {prob*100:.0f}%) → 적대적 노이즈 박멸 완료"
                return clean, msg, True, tactic_display
            else:
                msg = f"방어전술 : [{tactic_display}] | 방어 실패 (노이즈 편차 {noise_before:.1f} → {noise_after:.1f} 감쇄, 방어율 {prob*100:.0f}% 한계 돌파 허용)"
                return clean, msg, False, tactic_display
        else:
            tactic_display = "윤곽선 무결성 보존"
            clean = cv2.bilateralFilter(image, 9, 75, 75)
            noise_after = float(cv2.Laplacian(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY), cv2.CV_64F).std())

            prob = 0.60
            is_success = random.random() <= prob

            if is_success:
                msg = f"방어전술 : [{tactic_display}] | 방어 성공 (바이래터럴 필터 정화 완료, 차단율 60%) → 미세 스텔스 노이즈 차단"
                return clean, msg, True, tactic_display
            else:
                msg = f"방어전술 : [{tactic_display}] | 방어 실패 (관통 확률 40%로 스텔스 노이즈 우회 침투 허용)"
                return image, msg, False, tactic_display

    med = cv2.medianBlur(image, 3)
    clean = cv2.GaussianBlur(med, (5, 5), 0)
    return clean, "", True, "LLM 적응형 디노이징"


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'image' not in request.files:
        return jsonify({"status": "SLA_OK", "error": "NO_PAYLOAD"}), 200

    file = request.files['image']
    source_img_name = request.form.get("source_image", "UNKNOWN")
    attack_type     = request.form.get("attack_type", "NONE")
    phys_attack     = request.form.get("physical_attack", "NONE")
    phys_asset      = request.form.get("physical_asset", "NONE")
    cyb1            = request.form.get("cyber_attack_1", "NONE")
    cyb2            = request.form.get("cyber_attack_2", "NONE")
    sensor_dmg      = float(request.form.get("sensor_damage_level", 0.0))
    sync_loss       = int(request.form.get("sync_loss_pct", 0))
    avail_loss      = int(request.form.get("avail_loss_pct", request.form.get("bandwidth_loss_pct", 0)))
    client_ts       = request.form.get("client_timestamp", "0.0")
    req_round       = int(request.form.get("round_num", global_sim_state["globalRound"]))
    req_budget      = float(request.form.get("current_budget", global_sim_state["budget"]))

    if global_sim_state["globalRound"] == 1 and req_round > 1:
        return jsonify({"status": "RESET_DETECTED", "globalRound": global_sim_state["globalRound"]}), 200
    if req_round == 1 and global_sim_state["globalRound"] > 1:
        global score_tracker
        score_tracker = ScoreTracker()
        global_sim_state["historyLogs"] = []

    img_bytes = file.read()
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    image = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    if image is None:
        return jsonify({"status": "SLA_OK", "message": "PAYLOAD_CORRUPT"}), 200

    detected_anomalies = []
    active_defense_asset = "NONE"
    physical_defense_success = True
    platform_destroyed = False
    munition_intercepted = True

    processed_image = image.copy()
    noise_attack_type = cyb1 if "NOISE" in cyb1 else (cyb2 if "NOISE" in cyb2 else "NONE")

    noise_tactic = "LLM 적응형 디노이징 (LLM Adaptive Denoising)"
    if "NOISE" in noise_attack_type:
        processed_image, noise_defense_msg, noise_success, noise_tactic = denoise_preprocessing(processed_image, noise_attack_type)
        if noise_defense_msg:
            print(f"\n  {noise_defense_msg}", flush=True)
            if noise_success:
                detected_anomalies.append("적대적_노이즈_정화_완료")

    decision = "SAFE"
    prob_dict = {"UGV": 0.0, "UAV": 0.0, "Rocket": 0.0, "UAV_Clutter": 1.0}
    
    global zero_trust_radar_active
    if zero_trust_radar_active:
        print("\n  [레이더 교차 검증 활성화] 비전 센서 무력화 우회 -> 레이더 단면적(RCS) 기반 위협 식별", flush=True)
        if phys_asset == "UGV":
            prob_dict = {"UGV": 0.98, "UAV": 0.0, "Rocket": 0.0, "UAV_Clutter": 0.02}
        elif phys_asset == "UAV":
            prob_dict = {"UGV": 0.0, "UAV": 0.98, "Rocket": 0.0, "UAV_Clutter": 0.02}
        else:
            prob_dict = {"UGV": 0.0, "UAV": 0.0, "Rocket": 0.0, "UAV_Clutter": 0.98}
            
        if tactical_engine:
            main_conf = max(prob_dict["UGV"], prob_dict["UAV"], prob_dict["Rocket"])
            etc_conf = prob_dict["UAV_Clutter"]
            res_bytes = tactical_engine.evaluate_threat(ctypes.c_float(main_conf), ctypes.c_float(etc_conf))
            decision = res_bytes.decode('utf-8')

    elif ort_session:
        rgb_img = cv2.cvtColor(processed_image, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb_img)
        w, h = pil_img.size
        max_dim = max(w, h)
        canvas = Image.new('RGB', (max_dim, max_dim), (0, 0, 0))
        canvas.paste(pil_img, ((max_dim - w) // 2, (max_dim - h) // 2))
        resized = canvas.resize((224, 224))

        tensor = np.array(resized).astype(np.float32) / 255.0
        tensor = (tensor - MEAN) / STD
        tensor = tensor.transpose(2, 0, 1)[np.newaxis, ...]

        input_name = ort_session.get_inputs()[0].name
        outputs = ort_session.run(None, {input_name: tensor.astype(np.float32)})
        probs = outputs[0][0]
        prob_dict = {"UGV": float(probs[0]), "UAV": float(probs[1]), "Rocket": float(probs[2]), "UAV_Clutter": float(probs[3])}

        if tactical_engine:
            main_conf = max(prob_dict["UGV"], prob_dict["UAV"], prob_dict["Rocket"])
            etc_conf = prob_dict["UAV_Clutter"]
            res_bytes = tactical_engine.evaluate_threat(ctypes.c_float(main_conf), ctypes.c_float(etc_conf))
            decision = res_bytes.decode('utf-8')
    else:
        decision = "ONNX_OFFLINE"

    if phys_attack in ["MISSILE_SURGICAL_STRIKE", "DRONE_SWARM"]:
        platform_destroyed, munition_intercepted, intercept_msg = evaluate_physical_intercept(phys_attack, phys_asset, sensor_dmg, decision, prob_dict)
        physical_defense_success = munition_intercepted
        active_defense_asset = "Interceptor_Missile.png" if phys_attack == "MISSILE_SURGICAL_STRIKE" else "Vulcan_Cannon.png"

        print(f"\n  [★ 교전 전술 판정 로그] 물리 공격 감지 ({phys_asset} -> {phys_attack})")
        print(f"   └─> {intercept_msg}", flush=True)

        if physical_defense_success:
            detected_anomalies.append(f"탄두_요격_성공({intercept_msg[:25]})")
        else:
            if phys_attack == "MISSILE_SURGICAL_STRIKE":
                avail_loss = min(100, avail_loss + 20)
            elif phys_attack == "DRONE_SWARM":
                avail_loss = min(100, avail_loss + 10)

        if platform_destroyed:
            detected_anomalies.append("적_플랫폼_파괴")

    replay_tactic = "동적 지각 해시 검증"
    if any(k in cyb1 for k in ["DYNAMIC_REPLAY", "SPOOFING", "REPLAY", "스푸핑", "SPOOF"]) or any(k in cyb2 for k in ["DYNAMIC_REPLAY", "SPOOFING", "REPLAY", "스푸핑", "SPOOF"]):
        is_replay, replay_msg, replay_tactic = verify_replay_attack(processed_image, client_ts)
        print(f"\n  방어전술 : [{replay_tactic}] -> {replay_msg}", flush=True)
        if is_replay:
            detected_anomalies.append("동적_리플레이_스푸핑_감지")

    blind_tactic = "다중 센서 교차 검증"
    if any(k in cyb1 for k in ["PULSED_BLINDING", "BLURRING"]) or any(k in cyb2 for k in ["PULSED_BLINDING", "BLURRING"]):
        is_blind, blind_msg, blind_tactic, restored_img = verify_blinding_attack(processed_image)
        if blind_tactic == "적응형 감마 클리핑 및 편광 필터링" and is_blind:
            processed_image = restored_img
        print(f"\n  방어전술 : [{blind_tactic}] -> {blind_msg}", flush=True)
        if is_blind:
            detected_anomalies.append("화이트아웃_블러링_감지")

    if not physical_defense_success:
        decision = "SYSTEM_BREACHED_DANGER"

    if phys_attack != "NONE":
        def_success = munition_intercepted
    else:
        def_success = (len(detected_anomalies) > 0)

    score_tracker.evaluate_triad_round(
        attack_type,
        {"defense_success": def_success},
        int(round(sensor_dmg * 100)), sync_loss, avail_loss
    )

    # 방어 실패 시 사이버 공격 피해를 즉시 반영 (한 턴 지연 방지)
    if not def_success and phys_attack == "NONE":
        if "ADVERSARIAL_NOISE" in cyb1:
            sensor_dmg = min(1.0, sensor_dmg + 0.30)
            score_tracker.integrity_loss_pct = int(round(sensor_dmg * 100))
        elif any(k in cyb1 for k in ["STEALTH_NOISE", "NOISE"]):
            sensor_dmg = min(1.0, sensor_dmg + 0.20)
            score_tracker.integrity_loss_pct = int(round(sensor_dmg * 100))
        if any(k in cyb1 for k in ["DYNAMIC_REPLAY", "SPOOFING", "REPLAY", "스푸핑", "SPOOF"]):
            sync_loss = min(100, sync_loss + 25)
            score_tracker.sync_loss_pct = sync_loss
        if any(k in cyb1 for k in ["PULSED_BLINDING", "BLURRING"]):
            avail_loss = min(100, avail_loss + 5)
            score_tracker.avail_loss_pct = avail_loss
            score_tracker.availability = max(0.0, 100.0 - avail_loss)

    print(f" [Defense] 무결성손상: {score_tracker.integrity_loss_pct}% | 동기화왜곡: {score_tracker.sync_loss_pct}% | 가용성손실: {score_tracker.avail_loss_pct}%", flush=True)

    def_name = "AI 사이버 방어 쉴드"
    if phys_attack == "MISSILE_SURGICAL_STRIKE": def_name = "요격 미사일"
    elif phys_attack == "DRONE_SWARM": def_name = "발칸포"
    elif "NOISE" in noise_attack_type: def_name = noise_tactic
    elif any(k in cyb1 for k in ["DYNAMIC_REPLAY", "SPOOFING", "REPLAY", "스푸핑", "SPOOF"]): def_name = replay_tactic
    elif any(k in cyb1 for k in ["PULSED_BLINDING", "BLURRING"]): def_name = blind_tactic

    global_sim_state["globalRound"] = req_round + 1
    global_sim_state["attackScore"] = score_tracker.attack_score
    global_sim_state["defenseScore"] = score_tracker.defense_score
    global_sim_state["availLoss"] = score_tracker.avail_loss_pct
    global_sim_state["syncLoss"] = score_tracker.sync_loss_pct
    global_sim_state["integLoss"] = score_tracker.integrity_loss_pct
    global_sim_state["budget"] = req_budget
    global_sim_state["spentCost"] = round(15.0 - req_budget, 2)
    raw_att = phys_attack if phys_attack != "NONE" else (cyb1 if cyb1 != "NONE" else attack_type)
    att_display_map = {
        "MISSILE_SURGICAL_STRIKE": "UGV 미사일 타격",
        "DRONE_SWARM": "자폭 드론 군집",
        "STEALTH_NOISE": "스텔스 노이즈",
        "ADVERSARIAL_NOISE": "적대적 노이즈",
        "SPOOFING": "동적 리플레이 스푸핑",
        "DYNAMIC_REPLAY": "동적 리플레이 스푸핑",
        "BLURRING": "화이트아웃 주입 블러링",
        "PULSED_BLINDING": "화이트아웃 주입 블러링",
        "STANDBY": "대기 중"
    }
    global_sim_state["attackType"] = att_display_map.get(raw_att, raw_att)
    global_sim_state["defenseName"] = def_name
    global_sim_state["defenseSuccess"] = def_success
    if phys_attack == "MISSILE_SURGICAL_STRIKE":
        ugv_line = "UGV 명중 성공" if platform_destroyed else "UGV 명중 실패"
        msl_line = "미사일 요격 성공" if munition_intercepted else "미사일 요격 실패"
        global_sim_state["outcomeStatus"] = f"{ugv_line}<br>{msl_line}"
    else:
        global_sim_state["outcomeStatus"] = "방어 성공" if def_success else "방어 실패"
    completed_r = global_sim_state['globalRound'] - 1
    tot_sc = (score_tracker.defense_score + score_tracker.attack_score) * (max(0, 100 - score_tracker.avail_loss_pct) / 100.0)
    global_sim_state["historyLogs"].append({
        "round": completed_r,
        "attack": global_sim_state["attackType"],
        "defense": def_name,
        "win": "방어" if def_success else "공격",
        "aPoint": round(score_tracker.attack_score, 1),
        "dPoint": round(score_tracker.defense_score, 1),
        "tPoint": round(tot_sc, 1)
    })

    if completed_r % 3 == 0:
        att_wins = sum(1 for log in global_sim_state["historyLogs"][-3:] if log.get("win") == "공격")
        if att_wins < 2:
            global_sim_state["notice"] = f"{completed_r} Round ( Attack_Agent 다른 공격 패턴 구축 중 ... )"
        else:
            global_sim_state["notice"] = f"{completed_r} Round ( Attack_Agent 현재 공격 패턴 유지 )"
    else:
        global_sim_state["notice"] = f"{completed_r} Round"

    avail_pct = max(0, 100 - global_sim_state["availLoss"])
    win_req = round(1000.0 * (avail_pct / 100.0), 1)
    global_sim_state["winRequirement"] = win_req

    if global_sim_state["availLoss"] >= 100 or global_sim_state["syncLoss"] >= 100 or global_sim_state["integLoss"] >= 100:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "ATTACK"
        if global_sim_state["availLoss"] >= 100:
            global_sim_state["winReason"] = "가용성(Availability) 100% 붕괴로 시스템 마비"
        elif global_sim_state["syncLoss"] >= 100:
            global_sim_state["winReason"] = "동기화(Synchronization) 100% 붕괴로 데이터 불일치"
        else:
            global_sim_state["winReason"] = "무결성(Integrity) 100% 붕괴로 보안 체계 파괴"
    elif global_sim_state["attackScore"] >= win_req:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "ATTACK"
        global_sim_state["winReason"] = f"공격측 승리 조건({int(win_req)}점) 도달 (가용성 저하로 승리 기준 감소)"
    elif global_sim_state["defenseScore"] >= win_req:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "DEFENSE"
        global_sim_state["winReason"] = f"방어측 승리 조건({int(win_req)}점) 도달 (가용성 저하로 승리 기준 감소)"
    elif global_sim_state["budget"] < 0.05:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "DEFENSE"
        global_sim_state["winReason"] = "공격측 잔여 예산 완전 소진"


    return jsonify({
        "status": "SLA_OK",
        "globalRound": global_sim_state["globalRound"],
        "anomalies_detected": detected_anomalies,
        "tactical_decision": decision,
        "active_defense_asset": active_defense_asset,
        "physical_defense_success": physical_defense_success,
        "platform_destroyed": platform_destroyed,
        "munition_intercepted": munition_intercepted,
        "defense_success": def_success,
        "attack_score": score_tracker.attack_score,
        "defense_score": score_tracker.defense_score,
        "availability": score_tracker.availability
    }), 200


@app.route('/api/state', methods=['GET'])
def get_sim_state():
    return jsonify(global_sim_state), 200


@app.route('/api/notice', methods=['POST'])
def update_notice():
    data = request.json or {}
    global_sim_state["notice"] = data.get("notice", global_sim_state.get("notice", ""))
    return jsonify({"status": "OK"}), 200


@app.route('/api/reset', methods=['POST'])
def reset_state():
    global global_sim_state, score_tracker, adaptive_denoise_count
    score_tracker = ScoreTracker()
    adaptive_denoise_count = 0
    global_sim_state = {
        "globalRound": 1,
        "budget": 15.0,
        "spentCost": 0.0,
        "attackScore": 0.0,
        "defenseScore": 0.0,
        "availLoss": 0,
        "syncLoss": 0,
        "integLoss": 0,
        "attackType": "대기 중",
        "defenseName": "대기 중",
        "defenseSuccess": True,
        "outcomeStatus": "대기 중",
        "notice": "1 Round ( LLM 최초 공격 패턴 구축 중 ... )",
        "historyLogs": [],
        "gameOver": False,
        "winner": "",
        "winReason": "",
        "winRequirement": 1000,
        "isPaused": False
    }
    print("\n [★ 지휘 관제 리셋] 대시보드 명령으로 교전 상태 및 점수가 1라운드로 리셋되었습니다.\n", flush=True)
    return jsonify({"status": "RESET_OK"}), 200

@app.route('/api/pause', methods=['POST'])
def pause_state():
    global_sim_state["isPaused"] = True
    print("\n [★ 지휘 관제] 대시보드 명령으로 시뮬레이션이 일시정지(PAUSE) 되었습니다.\n", flush=True)
    return jsonify({"status": "PAUSED"}), 200

@app.route('/api/resume', methods=['POST'])
def resume_state():
    global_sim_state["isPaused"] = False
    print("\n [★ 지휘 관제] 대시보드 명령으로 시뮬레이션이 재개(RESUME) 되었습니다.\n", flush=True)
    return jsonify({"status": "RESUMED"}), 200


@app.route('/print_scoreboard', methods=['POST'])
def print_scoreboard():
    data = request.json or {}
    def_sc = data.get("defense_score", 0.0)
    att_sc = data.get("attack_score", 0.0)
    avail  = data.get("availability", 100.0)

    global_sim_state["attackScore"] = att_sc
    global_sim_state["defenseScore"] = def_sc
    global_sim_state["availLoss"] = round(100.0 - avail, 1)
    if "sync_loss" in data:
        global_sim_state["syncLoss"] = data["sync_loss"]
    if "integrity_loss" in data:
        global_sim_state["integLoss"] = data["integrity_loss"]

    if "budget" in data:
        global_sim_state["budget"] = data["budget"]
        global_sim_state["spentCost"] = data.get("spent_cost", round(15.0 - data["budget"], 2))

    win_req = round(1000.0 * (avail / 100.0), 1)
    global_sim_state["winRequirement"] = win_req

    if global_sim_state["budget"] < 2.0:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "DEFENSE"
        global_sim_state["winReason"] = "공격측 잔여 예산 완전 소진"
    elif att_sc >= win_req:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "ATTACK"
        global_sim_state["winReason"] = f"공격측 승리 조건({int(win_req)}점) 도달! (Attack Victory)"
    elif def_sc >= win_req:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "DEFENSE"
        global_sim_state["winReason"] = f"방어측 승리 조건({int(win_req)}점) 도달! (Defense Victory)"
    elif avail <= 0:
        global_sim_state["gameOver"] = True
        global_sim_state["winner"] = "ATTACK"
        global_sim_state["winReason"] = "SLA 가용성 0% 붕괴로 시스템 마비"

    tot_sc = (def_sc + att_sc) * (avail / 100.0)
    print(f" [Defense 점수] Defense Score : {def_sc:.1f} pt\n"
          f" [전술 점수판] Total Score : {tot_sc:.1f} pt (가용성: {avail:.0f}%, 승리조건: {win_req:.0f} pt)", flush=True)
    return jsonify({"status": "OK"}), 200


if __name__ == '__main__':
    print("[방어 에이전트] 가동 완료 (물리 대응 & 사이버 내성 연동 엔진)", flush=True)
    app.run(host='0.0.0.0', port=5000)
