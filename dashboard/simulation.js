const COSTS = {
  MISSILE_SURGICAL_STRIKE: 3.0,
  DRONE_SWARM: 2.0,
  STEALTH_NOISE: 0.05,
  ADVERSARIAL_NOISE: 0.10,
  DYNAMIC_REPLAY: 0.25,
  SPOOFING: 0.25,
  PULSED_BLINDING: 0.50,
  BLURRING: 0.50
};

let state = {
  isRunning: false,
  intervalId: null,
  speedMs: 1500,
  globalRound: 1,
  budget: 20.0,
  spentCost: 0.0,
  attackScore: 0.0,
  defenseScore: 0.0,
  availLoss: 0,
  syncLoss: 0,
  integLoss: 0,
  ugvCooldown: 0,
  uavCooldown: 0,
  adaptiveDenoiseCount: 0
};

const el = {
  btnStart: document.getElementById("btn-start"),
  btnReset: document.getElementById("btn-reset"),
  simSpeed: document.getElementById("sim-speed"),
  simMode: document.getElementById("sim-mode"),

  totalScoreBox: document.getElementById("total-score-box"),
  attackScoreVal: document.getElementById("attack-score-val"),
  defenseScoreVal: document.getElementById("defense-score-val"),
  victoryReqVal: document.getElementById("victory-req-val"),

  meterAvail: document.getElementById("meter-avail"),
  meterSync: document.getElementById("meter-sync"),
  meterInteg: document.getElementById("meter-integ"),
  meterBudget: document.getElementById("meter-budget"),

  attackTitle: document.getElementById("attack-header-title"),
  attackMainImg: document.getElementById("attack-main-img"),

  defenseTitle: document.getElementById("defense-header-title"),
  defenseMainImg: document.getElementById("defense-main-img"),

  r1Title: document.getElementById("r1-title"),
  r2Title: document.getElementById("r2-title"),
  r3Title: document.getElementById("r3-title"),
  r1Img: document.getElementById("r1-img"),
  r2Img: document.getElementById("r2-img"),
  r3Img: document.getElementById("r3-img"),

  outcomeAttack: document.getElementById("outcome-attack"),
  outcomeStatus: document.getElementById("outcome-status"),
  noticeBanner: document.getElementById("tactical-notice-banner"),
  historyTbody: document.getElementById("history-tbody"),

  modalOverlay: document.getElementById("modal-overlay"),
  modalTitle: document.getElementById("modal-title"),
  modalDesc: document.getElementById("modal-desc"),
  modalIcon: document.getElementById("modal-icon"),
  btnRestart: document.getElementById("btn-restart")
};

el.btnStart.addEventListener("click", () => {
  if (state.isRunning) pauseSim();
  else startSim();
});

el.btnReset.addEventListener("click", resetSim);
el.btnRestart.addEventListener("click", () => {
  el.modalOverlay.classList.remove("active");
  resetSim();
  startSim();
});

if (el.simMode) {
  const updateSpeedUI = () => {
    if (el.simMode.value === "docker") {
      el.simSpeed.disabled = true;
      el.simSpeed.style.opacity = "0.4";
      el.simSpeed.title = "Ollama Live 모드에서는 실제 LLM 추론 속도(10~30초)로 진행됩니다.";
    } else {
      el.simSpeed.disabled = false;
      el.simSpeed.style.opacity = "1";
      el.simSpeed.title = "";
    }
  };
  updateSpeedUI();
  el.simMode.addEventListener("change", () => {
    updateSpeedUI();
    if (state.isRunning) {
      pauseSim();
      startSim();
    }
  });
}

el.simSpeed.addEventListener("change", (e) => {
  state.speedMs = parseInt(e.target.value, 10);
  if (state.isRunning && (!el.simMode || el.simMode.value === "demo")) {
    clearInterval(state.intervalId);
    state.intervalId = setInterval(stepSim, state.speedMs);
  }
});

let lastPolledRound = -1;

