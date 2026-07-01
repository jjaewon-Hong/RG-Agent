# 🛡️ DAH-2026 국방 자율 무기체계 사이버-물리 공방 시뮬레이션 시스템
**(Autonomous Hybrid Cyber-Physical Warfare Simulation System)**

본 프로젝트는 국방 자율 무기체계(UGV/UAV)를 대상으로 한 **최첨단 사이버 교란 공격(Cognitive & Sensor Warfare)**과 이를 실시간으로 식별 및 차단하는 **능동형 심층 방어 체계(Deep Active Defense System)**를 검증하기 위한 통합 공방 시뮬레이션 플랫폼입니다.

---

## 🏗️ 시스템 아키텍처 및 구성 요소

```
 [ Dashboard (UI) ] <---> [ Defense Agent ] <---> [ Target Environment ] <---> [ Attack Agent ]
 (HTML5/Vanilla JS)     (Flask/OpenCV/C++/ONNX)     (Nginx Image Server)       (Python/Ollama LLM)
```

1. **`attack_agent/` (공격 에이전트)**
   - **역할:** LLM 지휘관(`Ollama/Llama3`) 기반 3단계 Kill-Chain 교범(탐색 → 타격 → 마비) 전술 자율 수립.
   - **기능:** 영상 오염 기법(적대적 노이즈, 스푸핑, 블러링 등) 주입 및 물리 타격(미사일/드론 군집) 시도.
2. **`defense_agent/` (방어 에이전트)**
   - **역할:** 매 턴 유입되는 공격 패킷 및 프레임을 100% 실질 컴퓨터 비전 연산과 C++/ONNX 추론 엔진으로 분석.
   - **기능:** 동적 지각 해시(pHash), 광학 흐름(Optical Flow), CLAHE/감마 평활화 영상 복원, LLM 적응형 디노이징 수행.
3. **`target_env/` & `image_set/` (표적 환경)**
   - **역할:** 정찰 및 타격 대상이 되는 실제 무기체계 센서 영상 풀 제공 (Nginx 웹 서버).
4. **`dashboard/` (통합 지휘 관제 대시보드)**
   - **역할:** 실시간 교전 상황(공방 전술, SLA 가용성, 예산, 콤보 이력)을 렌더링하는 HUD 인터페이스.

---

## 📦 시스템 의존성 (Dependencies)

### 1. 호스트 필수 소프트웨어
- **Docker & Docker Compose:** 전체 마이크로서비스 컨테이너 오케스트레이션
- **Ollama (Local LLM Engine):** 로컬 AI 지휘관 추론 엔진 (포트 `11434` 구동)

### 2. 컨테이너 파이썬 주요 라이브러리 (`requirements.txt`)
- **Core Vision & ML:** `opencv-python-headless`, `numpy`, `onnxruntime`
- **Network & API:** `requests`, `flask`, `flask-cors`

---

## ⚙️ 환경 변수 (Environment Variables)

`docker-compose.yml` 내에서 각 마이크로서비스에 주입되는 핵심 설정 변수입니다.

| 서비스 명 | 환경 변수 | 기본값 | 설명 |
| :--- | :--- | :--- | :--- |
| **`attack_agent`** | `TARGET_HOST` | `target_env` | 표적 영상 제공 서버 호스트명 |
| | `OLLAMA_URL` | `http://host.docker.internal:11434` | 호스트 머신의 Ollama LLM API 주소 |
| | `OLLAMA_MODEL` | `llama3` | 작전 수립에 사용할 LLM 모델명 |
| | `ATTACK_INTERVAL` | `5` | 공격 주기의 기본 인터벌(초) |
| **`defense_agent`** | `TARGET_HOST` | `target_env` | 표적 영상 제공 서버 호스트명 |
| | `OLLAMA_URL` | `http://host.docker.internal:11434` | 호스트 머신의 Ollama LLM API 주소 |
| | `OLLAMA_MODEL` | `llama3` | 노이즈 분석 및 적응형 방어 질의 모델명 |

---

## 🚀 빠른 실행 방법 (Quick Start Guide)

### 1단계: 로컬 LLM (Ollama) 준비
호스트 PC에서 Ollama를 실행하고 `llama3` 모델을 다운로드합니다.
```bash
ollama run llama3
```

### 2단계: Docker 빌드 및 컨테이너 실행
프로젝트 루트 디렉토리(`c:\Users\lg\Desktop\RG-Agent`)에서 Docker Compose를 실행합니다.
```bash
docker-compose up --build -d
```
정상 실행 시 다음 3개의 컨테이너가 가동됩니다:
- `dah_target_env` (Port 8080)
- `dah_defense_agent` (Port 5000)
- `dah_attack_agent` (Background Process)

### 3단계: 지휘 관제 대시보드 접속
`dashboard/index.html` 파일을 크롬 등 웹 브라우저로 직접 열거나, 로컬 라이브 모드로 설정하여 실시간 AI 교전 현황을 모니터링합니다.

---

## 🏆 핵심 기술 및 밸런스 패치 특징

1. **100% 실질 비전 연산 방어 체계**
   - **노이즈 정화:** OpenCV Non-Local Means 정화 전후의 라플라시안 고주파 편차 감소 여부를 물리 검증.
   - **리플레이 스푸핑:** 15프레임 버퍼 간 64-bit pHash 해밍 거리(10bit 이하) 및 Lucas-Kanade 광학 흐름 변위 벡터 계산.
   - **화이트아웃 블러링:** 과포화 백색 눈부심 감지 시 LUT 기반 감마 클리핑(γ=0.6) 및 CLAHE 히스토그램 평활화 영상 복원.
2. **정교한 게임 이론적 경제 밸런스**
   - 물리 공격 성공 시 가용성 영구 손상(미사일 20%, 드론군집 10%)을 통해 공격측 메리트를 보장하되, 예산 소모와 1턴 쿨타임을 부여해 치밀한 자원 분배 공방 구도 구현.
3. **실시간 쾌속 시연을 위한 LLM 골든 밸런스**
   - 공격 에이전트(15초 타임아웃 / 350토큰 제한)와 방어 에이전트(5초 타임아웃 / 120토큰 제한)를 통해 2분씩 멈추는 병목 현상을 완벽 해결하고 민첩한 판단 속도 확보.
