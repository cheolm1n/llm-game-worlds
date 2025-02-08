# prompts.py 예시
from enum import Enum


class GameContentPrompts(Enum):
    KEYWORDS_PROMPT_SYSTEM = "너는 전문적인 어시스턴트야."
    KEYWORDS_PROMPT_HUMAN = (
        "지난 1주일간 IT, 과학, 스포츠, 경제 분야에서 화제가 된 키워드 3~5개를 JSON 배열로만 알려줘."
    )
    PROBLEM_PROMPT_SYSTEM = "너는 창의적인 작가야."
    PROBLEM_PROMPT_HUMAN = (
        "키워드 {keyword}에 대한 500자 이내의 문장과, 5개 단어에 오타를 삽입한 뒤, JSON으로 반환해."
    )