async function pollDockerBackend() {
  try {
    let res = await fetch("http://localhost:5000/api/state");
    if (!res.ok) return;
    let data = await res.json();

    state.globalRound = data.globalRound || 1;
    state.budget = data.budget !== undefined ? data.budget : 20.0;
    state.spentCost = data.spentCost || 0.0;
    state.attackScore = data.attackScore !== undefined ? data.attackScore : 0.0;
    state.defenseScore = data.defenseScore !== undefined ? data.defenseScore : 0.0;
    state.availLoss = data.availLoss || 0;
    state.syncLoss = data.syncLoss || 0;
    state.integLoss = data.integLoss || 0;

    updateUI();

    let attType = data.attackType || "대기 중";
    el.attackTitle.textContent = `Attack_Agent : ${attType}`;
    if (attType.includes("STANDBY") || attType.includes("대기")) {
      el.attackMainImg.style.display = "none";
    } else {
      el.attackMainImg.style.display = "block";
      if (attType.includes("MISSILE") || attType.includes("UGV 미사일")) el.attackMainImg.src = "images/ugv_attack.png";
      else if (attType.includes("DRONE") || attType.includes("드론")) el.attackMainImg.src = "images/uav_attack.png";
      else if (attType.includes("BLURRING") || attType.includes("블러링")) el.attackMainImg.src = "images/blurring.png";
      else if (attType.includes("SPOOFING") || attType.includes("스푸핑") || attType.includes("REPLAY")) el.attackMainImg.src = "images/spoofing.png";
      else el.attackMainImg.src = "images/noise.png";
    }

    let defName = data.defenseName || "대기 중";
    el.defenseTitle.textContent = `Defense_Agent : ${defName}`;
    if (defName.includes("STANDBY") || defName.includes("대기") || attType.includes("STANDBY") || attType.includes("대기")) {
      el.defenseMainImg.style.display = "none";
    } else {
      el.defenseMainImg.style.display = "block";
      if (defName.includes("Interceptor") || defName.includes("요격")) el.defenseMainImg.src = "images/interceptor_missile.png";
      else if (defName.includes("Vulcan") || defName.includes("발칸")) el.defenseMainImg.src = "images/vulcan_cannon.png";
      else if (defName.includes("해시") || defName.includes("광학") || defName.includes("스푸핑") || defName.includes("리플레이")) el.defenseMainImg.src = "images/spoofing_defense.png";
      else if (defName.includes("센서") || defName.includes("감마") || defName.includes("블러링") || defName.includes("편광")) el.defenseMainImg.src = "images/blurring_defense.png";
      else el.defenseMainImg.src = "images/noise_defense.png";
    }

    el.outcomeAttack.textContent = attType;
    el.outcomeStatus.innerHTML = data.outcomeStatus || "대기 중";
    let defSuccess = data.defenseSuccess;
    el.outcomeStatus.className = `outcome-status ${defSuccess ? 'success' : (attType.includes('STANDBY') || attType.includes('대기') ? '' : 'fail')}`;

    if (data.notice && el.noticeBanner) {
      el.noticeBanner.textContent = data.notice;
      if (data.notice.includes("분석 중") || data.notice.includes("구축 중")) {
        el.noticeBanner.style.borderColor = "#ffaa00";
        el.noticeBanner.style.color = "#ffaa00";
        el.noticeBanner.style.background = "rgba(255, 170, 0, 0.1)";
      } else {
        el.noticeBanner.style.borderColor = "#00ffaa";
        el.noticeBanner.style.color = "#00ffaa";
        el.noticeBanner.style.background = "rgba(0, 255, 170, 0.08)";
      }
    }

    if (state.globalRound > 1) {
      let curRound = state.globalRound - 1;
      let cycleIdx = (curRound - 1) % 3;
      let cycleStart = curRound - cycleIdx;
      el.r1Title.textContent = `Round ${cycleStart}`;
      el.r2Title.textContent = `Round ${cycleStart + 1}`;
      el.r3Title.textContent = `Round ${cycleStart + 2}`;

      let boxes = [
        { round: cycleStart, imgEl: el.r1Img },
        { round: cycleStart + 1, imgEl: el.r2Img },
        { round: cycleStart + 2, imgEl: el.r3Img }
      ];
      boxes.forEach(box => {
        let log = (data.historyLogs || []).find(l => l.round === box.round);
        if (log) {
          box.imgEl.src = log.win === '방어' ? "images/defense_win.png" : "images/attack_win.png";
          box.imgEl.style.display = "inline-block";
        } else {
          box.imgEl.style.display = "none";
        }
      });
    } else {
      clearRoundBoxes(1);
    }


    if (el.historyTbody && data.historyLogs && (data.historyLogs.length !== lastPolledRound || el.historyTbody.children.length === 0)) {
      el.historyTbody.innerHTML = "";
      data.historyLogs.forEach(log => {
        let row = document.createElement("tr");
        row.innerHTML = `
          <td>Round ${log.round}</td>
          <td>${log.attack}</td>
          <td>${log.defense}</td>
          <td>${log.win === '방어' ? '<span class="win-def">방어</span>' : '<span class="win-att">공격</span>'}</td>
          <td>${log.aPoint} pt</td>
          <td>${log.dPoint} pt</td>
          <td>${log.tPoint} pt</td>
        `;
        el.historyTbody.appendChild(row);
      });
      lastPolledRound = data.historyLogs.length;
    }

    if (data.gameOver) {
      triggerGameOver(data.winner === "ATTACK" ? "ATTACK VICTORY" : "DEFENSE VICTORY", data.winReason || "시뮬레이션 종료");
      return;
    }
    if (state.availLoss >= 100 || state.syncLoss >= 100 || state.integLoss >= 100) {
      let reason = state.availLoss >= 100 ? "가용성(Availability) 100% 붕괴로 시스템 마비" : (state.syncLoss >= 100 ? "동기화(Synchronization) 100% 붕괴로 데이터 불일치" : "무결성(Integrity) 100% 붕괴로 보안 체계 파괴");
      triggerGameOver("ATTACK VICTORY", reason);
      return;
    }
    let availPct = Math.max(0, 100 - state.availLoss);
    let winReq = Math.round(1000 * (availPct / 100.0));
    if (state.attackScore >= winReq) {
      triggerGameOver("ATTACK VICTORY", `공격측 승리 조건(${winReq}점) 도달 (가용성 저하로 승리 기준 감소)`);
      return;
    }
    if (state.defenseScore >= winReq) {
      triggerGameOver("DEFENSE VICTORY", `방어측 승리 조건(${winReq}점) 도달 (가용성 저하로 승리 기준 감소)`);
      return;
    }
    if (state.budget < 0.05) {
      triggerGameOver("DEFENSE VICTORY", "공격측 잔여 예산 완전 소진");
      return;
    }
  } catch (e) {
    console.log("Waiting for Docker Ollama backend...");
  }
}

