import logging
import os
from enum import Enum
from typing import List

from dotenv import load_dotenv
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain_aws import ChatBedrockConverse
from langchain_core.output_parsers import JsonOutputParser
from langfuse.callback import CallbackHandler
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(level=logging.INFO)

langfuse_handler = CallbackHandler(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST"),
    tags=["find-hallucination"]
)


# ----------------------------------------------------------------------
# 1) Pydantic 모델 (LLM JSON 응답 파싱용)
# ----------------------------------------------------------------------
class KeywordsResponse(BaseModel):
    keywords: List[str] = Field(..., description="List of keywords")


class ProblemResponse(BaseModel):
    category: str = Field(..., description="주어진 분야")
    subject: str = Field(..., description="분야의 세부 주제")
    story_idea: str = Field(..., description="분야의 세부 주제를 바탕으로 정한 글감")
    right_text: List[str] = Field(..., description="키워드를 바탕으로 생성된 500자 이상, 15개 문장의 글을 문장 단위로 자른 리스트")
    wrong_text: List[str] = Field(..., description="right_text의 문장 잘못된 내용으로 교체한 리스트")


# ----------------------------------------------------------------------
# 2) 프롬프트 상수/enum
# ----------------------------------------------------------------------
class Prompts(Enum):
    # 키워드 생성
    KEYWORDS_PROMPT_SYSTEM = (
        "당신은 전문적인 어시스턴트 입니다."
    )
    KEYWORDS_PROMPT_HUMAN = (
        """
        상식 퀴즈 생성을 위한 키워드를 다양하게 5개만 뽑아 주세요.
        
        출력 형식을 반드시 준수하여 JSON으로 출력해주세요.
        
        # 출력 형식(JSON):
        {format_instructions}
        """
    )

    # 문제 생성
    PROBLEM_PROMPT_SYSTEM = (
        "당신은 전문적인 어시스턴트 입니다."
    )
    PROBLEM_PROMPT_HUMAN = (
        """
        분야는 {keyword} 입니다. 해당 분야에 대한 심층적인 글을 작성하려고 합니다. 이를 위해 다음과 같은 단계로 진행해주세요.
        
        ## 1단계: 세부 주제 도출
        - 흥미롭고 의미 있는 세부 주제를 3~5개 제안해주세요.
        - 각 세부 주제는 독자가 관심을 가질 만한 내용이어야 하며, 최신 트렌드나 일반적인 논의에서 발전된 형태여야 합니다.
        
        ## 2단계: 세부 주제 구체화 및 글감 선정
        - 제안된 세부 주제 중 하나를 선택하여 더욱 구체화하세요.
        - 구체화된 주제에서 핵심적인 내용을 다룰 글감을 선정하세요.
        - 글감은 명확하고 구체적인 개념, 사건, 제품, 이론 등이 될 수 있습니다.
        
        ## 3단계: 글 작성
        - 선정된 글감에 대해 **500~550자, 15문장 분량**으로 글을 작성하세요.
        - **사실 기반**으로 작성해야 하며, 논리적으로 문장이 연결되도록 한 문단으로 구성해야 합니다.
        - 독자가 글을 읽고 자연스럽게 이해할 수 있도록, 개념을 설명하고 관련 정보를 제공하세요.
        
        ## 4단계: 올바른 문장과 잘못된 문장 생성
        - 작성한 문장을 문장 단위로 나누어 리스트(`right_text`)로 저장하세요.
        - 동시에, 같은 구조를 유지하면서 **모든 문장을 사실과 다르게 바꾼 리스트(`wrong_text`)**를 생성하세요.
          - 사실과 다르게 바꿀 때는 날짜, 인물, 사건, 특징 등을 변형하여 허위 정보를 만들되, 문장 구조는 원본과 유사해야 합니다.

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
    )


# ----------------------------------------------------------------------
# 3) BedrockChatModel Enum (예시)
# ----------------------------------------------------------------------
class BedrockChatModel(Enum):
    # 실제 Bedrock 모델 ID (예: us.amazon.nova-pro-v1:0, 등)
    NOVA_PRO: str = "us.amazon.nova-pro-v1:0"


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


# ----------------------------------------------------------------------
# 5) 키워드 생성 함수
# ----------------------------------------------------------------------
def generate_keywords() -> dict:
    state = {}
    # 1) parser 생성
    parser = JsonOutputParser(pydantic_object=KeywordsResponse)

    # 2) System/Human 프롬프트
    keywords_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(Prompts.KEYWORDS_PROMPT_SYSTEM.value),
        HumanMessagePromptTemplate.from_template(Prompts.KEYWORDS_PROMPT_HUMAN.value),
    ]).partial(format_instructions=parser.get_format_instructions())

    # 3) LLM 준비
    llm = get_chat_model(model=BedrockChatModel.NOVA_PRO.value, temperature=0.7)

    # 5) 체인 구성
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
    # 1) parser 생성
    parser = JsonOutputParser(pydantic_object=ProblemResponse)

    # 2) System/Human 프롬프트
    problem_prompt = ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(Prompts.PROBLEM_PROMPT_SYSTEM.value),
        HumanMessagePromptTemplate.from_template(Prompts.PROBLEM_PROMPT_HUMAN.value),
    ]).partial(format_instructions=parser.get_format_instructions())

    # 3) LLM 준비
    llm = get_chat_model(model=BedrockChatModel.NOVA_PRO.value, temperature=0.3)

    # 4) chain 실행
    chain = problem_prompt | llm | parser
    try:
        llm_response = chain.invoke({"keyword": keyword}, config={"callbacks": [langfuse_handler]})
        state = llm_response
        logging.info(f"[generate_problem]: {state}")
    except Exception as e:
        logging.error(f"[generate_problem] error: {e}")

    return state


# ----------------------------------------------------------------------
# 7) 테스트 실행
# ----------------------------------------------------------------------
if __name__ == "__main__":
    game_state = {}

    # 키워드 생성
    response_keywords = generate_keywords()
    logging.info("키워드 목록:", response_keywords.get("keywords"))

    # 문제 생성
    response_problem = generate_problem(response_keywords.get("keywords")[0])
    logging.info("문제 텍스트:", response_problem.get("right_text"))
    logging.info("오류 텍스트:", response_problem.get("wrong_text"))
    logging.info("오류 인덱스:", response_problem.get("wrong_indices"))
