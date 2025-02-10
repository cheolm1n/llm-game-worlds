import logging
import os
from enum import Enum
from typing import List

import sqlite3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain_aws import ChatBedrockConverse
from langchain_core.output_parsers import JsonOutputParser
from langfuse.callback import CallbackHandler

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI()

# CORS 설정 (모든 도메인 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# 순위 저장을 위한 데이터베이스 설정 (SQLite)
# ---------------------------
DATABASE = "rankings.db"

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            keyword TEXT NOT NULL,
            elapsed_time REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------------------------
# 1) Pydantic 모델 (LLM JSON 응답 파싱용)
# ----------------------------------------------------------------------
class KeywordsResponse(BaseModel):
    keywords: List[str] = Field(..., description="List of keywords")

class ProblemResponse(BaseModel):
    category: str = Field(..., description="주어진 분야")
    subject: str = Field(..., description="분야의 세부 주제")
    story_idea: str = Field(..., description="분야의 세부 주제를 바탕으로 정한 글감")
    right_text: List[str] = Field(
        ...,
        description="키워드를 바탕으로 생성된 500자 이상, 15개 문장의 글을 문장 단위로 자른 리스트"
    )
    wrong_text: List[str] = Field(
        ...,
        description="right_text의 문장 잘못된 내용으로 교체한 리스트"
    )

# 랭킹 저장 및 조회를 위한 모델
class RankingRecord(BaseModel):
    nickname: str
    keyword: str
    elapsed_time: float

# ----------------------------------------------------------------------
# 2) 프롬프트 상수/enum
# ----------------------------------------------------------------------
class Prompts(Enum):
    # 키워드 생성
    KEYWORDS_PROMPT_SYSTEM = "당신은 전문적인 어시스턴트 입니다."
    KEYWORDS_PROMPT_HUMAN = """
        상식 퀴즈 생성을 위한 키워드를 무작위로 여러 분야게 걸쳐 최대한 다양하게 5개만 뽑아 주세요.
        
        출력 형식을 반드시 준수하여 JSON으로 출력해주세요.
        
        # 출력 형식(JSON):
        {format_instructions}
        """
    # 문제 생성
    PROBLEM_PROMPT_SYSTEM = "당신은 전문적인 어시스턴트 입니다."
    PROBLEM_PROMPT_HUMAN = """
        분야는 {keyword} 입니다. 해당 분야에 대한 심층적인 글을 작성하려고 합니다. 이를 위해 다음과 같은 단계로 진행해주세요.
        
        ## 1단계: 세부 주제 도출
        - 흥미롭고 의미 있는 세부 주제를 3~5개 제안해주세요.
        - 각 세부 주제는 독자가 관심을 가질 만한 내용이어야 하며, 최신 트렌드나 일반적인 논의에서 발전된 형태여야 합니다.
        
        ## 2단계: 세부 주제 구체화 및 글감 선정
        - 제안된 세부 주제 중 하나를 선택하여 더욱 구체화하세요.
        - 구체화된 주제에서 핵심적인 내용을 다룰 글감을 선정하세요.
        - 글감은 명확하고 구체적인 개념, 사건, 제품, 이론 등이 될 수 있습니다.
        
        ## 3단계: 글 작성
        - 선정된 글감에 대해 **최소 500자, 최대 1000자, 최소 15문장, 최대 20문장** 사이의 글을 작성하세요.
        - **사실 기반**으로 작성해야 하며, 논리적으로 문장이 연결되도록 한 문단으로 구성해야 합니다.
        - 독자가 글을 읽고 자연스럽게 이해할 수 있도록 작성해주세요.
        - 고등 학생 이상의 성인이 이해 할 수 있는 수준의 글을 작성해주세요.
        - 지나치게 전문화된 글은 이해하기 어려우니 비전문가도 이해할 수 있게 작성해주세요.
        
        ## 4단계: 올바른 문장과 잘못된 문장 생성
        - 작성한 문장을 문장 단위로 나누어 리스트(`right_text`)로 저장하세요.
        - 같은 구조를 유지하면서 **right_text의 모든 문장을 사실과 다르게 바꾼 리스트(`wrong_text`)**를 생성하세요.
            - 날짜, 인물, 사건, 특징 등을 허위 정보를 섞어 작성합니다. 
            - 문장의 갯수와 구조는 원본과 동일해야 합니다.

        # 예시
        ```
        {{
          "category": "게임",
          "topic_suggestions": ["신작 게임 소개", "게임 산업 트렌드", "게임과 AI의 관계"],
          "selected_topic": "신작 게임 소개",
          "specific_subject": "몬스터 헌터 와일즈",
          "right_text": [
            "'몬스터 헌터 와일즈'는 캡콤이 개발한 액션 롤플레잉 게임으로, 2025년 2월 28일에 출시될 예정이다.",
            "플레이어는 '금지된 땅'이라 불리는 미지의 영역에서 헌터로서 거대한 몬스터를 사냥하게 된다.",
            "...",
            "게임은 PlayStation 5, Xbox Series X/S, PC 등 다양한 플랫폼에서 이용 가능하다."
          ],
          "wrong_text": [
            "'몬스터 헌터 와일즈'는 유비소프트가 개발한 스포츠 게임으로, 2023년 10월 15일에 출시되었다.",
            "플레이어는 '열린 평원'이라 불리는 도시 지역에서 동물들과 경주하게 된다.",
            "...",
            "게임은 Nintendo Switch에서만 이용 가능하다."
          ]
        }}
        ```
                
        ## 5단계: JSON 출력
        - 최종 결과만 반드시 JSON 형식으로 출력하세요:
        {format_instructions}
        """