function startSim() {
  if (el.modalOverlay && el.modalOverlay.classList.contains("active")) {
    return;
  }
  state.isRunning = true;
  el.btnStart.textContent = "⏸ PAUSE";
  el.btnStart.style.backgroundColor = "#ff9100";

  let mode = el.simMode ? el.simMode.value : "demo";
  if (!state.intervalId) {
    if (mode === "docker") {
      pollDockerBackend();
      state.intervalId = setInterval(pollDockerBackend, 1000);
    } else {
      stepSim();
      state.intervalId = setInterval(stepSim, state.speedMs);
    }
  }
}

function pauseSim() {
  state.isRunning = false;
  clearInterval(state.intervalId);
  state.intervalId = null;
  el.btnStart.textContent = "▶ RESUME";
  el.btnStart.style.backgroundColor = "#00c853";
}

function resetSim() {
  pauseSim();
  if (el.modalOverlay) el.modalOverlay.classList.remove("active");
  lastPolledRound = -1;
  if (el.simMode && el.simMode.value === "docker") {
    fetch("http://localhost:5000/api/reset", { method: "POST" }).catch(() => { });
  }

  el.btnStart.textContent = "▶ ENGAGE";
  el.btnStart.style.backgroundColor = "#00c853";

  state = {
    isRunning: false,
    intervalId: null,
    speedMs: parseInt(el.simSpeed.value, 10),
    globalRound: 1,
    budget: 20.0,
    spentCost: 0.0,
    attackScore: 0.0,
    defenseScore: 0.0,
    availLoss: 0, syncLoss: 0, integLoss: 0,
    ugvCooldown: 0, uavCooldown: 0, adaptiveDenoiseCount: 0
  };

  clearRoundBoxes(1);
  updateUI();
  if (el.historyTbody) el.historyTbody.innerHTML = "";

  el.attackTitle.textContent = "Attack_Agent : 대기 중";
  el.attackMainImg.src = "";
  el.attackMainImg.style.display = "none";

  el.defenseTitle.textContent = "Defense_Agent : 대기 중";
  el.defenseMainImg.src = "";
  el.defenseMainImg.style.display = "none";

  el.outcomeAttack.textContent = "대기 중";
  el.outcomeStatus.textContent = "대기 중";
  el.outcomeStatus.className = "outcome-status";
  if (el.noticeBanner) {
    el.noticeBanner.textContent = " LLM 최초 공격 패턴 구축 중 ... ";
    el.noticeBanner.style.borderColor = "#00ffaa";
    el.noticeBanner.style.color = "#00ffaa";
    el.noticeBanner.style.background = "rgba(0, 255, 170, 0.08)";
  }
}

