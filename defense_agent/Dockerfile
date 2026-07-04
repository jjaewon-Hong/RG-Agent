FROM python:3.10-slim

# C++ 컴파일을 위한 g++ 설치
RUN apt-get update && apt-get install -y g++ libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 파이썬 패키지 설치
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 모델, 엔진 소스코드, 파이썬 스크립트 복사
COPY reasoning_guard_engine.onnx ./
COPY reasoning_guard_engine.onnx.data ./
COPY tactical_engine.cpp ./
COPY agent.py scorer.py ./

# C++ 전술 엔진 컴파일 (.so 공유 라이브러리 생성)
RUN g++ -shared -fPIC -o tactical_engine.so tactical_engine.cpp

EXPOSE 5000

CMD ["python", "agent.py"]