# ----------------------------------------------------------------------
# 3) BedrockChatModel Enum (예시)
# ----------------------------------------------------------------------
class BedrockChatModel(Enum):
    NOVA_PRO = "us.amazon.nova-pro-v1:0"
    NOVA_MICRO = "us.amazon.nova-micro-v1:0"

# ----------------------------------------------------------------------
# 4) get_chat_model (Stub)
# ----------------------------------------------------------------------
def get_chat_model(model: str, temperature: float):
    if os.getenv("PHASE") == "LOCAL":
        return ChatBedrockConverse(
            model=model,
            temperature=temperature,
            region_name="us-west-2",
            credentials_profile_name="saml",
        )
    else:
        return ChatBedrockConverse(
            model=model,
            temperature=temperature,
            region_name="us-west-2",
        )

langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
    tags=["find-hallucination"]
)

# ----------------------------------------------------------------------
# 5) 키워드 생성 함수
# ----------------------------------------------------------------------
def generate_keywords() -> dict:
    state = {}
    parser = JsonOutputParser(pydantic_object=KeywordsResponse)
    keywords_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(Prompts.KEYWORDS_PROMPT_SYSTEM.value),
        HumanMessagePromptTemplate.from_template(Prompts.KEYWORDS_PROMPT_HUMAN.value),
    ]).partial(format_instructions=parser.get_format_instructions())
    llm = get_chat_model(model=BedrockChatModel.NOVA_PRO.value, temperature=1)
    chain = keywords_prompt | llm | parser
    try:
        llm_response = chain.invoke({}, config={"callbacks": [langfuse_handler]})
        state = llm_response
        logging.info(f"[generate_keywords]: {state}")
    except Exception as e:
        logging.error(f"[generate_keywords] error: {e}")
        state["keywords"] = ["ChatGPT", "AI 규제", "우주 탐사"]
    return state

# ----------------------------------------------------------------------
# 6) 문제 생성 함수
# ----------------------------------------------------------------------
def generate_problem(keyword: str) -> dict:
    state = {}

    parser = JsonOutputParser(pydantic_object=ProblemResponse)
    problem_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(Prompts.PROBLEM_PROMPT_SYSTEM.value),
        HumanMessagePromptTemplate.from_template(Prompts.PROBLEM_PROMPT_HUMAN.value),
    ]).partial(format_instructions=parser.get_format_instructions())
    llm = get_chat_model(model=BedrockChatModel.NOVA_PRO.value, temperature=0.3)
    chain = problem_prompt | llm | parser
    try:
        llm_response = chain.invoke({"keyword": keyword}, config={"callbacks": [langfuse_handler]})
        state = llm_response
        logging.info(f"[generate_problem]: {state}")
    except Exception as e:
        logging.error(f"[generate_problem] error: {e}")
    return state

# ----------------------------------------------------------------------
# 7) API 엔드포인트
# ----------------------------------------------------------------------
@app.get("/api/keywords")
async def api_keywords():
    result = generate_keywords()
    # TEST 용 stub
    # result = {"keywords":["역사적 사건","문화적 관습","과학적 원리","문학적 작품","지리적 특징"]}
    return result

