<template>
  <!-- 배경음악 오디오 (자동 재생, 반복) -->
  <audio ref="bgmAudio" :src="bgmSrc" loop></audio>

  <!-- 화면 전환 애니메이션 -->
  <transition name="fade" mode="out-in">
    <div id="app" :key="state">
      <!-- 로딩 화면 -->
      <div v-if="state === 'loading'" class="loading">
        LLM을 이용해 문제 생성중...<br>
        이 과정은 오래 걸릴 수 있습니다. (최대 1분)
      </div>

      <!-- 메인 메뉴: 닉네임 입력, 키워드 선택, 랭킹보기 버튼 -->
      <div v-else-if="state === 'mainMenu'" class="main-menu">
        <h1>틀린 글 찾기 챌린지</h1>
        <!-- 닉네임 입력 -->
        <div class="nickname-input">
          <input type="text" v-model="nickname" placeholder="닉네임을 입력하세요" />
        </div>
        <!-- 랭킹보기 버튼 -->
        <div class="ranking-btn-container">
          <button class="nav-btn" @click="viewRanking">랭킹보기</button>
        </div>
        <!-- 키워드 버튼 -->
        <div class="keyword-container">
          <button
              v-for="(keyword, index) in keywords"
              :key="index"
              class="keyword-btn"
              :style="{ backgroundColor: keywordColors[index] }"
              @click="startGame(keyword)"
          >
            {{ keyword }}
          </button>
        </div>
      </div>

      <!-- 게임 화면 -->
      <div v-else-if="state === 'game'" class="game">
        <!-- 상단 바: 좌측에 시간, 우측에 뒤로 버튼 -->
        <div class="top-bar">
          <div class="time-container">
            ⏰ <span class="time-text">{{ elapsedTime.toFixed(0) }} 초</span>
          </div>
          <div>틀린 문장 5개를 찾아보세요!</div>
          <div class="back-container">
            <button class="nav-btn" @click="goHome">뒤로</button>
          </div>
        </div>

        <!-- 내용 영역: 책 읽는 느낌의 단락 -->
        <div class="content" ref="contentDiv">
          <p class="book-paragraph">
            <span
                v-for="(sentence, index) in modifiedList"
                :key="index"
                :class="['book-sentence', { selected: selectedIndices.includes(index) }]"
                @click="toggleSelection(index)"
            >
              {{ sentence }}&nbsp;
            </span>
          </p>
        </div>

        <!-- 하단 바: 정답 제출 버튼 -->
        <div class="bottom-bar">
          <button class="submit-btn" @click="submitAnswer">
            정답 제출
          </button>
        </div>
      </div>

      <!-- 결과 화면 -->
      <div v-else-if="state === 'result'" class="result">
        <div class="result-text">
          오류 {{ totalErrors }}개 중 {{ correctCount }}개 맞춤!
        </div>
        <div class="result-message" v-if="correctCount === totalErrors">
          <span class="alert-text">축하합니다! 소요 시간: {{ ((gameEndTime - gameStartTime) / 1000).toFixed(1) }}초</span>
        </div>
        <div class="result-message" v-else>
          <span class="alert-text">아직 더 찾을 오류가 있습니다!</span>
        </div>
        <div class="result-buttons">
          <button v-if="correctCount < totalErrors" @click="retry">
            다시 시도
          </button>
          <button @click="goHome">
            처음으로
          </button>
        </div>
      </div>

      <!-- 랭킹 화면 -->
      <div v-else-if="state === 'ranking'" class="ranking">
        <h1>랭킹</h1>
        <table class="ranking-table">
          <thead>
          <tr>
            <th>순위</th>
            <th>닉네임</th>
            <th>키워드</th>
            <th>걸린 시간 (초)</th>
          </tr>
          </thead>
          <tbody>
          <tr v-for="record in rankings" :key="record.rank">
            <td>{{ record.rank }}</td>
            <td>{{ record.nickname }}</td>
            <td>{{ record.keyword }}</td>
            <td>{{ record.elapsed_time }}</td>
          </tr>
          </tbody>
        </table>
        <button class="nav-btn" @click="goHome">뒤로</button>
      </div>
    </div>
  </transition>
</template>

<script setup>
import {onBeforeUnmount, onMounted, reactive, ref, watch} from 'vue'
import axios from 'axios'
import bgmSrc from './assets/bgm.mp3'

// 미리 정의한 색상 팔레트 (추가 색상 포함)
const colorPalette = [
  "#edcb3d", "#9572E0", "#F1392F", "#FDB12E", "#563CFE", "#A3FFA3", "#F6392F",
  "#53bdea", "#d1405c", "#6dd548", "#f4862f", "#C2B2FF", "#B2FFC2", "#FFCC99"
];

/**
 * 팔레트를 섞어서 키워드 수만큼 고유한 색상을 반환합니다.
 */
