# DAH-2026 국방 자율 무기체계 사이버-물리 공방 시뮬레이션 시스템

---

## ⚔️ 실행 방법

### 1. 로컬 LLM (Ollama) 준비
호스트 PC에서 Ollama를 실행하고 `llama3` 모델을 준비합니다.
```bash
ollama run llama3
```

### 2. 컨테이너 빌드 및 실행
프로젝트 루트 디렉토리에서 Docker Compose를 실행합니다.
```bash
docker-compose up --build -d
```
- **구동 서비스:** `target_env` (포트 8080), `defense_agent` (포트 5000), `attack_agent` (백그라운드)

### 3. 대시보드 모니터링
`dashboard/index.html` 파일을 웹 브라우저로 열어 실시간 AI 공방 시뮬레이션을 확인합니다.

---

## 🛡️ 의존성

### 호스트 필수 소프트웨어
- **Docker & Docker Compose** (전체 서비스 컨테이너 구동 및 오케스트레이션)
- **Ollama** (로컬 LLM 지휘관 추론 엔진, 포트 `11434` 사용)

### 컨테이너 및 라이브러리 (`requirements.txt`)
- **Vision & ML Engine:** `opencv-python-headless`, `numpy`, `onnxruntime`
- **Network & API Server:** `flask`, `flask-cors`, `requests`
- **C++ Tactical Engine:** `g++` (빌드 시 전술 엔진 `tactical_engine.so` 공유 라이브러리 컴파일)

---

## ⚙️ 환경변수

`docker-compose.yml`을 통해 각 서비스 컨테이너에 주입되는 환경변수 목록입니다.

| 서비스 명 | 환경변수 | 기본값 | 설명 |
| :--- | :--- | :--- | :--- |
| **`attack_agent`** | `TARGET_HOST` | `target_env` | 표적 영상 제공 서버 호스트명 |
| | `OLLAMA_URL` | `http://host.docker.internal:11434` | 호스트 머신의 Ollama LLM API 주소 |
| | `OLLAMA_MODEL` | `llama3` | 공방 전술 수립에 사용할 LLM 모델명 |
| | `ATTACK_INTERVAL` | `5` | 공격 주기의 기본 인터벌(초) |
| **`defense_agent`** | `TARGET_HOST` | `target_env` | 표적 영상 제공 서버 호스트명 |
| | `OLLAMA_URL` | `http://host.docker.internal:11434` | 호스트 머신의 Ollama LLM API 주소 |
| | `OLLAMA_MODEL` | `llama3` | 적응형 방어 전략 수립에 사용할 LLM 모델명 |

