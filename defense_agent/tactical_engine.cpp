#include <deque>
#include <numeric>
#include <string>

std::deque<float> threat_history;
const int WINDOW_SIZE = 5;

std::string current_state = "SAFE";

extern "C" {
    const char* evaluate_threat(float main_conf, float etc_conf) {
        threat_history.push_back(main_conf);
        if (threat_history.size() > WINDOW_SIZE) {
            threat_history.pop_front();
        }

        float sum = 0.0f;
        for (float val : threat_history) {
            sum += val;
        }
        float moving_avg = sum / threat_history.size();

        float margin = main_conf - etc_conf;

        if (threat_history.size() < WINDOW_SIZE) {
            if (moving_avg > 0.6f) return "CAUTION";
            return "SAFE";
        }

        if (margin < 0.20f) {
            current_state = (moving_avg > 0.5f) ? "CAUTION" : "SAFE";
            return current_state.c_str();
        }

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