function clearRoundBoxes(startRoundNum) {
  el.r1Title.textContent = `Round ${startRoundNum}`;
  el.r2Title.textContent = `Round ${startRoundNum + 1}`;
  el.r3Title.textContent = `Round ${startRoundNum + 2}`;

  el.r1Img.style.display = "none";
  el.r2Img.style.display = "none";
  el.r3Img.style.display = "none";
}

function stepSim() {
  let cycleIdx = (state.globalRound - 1) % 3;
  if (cycleIdx === 0) {
    clearRoundBoxes(state.globalRound);
  }

  if (state.budget < 2.0) {
    triggerGameOver("DEFENSE VICTORY", "공격측 잔여 예산 완전 소진");
    return;
  }

  let attType = "";
  let attCost = 0;
  let isPhysical = false;

  if (cycleIdx === 0) {
    attType = Math.random() > 0.5 ? "STEALTH_NOISE" : "ADVERSARIAL_NOISE";
  } else if (cycleIdx === 1) {
    isPhysical = true;
    if (state.budget >= COSTS.MISSILE_SURGICAL_STRIKE && state.ugvCooldown === 0) {
      attType = "MISSILE_SURGICAL_STRIKE";
    } else {
      attType = "DRONE_SWARM";
    }
  } else {
    attType = Math.random() > 0.5 ? "SPOOFING" : "BLURRING";
  }

  attCost = COSTS[attType] || 0;
  if (state.budget < attCost) {
    triggerGameOver("DEFENSE VICTORY", "예산 부족으로 공격 수행 불가");
    return;
  }

  state.budget -= attCost;
  state.spentCost += attCost;

  let attMap = {
    "MISSILE_SURGICAL_STRIKE": "UGV 미사일 타격",
    "DRONE_SWARM": "자폭 드론 군집",
    "STEALTH_NOISE": "스텔스 노이즈",
    "ADVERSARIAL_NOISE": "적대적 노이즈",
    "SPOOFING": "동적 리플레이 스푸핑",
    "DYNAMIC_REPLAY": "동적 리플레이 스푸핑",
    "BLURRING": "화이트아웃 주입 블러링",
    "PULSED_BLINDING": "화이트아웃 주입 블러링"
  };
  let attDisplay = attMap[attType] || attType;

  el.attackMainImg.style.display = "block";
  el.attackTitle.textContent = `Attack_Agent : ${attDisplay}`;
  if (attType === "MISSILE_SURGICAL_STRIKE") {
    el.attackMainImg.src = "images/ugv_attack.png";
  } else if (attType === "DRONE_SWARM") {
    el.attackMainImg.src = "images/uav_attack.png";
  } else if (attType === "BLURRING" || attType === "PULSED_BLINDING") {
    el.attackMainImg.src = "images/blurring.png";
  } else if (attType === "SPOOFING" || attType === "DYNAMIC_REPLAY") {
    el.attackMainImg.src = "images/spoofing.png";
  } else {
    el.attackMainImg.src = "images/noise.png";
  }

  let defName = "";
  let defSuccess = true;

  if (attType === "ADVERSARIAL_NOISE") {
    state.adaptiveDenoiseCount++;
    let prob = Math.min(0.95, 0.40 + 0.15 * (state.adaptiveDenoiseCount - 1));
    defSuccess = Math.random() <= prob;
    defName = "LLM 적응형 디노이징";
    el.defenseMainImg.src = "images/noise_defense.png";
  } else if (attType === "STEALTH_NOISE") {
    defSuccess = Math.random() <= 0.60;
    defName = "윤곽선 무결성 보존";
    el.defenseMainImg.src = "images/noise_defense.png";
  } else if (attType === "MISSILE_SURGICAL_STRIKE") {
    defSuccess = Math.random() <= 0.70;
    let ugvHit = Math.random() <= 0.70;
    state.lastUgvHit = ugvHit;
    defName = "요격 미사일";
    el.defenseMainImg.src = "images/interceptor_missile.png";
    if (ugvHit) state.ugvCooldown = 1;
  } else if (attType === "DRONE_SWARM") {
    defSuccess = Math.random() <= 0.40;
    defName = "발칸포";
    el.defenseMainImg.src = "images/vulcan_cannon.png";
    if (defSuccess && Math.random() <= 0.5) state.uavCooldown = 1;
  } else if (attType === "DYNAMIC_REPLAY" || attType === "SPOOFING") {
    defSuccess = Math.random() <= 0.75;
    defName = Math.random() > 0.5 ? "동적 지각 해시 검증" : "시공간 광학 흐름 연속성 검증";
    el.defenseMainImg.src = "images/spoofing_defense.png";
  } else if (attType === "PULSED_BLINDING" || attType === "BLURRING") {
    defSuccess = Math.random() <= 0.70;
    defName = Math.random() > 0.5 ? "다중 센서 교차 검증" : "적응형 감마 클리핑 및 편광 필터링";
    el.defenseMainImg.src = "images/blurring_defense.png";
  }

  el.defenseMainImg.style.display = "block";
  el.defenseTitle.textContent = `Defense_Agent : ${defName}`;

  if (!defSuccess) {
    if (attType === "MISSILE_SURGICAL_STRIKE") {
      state.availLoss = Math.min(100, state.availLoss + 20);
      state.attackScore = Math.round((state.attackScore + 200.0) * 10) / 10;
    } else if (attType === "DRONE_SWARM") {
      state.availLoss = Math.min(100, state.availLoss + 10);
      state.attackScore = Math.round((state.attackScore + 120.0) * 10) / 10;
    } else if (attType === "DYNAMIC_REPLAY" || attType === "SPOOFING") {
      state.syncLoss = Math.min(100, state.syncLoss + 25);
      state.attackScore = Math.round((state.attackScore + 120.0) * 10) / 10;
    } else if (attType === "PULSED_BLINDING" || attType === "BLURRING") {
      state.availLoss = Math.min(100, state.availLoss + 5);
      state.attackScore = Math.round((state.attackScore + 150.0) * 10) / 10;
    } else if (attType === "ADVERSARIAL_NOISE") {
      state.attackScore = Math.round((state.attackScore + 50.0) * 10) / 10;
    } else {
      state.attackScore = Math.round((state.attackScore + 30.0) * 10) / 10;
    }
  } else {
    let shift = 20.0;
    if (attType === "MISSILE_SURGICAL_STRIKE") shift = 120.0;
    else if (attType === "DRONE_SWARM") shift = 80.0;
    else if (attType === "BLURRING" || attType === "PULSED_BLINDING") shift = 100.0;
    else if (attType === "SPOOFING" || attType === "DYNAMIC_REPLAY") shift = 120.0;
    else if (attType === "ADVERSARIAL_NOISE") shift = 30.0;
    state.defenseScore = Math.round((state.defenseScore + shift) * 10) / 10;
  }

  if (isPhysical) {
    if (state.ugvCooldown > 0 && attType !== "MISSILE_SURGICAL_STRIKE") state.ugvCooldown--;
    if (state.uavCooldown > 0 && attType !== "DRONE_SWARM") state.uavCooldown--;
  }

  let targetImgEl = cycleIdx === 0 ? el.r1Img : (cycleIdx === 1 ? el.r2Img : el.r3Img);
  targetImgEl.src = defSuccess ? "images/defense_win.png" : "images/attack_win.png";
  targetImgEl.style.display = "inline-block";

  el.outcomeAttack.textContent = attDisplay;
  if (attType === "MISSILE_SURGICAL_STRIKE") {
    let ugvStr = state.lastUgvHit ? "UGV 요격 성공" : "UGV 요격 실패";
    let mslStr = defSuccess ? "미사일 요격 성공" : "미사일 요격 실패";
    el.outcomeStatus.innerHTML = `${ugvStr}<br>${mslStr}`;
  } else {
    el.outcomeStatus.textContent = defSuccess ? "방어 성공" : "방어 실패";
  }
  el.outcomeStatus.className = `outcome-status ${defSuccess ? 'success' : 'fail'}`;

  updateUI();

  if (el.historyTbody) {
    let availPct = Math.max(0, 100 - state.availLoss);
    let totScore = (state.attackScore + state.defenseScore) * (availPct / 100.0);
    let row = document.createElement("tr");
    row.innerHTML = `
      <td>Round ${state.globalRound}</td>
      <td>${attDisplay}</td>
      <td>${defName}</td>
      <td>${defSuccess ? '<span class="win-def">방어</span>' : '<span class="win-att">공격</span>'}</td>
      <td>${state.attackScore.toFixed(1)} pt</td>
      <td>${state.defenseScore.toFixed(1)} pt</td>
      <td>${totScore.toFixed(1)} pt</td>
    `;
    el.historyTbody.appendChild(row);
  }

  if (state.availLoss >= 100 || state.syncLoss >= 100 || state.integLoss >= 100) {
    let reason = state.availLoss >= 100 ? "가용성(Availability) 100% 붕괴로 시스템 마비" : (state.syncLoss >= 100 ? "동기화(Synchronization) 100% 붕괴로 데이터 불일치" : "무결성(Integrity) 100% 붕괴로 보안 체계 파괴");
    triggerGameOver("ATTACK VICTORY", reason);
    return;
  }
  let availPct = Math.max(0, 100 - state.availLoss);
  let winReq = Math.round(1000 * (availPct / 100.0));
  if (state.attackScore >= winReq) {
    triggerGameOver("ATTACK VICTORY", `공격측 승리 조건(${winReq}점) 도달 (가용성 저하로 승리 기준 감소)`);
    return;
  }
  if (state.defenseScore >= winReq) {
    triggerGameOver("DEFENSE VICTORY", `방어측 승리 조건(${winReq}점) 도달 (가용성 저하로 승리 기준 감소)`);
    return;
  }
  if (state.budget < 0.05) {
    triggerGameOver("DEFENSE VICTORY", "공격측 잔여 예산 완전 소진");
    return;
  }

  let completedRound = state.globalRound;
  if (el.noticeBanner) {
    if (completedRound % 3 === 0) {
      let last3 = (el.historyTbody ? Array.from(el.historyTbody.children).slice(-3) : []);
      let attWins = last3.filter(r => r.innerHTML.includes("win-att")).length;
      if (attWins < 2) {
        el.noticeBanner.textContent = `${completedRound} Round ( Attack_Agent 다른 공격 패턴 구축 중 ... )`;
        el.noticeBanner.style.borderColor = "#ffaa00";
        el.noticeBanner.style.color = "#ffaa00";
        el.noticeBanner.style.background = "rgba(255, 170, 0, 0.1)";
      } else {
        el.noticeBanner.textContent = `${completedRound} Round ( Attack_Agent 현재 공격 패턴 유지 )`;
        el.noticeBanner.style.borderColor = "#ffaa00";
        el.noticeBanner.style.color = "#ffaa00";
        el.noticeBanner.style.background = "rgba(255, 170, 0, 0.1)";
      }
    } else {
      el.noticeBanner.textContent = `${completedRound} Round`;
      el.noticeBanner.style.borderColor = "#00ffaa";
      el.noticeBanner.style.color = "#00ffaa";
      el.noticeBanner.style.background = "rgba(0, 255, 170, 0.08)";
    }
  }

  state.globalRound++;
}