@app.post("/api/problem")
async def api_problem(request: Request):
    data = await request.json()
    keyword = data.get("keyword", "")
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword is required")
    result = generate_problem(keyword)
    # TEST 용 stub
    # result = {
    #     "category": "과학적 원리",
    #     "subject": "양자 컴퓨팅의 기본 원리와 응용",
    #     "story_idea": "양자 컴퓨팅의 기본 원리와 현재 응용 사례",
    #     "right_text": [
    #         "양자 컴퓨팅은 고전적인 컴퓨팅과는 다른 방식으로 정보를 처리하는 기술이다.",
    #         "고전적인 컴퓨터는 비트를 사용하여 정보를 처리하지만, 양자 컴퓨터는 큐비트를 사용한다.",
    #         "큐비트는 중첩성과 얽힘이라는 양자 역학의 특성을 이용하여 동시에 여러 상태를 가질 수 있다.",
    #         "이러한 특성 덕분에 양자 컴퓨터는 특정 유형의 문제를 훨씬 더 빠르게 해결할 수 있다.",
    #         "양자 컴퓨팅의 응용 분야로는 암호 해독, 화학 모사, 최적화 문제 등이 있다.",
    #         "양자 컴퓨팅은 현재 연구 단계에 있으며, 상용화를 위한 노력이 진행 중이다.",
    #         "IBM, Google, Microsoft 등 여러 기업이 양자 컴퓨터 개발에 투자하고 있다.",
    #         "2019년 10월, Google은 양자 우월성을 달성했다고 발표했다.",
    #         "양자 우월성이란 양자 컴퓨터가 고전적인 컴퓨터보다 더 빠르게 문제를 해결할 수 있다는 것을 의미한다.",
    #         "양자 컴퓨팅은 미래 산업에 큰 영향을 미칠 것으로 예상된다.",
    #         "하지만 현재로서는 양자 컴퓨터의 안정성과 오류 수정 기술이 아직 완벽하지 않다.",
    #         "양자 컴퓨팅 연구자들은 이러한 문제를 해결하기 위해 노력하고 있다.",
    #         "양자 컴퓨팅의 발전은 과학과 기술 분야에서 큰 혁신을 가져올 것으로 기대된다.",
    #         "양자 컴퓨팅은 여전히 많은 연구와 개발이 필요한 분야이다.",
    #         "그러나 그 잠재력은 이미 많은 이들의 관심을 끌고 있다."
    #     ],
    #     "wrong_text": [
    #         "양자 컴퓨팅은 고전적인 컴퓨팅과 동일한 방식으로 정보를 처리하는 기술이다.",
    #         "고전적인 컴퓨터는 큐비트를 사용하여 정보를 처리하지만, 양자 컴퓨터는 비트를 사용한다.",
    #         "비트는 중첩성과 얽힘이라는 고전 역학의 특성을 이용하여 동시에 여러 상태를 가질 수 없다.",
    #         "이러한 특성으로 인해 양자 컴퓨터는 특정 유형의 문제를 훨씬 더 느리게 해결한다.",
    #         "양자 컴퓨팅의 응용 분야로는 암호 생성, 물리 모사, 복잡화 문제 등이 있다.",
    #         "양자 컴퓨팅은 현재 상용화 단계에 있으며, 연구를 위한 노력이 진행 중이다.",
    #         "Apple, Samsung, Huawei 등 여러 기업이 양자 컴퓨터 개발에 투자하고 있다.",
    #         "2017년 5월, Microsoft는 양자 우월성을 달성했다고 발표했다.",
    #         "양자 우월성이란 고전적인 컴퓨터가 양자 컴퓨터보다 더 빠르게 문제를 해결할 수 있다는 것을 의미한다.",
    #         "양자 컴퓨팅은 미래 산업에 거의 영향을 미치지 않을 것으로 예상된다.",
    #         "현재로서는 양자 컴퓨터의 안정성과 오류 수정 기술이 이미 완벽하다.",
    #         "양자 컴퓨팅 연구자들은 이미 해결된 문제를 다시 연구하고 있다.",
    #         "양자 컴퓨팅의 발전은 과학과 기술 분야에서 큰 혁신을 가져오지 않을 것으로 기대된다.",
    #         "양자 컴퓨팅은 이미 완성된 분야이다.",
    #         "그러나 그 잠재력은 거의 관심을 끌지 않고 있다."
    #     ]
    # }
    return result

# ---------------------------
# 8) 랭킹 저장 API (POST) – 10위 초과 시 하위 기록 삭제
# ---------------------------
@app.post("/api/rankings")
async def save_ranking(record: RankingRecord):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO rankings (nickname, keyword, elapsed_time) VALUES (?, ?, ?)",
                   (record.nickname, record.keyword, record.elapsed_time))
    conn.commit()
    # 전체 기록을 걸린 시간 순으로 정렬 후, 10위 밖 기록 삭제
    cursor.execute("SELECT id FROM rankings ORDER BY elapsed_time ASC")
    rows = cursor.fetchall()
    if len(rows) > 10:
        for row in rows[10:]:
            cursor.execute("DELETE FROM rankings WHERE id = ?", (row[0],))
        conn.commit()
    conn.close()
    return {"status": "ok"}

# ---------------------------
# 9) 랭킹 조회 API (GET) – 순위, 닉네임, 키워드, 걸린 시간 반환
# ---------------------------
@app.get("/api/rankings")
async def get_rankings():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute("SELECT nickname, keyword, elapsed_time FROM rankings ORDER BY elapsed_time ASC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    rankings_list = []
    for idx, row in enumerate(rows):
        rankings_list.append({
            "rank": idx + 1,
            "nickname": row[0],
            "keyword": row[1],
            "elapsed_time": row[2]
        })
    return {"rankings": rankings_list}

# ----------------------------------------------------------------------
# 10) Uvicorn 실행
# ----------------------------------------------------------------------
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="info")