function getUniqueColors(num) {
  const availableColors = [...colorPalette];
  for (let i = availableColors.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [availableColors[i], availableColors[j]] = [availableColors[j], availableColors[i]];
  }
  if (num <= availableColors.length) {
    return availableColors.slice(0, num);
  } else {
    let colors = availableColors.slice();
    while (colors.length < num) {
      let newColor = '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0').toUpperCase();
      if (!colors.includes(newColor)) {
        colors.push(newColor);
      }
    }
    return colors;
  }
}

/* --- 게임 관련 상태 --- */
const state = ref('loading'); // 'loading', 'mainMenu', 'game', 'result', 'ranking'
const keywords = ref([]);
const selectedKeyword = ref('');
const problem = reactive({
  right_text: [],
  wrong_text: []
});
const errorIndices = ref([]);
const modifiedList = ref([]);
const selectedIndices = ref([]);
const totalErrors = ref(0);
const correctCount = ref(0);
const gameStartTime = ref(0);
const gameEndTime = ref(0);
const elapsedTime = ref(0);
let timerInterval = null;

// 키워드 버튼별 색상을 저장할 배열
const keywordColors = ref([]);

// 배경음악 엘리먼트 ref
const bgmAudio = ref(null);

// NEW: 사용자 닉네임
const nickname = ref("");

// NEW: 랭킹 데이터 저장 (랭킹 화면에서 사용)
const rankings = ref([]);

// 게임 상태에 따라 배경음악 자동 재생/정지
watch(state, (newVal) => {
  if (newVal === 'game' && bgmAudio.value) {
    bgmAudio.value.play().catch(err => {
      console.warn('Background music play failed:', err);
    });
  } else if (bgmAudio.value) {
    bgmAudio.value.pause();
    bgmAudio.value.currentTime = 0;
  }
});

/* --- 유틸리티 함수: n개 중 count개 랜덤 선택 --- */
function getRandomSample(n, count) {
  const indices = Array.from({length: n}, (_, i) => i);
  const sample = [];
  for (let i = 0; i < count; i++) {
    if (indices.length === 0) break;
    const randIndex = Math.floor(Math.random() * indices.length);
    sample.push(indices[randIndex]);
    indices.splice(randIndex, 1);
  }
  return sample;
  return sample.sort((a, b) => a - b);
}

/* --- API 호출: 키워드 목록 가져오기 --- */
function fetchKeywords() {
  state.value = 'loading';
  axios
      .get('http://localhost:5000/api/keywords')
      .then(response => {
        keywords.value = response.data.keywords;
        // 키워드 수 만큼 고유한 색상 할당
        keywordColors.value = getUniqueColors(keywords.value.length);
        state.value = 'mainMenu';
      })
      .catch(error => {
        console.error('Error fetching keywords:', error);
        keywords.value = ["ChatGPT", "AI 규제", "우주 탐사"];
        keywordColors.value = getUniqueColors(keywords.value.length);
        state.value = 'mainMenu';
      });
}

/* --- 게임 시작: 선택한 키워드로 문제 호출 --- */
function startGame(keyword) {
  // 닉네임 입력 여부 확인
  if (!nickname.value.trim()) {
    alert("닉네임을 입력해주세요.");
    return;
  }
  selectedKeyword.value = keyword;
  state.value = 'loading';
  axios
      .post('http://localhost:5000/api/problem', {keyword})
      .then(response => {
        problem.right_text = response.data.right_text;
        problem.wrong_text = response.data.wrong_text;
        const n = problem.right_text.length;
        errorIndices.value = getRandomSample(n, 5);
        totalErrors.value = errorIndices.value.length;
        modifiedList.value = problem.right_text.map((sentence, index) => {
          return errorIndices.value.includes(index)
              ? problem.wrong_text[index]
              : sentence;
        });
        selectedIndices.value = [];
        gameStartTime.value = Date.now();
        elapsedTime.value = 0;
        if (timerInterval) clearInterval(timerInterval);
        timerInterval = setInterval(() => {
          elapsedTime.value = (Date.now() - gameStartTime.value) / 1000;
        }, 100);
        state.value = 'game';
      })
      .catch(error => {
        console.error('Error fetching problem:', error);
        state.value = 'mainMenu';
      });
}

/* --- 문장 선택 토글 --- */
function toggleSelection(index) {
  const pos = selectedIndices.value.indexOf(index);
  if (pos >= 0) {
    selectedIndices.value.splice(pos, 1);
  } else {
    if (selectedIndices.value.length < 5) {
      selectedIndices.value.push(index);
    }
  }
}