function updateUI() {
  let availPct = Math.max(0, 100 - state.availLoss);
  let totScore = (state.attackScore + state.defenseScore) * (availPct / 100.0);

  el.totalScoreBox.textContent = `Total_Score: ${totScore.toFixed(1)} pt`;
  el.attackScoreVal.textContent = `${state.attackScore.toFixed(1)} pt`;
  el.defenseScoreVal.textContent = `${state.defenseScore.toFixed(1)} pt`;

  let winReq = Math.round(1000 * (availPct / 100.0));
  if (el.victoryReqVal) {
    el.victoryReqVal.textContent = `${winReq}`;
  }

  el.meterAvail.textContent = `${availPct} %`;
  el.meterAvail.className = `circle-meter ${availPct < 40 ? 'danger' : (availPct < 70 ? 'warning' : '')}`;

  el.meterSync.textContent = `${state.syncLoss} %`;
  el.meterSync.className = `circle-meter ${state.syncLoss > 60 ? 'danger' : (state.syncLoss > 30 ? 'warning' : '')}`;

  el.meterInteg.textContent = `${state.integLoss} %`;
  el.meterInteg.className = `circle-meter ${state.integLoss > 60 ? 'danger' : (state.integLoss > 30 ? 'warning' : '')}`;

  el.meterBudget.textContent = `${state.budget.toFixed(2)} M$`;
  el.meterBudget.className = `circle-meter ${state.budget < 4.0 ? 'danger' : (state.budget < 8.0 ? 'warning' : '')}`;
}

function triggerGameOver(title, desc) {
  pauseSim();
  let isDef = title.includes("DEFENSE");
  el.modalTitle.textContent = isDef ? "Defense Agent Win" : "Attack Agent Win";
  if (el.modalDesc) {
    let formattedDesc = desc || "시뮬레이션 종료";
    formattedDesc = formattedDesc.replace(/<br>\s*/g, " ");
    formattedDesc = formattedDesc.replace(/!\s*\((Defense Victory|Attack Victory|가용성 저하로 승리 기준 감소)\)/g, "!<br>($1)");
    formattedDesc = formattedDesc.replace(/ \((Defense Victory|Attack Victory|가용성 저하로 승리 기준 감소)\)/g, "<br>($1)");
    el.modalDesc.innerHTML = formattedDesc;
    el.modalDesc.style.display = "block";
    el.modalDesc.style.color = isDef ? "#00ffaa" : "#ff2a4b";
  }
  if (el.modalIcon) {
    el.modalIcon.src = isDef ? "images/defense_logo.png" : "images/attack_logo.png";
  }
  el.modalOverlay.classList.add("active");
}

resetSim();
