from typing import List

from pydantic import BaseModel


class KeywordsResponse(BaseModel):
    keywords: List[str]


class ProblemResponse(BaseModel):
    text: str
    error_indices: List[int]