/* --- 정답 제출 --- */
function submitAnswer() {
  correctCount.value = selectedIndices.value.filter(idx =>
      errorIndices.value.includes(idx)
  ).length;
  gameEndTime.value = Date.now();
  // 정답인 경우 랭킹 저장 API 호출 (닉네임, 키워드, 걸린 시간)
  if (correctCount.value === totalErrors.value) {
    const timeTaken = (gameEndTime.value - gameStartTime.value) / 1000;
    axios.post('http://localhost:5000/api/rankings', {
      nickname: nickname.value,
      keyword: selectedKeyword.value,
      elapsed_time: timeTaken
    }).then(() => {
      console.log("Ranking saved");
    }).catch(err => {
      console.error("Failed to save ranking", err);
    });
  }
  state.value = 'result';
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

/* --- 다시 시도 (이전 선택 결과 그대로 유지) --- */
function retry() {
  state.value = 'game';
  gameStartTime.value = Date.now() - elapsedTime.value * 1000;
  if (!timerInterval) {
    timerInterval = setInterval(() => {
      elapsedTime.value = (Date.now() - gameStartTime.value) / 1000;
    }, 100);
  }
}

/* --- 처음으로 (메인 메뉴로 복귀) --- */
function goHome() {
  state.value = 'mainMenu';
  selectedKeyword.value = '';
  problem.right_text = [];
  problem.wrong_text = [];
  errorIndices.value = [];
  modifiedList.value = [];
  selectedIndices.value = [];
  totalErrors.value = 0;
  correctCount.value = 0;
  gameStartTime.value = 0;
  gameEndTime.value = 0;
  elapsedTime.value = 0;
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

/* --- 랭킹보기: 백엔드에서 순위 데이터 가져오기 --- */
function viewRanking() {
  state.value = 'loading';
  axios.get('http://localhost:5000/api/rankings')
      .then(response => {
        rankings.value = response.data.rankings;
        state.value = 'ranking';
      })
      .catch(error => {
        console.error("Failed to fetch rankings", error);
        state.value = 'mainMenu';
      });
}

onMounted(() => {
  fetchKeywords();
});

onBeforeUnmount(() => {
  if (timerInterval) clearInterval(timerInterval);
});
</script>

<style scoped>
/* 화면 전환 페이드 효과 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.5s ease;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* Google Fonts - Open Sans */
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap');

#app {
  background: #000000;
  font-family: 'Open Sans', sans-serif;
  color: #ffffff;
  padding: 20px;
  min-height: 100vh;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  position: relative;
}

/* 제목 스타일 */
h1 {
  font-size: 2.5em;
  margin-bottom: 30px;
  color: #ffffff;
}

/* 기본 버튼 스타일 */
button {
  background: #FC226E;
  color: #FFFFFF;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  transition: transform 0.2s;
  font-family: 'Open Sans', sans-serif;
  font-weight: bold;
}

button:hover {
  transform: scale(1.03);
}

/* 상단 바 */
.top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  margin: 20px 0;
}

.time-container {
  display: flex;
  align-items: center;
  font-size: 1.5em;
  color: #ffffff;
}

.time-container .time-text {
  margin-left: 5px;
}

.back-container {
  display: flex;
  align-items: center;
}

.nav-btn {
  background: #786b6d;
  color: #FFFFFF;
  border: none;
  padding: 10px 20px;
  border-radius: 20px;
  cursor: pointer;
  font-family: 'Open Sans', sans-serif;
  font-weight: bold;
  font-size: 1.2em;
}

.nav-btn:hover {
  transform: scale(1.03);
}

/* 하단 바 */
.bottom-bar {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  max-width: 720px;
  margin: 20px 0;
}

/* 메인 메뉴 내 키워드 버튼 */
.keyword-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 15px;
}

.keyword-btn {
  font-size: 2rem;
}

/* 내용 영역 */
.content {
  background: #FFFFFF;
  border: 1px solid #ddd;
  border-radius: 10px;
  padding: 25px;
  width: 100%;
  max-width: 720px;
}

.book-paragraph {
  font-size: 1.1em;
  line-height: 1.8;
  text-align: justify;
  margin: 0;
  color: #343A40;
}

.book-sentence {
  cursor: pointer;
  transition: background-color 0.3s;
}

.book-sentence.selected {
  background-color: rgba(255, 79, 119, 0.3);
}

.submit-btn {
  font-size: 2rem;
}

/* 로딩, 메인 메뉴, 결과, 랭킹 화면 중앙 정렬 */
.loading,
.main-menu,
.result,
.ranking {
  text-align: center;
  width: 100%;
  max-width: 720px;
}

/* 결과 화면 스타일 */
.result {
  background: #FFFFFF;
  padding: 30px;
  border-radius: 8px;
  box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
  color: #343A40;
}

.result-message {
  font-weight: bold;
}

.result-buttons {
  margin-top: 20px;
}

.result-buttons button {
  margin: 0 10px;
  width: 140px;
  height: 45px;
  font-size: 1em;
  background: #FC226E;
  color: #FFFFFF;
  border: none;
  font-weight: bold;
  border-radius: 20px;
}

/* 닉네임 입력 */
.nickname-input {
  margin-bottom: 20px;
}

.nickname-input input {
  padding: 10px;
  font-size: 1.2rem;
  border-radius: 10px;
  border: 1px solid #ccc;
}

/* 랭킹보기 버튼 컨테이너 */
.ranking-btn-container {
  margin-bottom: 50px;
}

/* 랭킹 테이블 */
.ranking-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 20px;
}

.ranking-table th, .ranking-table td {
  border: 1px solid #ddd;
  padding: 10px;
}

.ranking-table th {
  background-color: #f2f2f2;
  color: #343A40;
}
</style>
