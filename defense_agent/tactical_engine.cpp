#include <deque>
#include <numeric>
#include <string>

// 시계열 데이터 저장을 위한 전역 슬라이딩 윈도우
std::deque<float> threat_history;
const int WINDOW_SIZE = 5;

// 상태 머신(FSM) 유지를 위한 전역 상태
std::string current_state = "SAFE";

extern "C" {
    // main_conf: THREAT(UGV/UAV/로켓) 중 최대 확률, etc_conf: Clutter(UAV_Clutter) 확률
    const char* evaluate_threat(float main_conf, float etc_conf) {
        // 1. 시계열 데이터 갱신 (Sliding Window)
        threat_history.push_back(main_conf);
        if (threat_history.size() > WINDOW_SIZE) {
            threat_history.pop_front();
        }

        // 2. 이동 평균(Moving Average) 계산을 통한 스파이크 노이즈 제거
        float sum = 0.0f;
        for (float val : threat_history) {
            sum += val;
        }
        float moving_avg = sum / threat_history.size();

        // 3. 모델 불확실성(Margin) 분석: 1위 위협과 비위협(UAV_Clutter)의 격차
        float margin = main_conf - etc_conf;
        
        // 데이터가 아직 충분히 쌓이지 않았다면 신중하게 접근 (최대 CAUTION)
        if (threat_history.size() < WINDOW_SIZE) {
            if (moving_avg > 0.6f) return "CAUTION";
            return "SAFE";
        }

        // 4. 상태 머신 (FSM) 및 전술 판정
        // [안전장치 1] 불확실성이 높을 때 (확률 격차가 20% 미만)
        // 극심한 물리/사이버 공격으로 영상이 훼손되어 AI가 억지로 찍은 상황.
        // 이때는 오인 사격(False Positive) 방지를 위해 무조건 CAUTION으로 강등.
        if (margin < 0.20f) {
            current_state = (moving_avg > 0.5f) ? "CAUTION" : "SAFE";
            return current_state.c_str();
        }

        // [안전장치 2] 마진이 확보된 상태에서 '이동 평균' 기반 상태 전이
        // 단 1프레임이 90%를 넘더라도, 최근 5프레임 평균이 80%를 넘어야만 DANGER 선언
        if (moving_avg >= 0.80f) {
            current_state = "DANGER";
        } else if (moving_avg >= 0.40f) {
            current_state = "CAUTION";
        } else {
            current_state = "SAFE";
        }

        return current_state.c_str();
    }
}
