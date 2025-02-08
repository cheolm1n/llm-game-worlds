import logging
import pygame
import sys
import json
import time
import random

from llm import generate_keywords, generate_problem

# 화면 크기
SCREEN_WIDTH = 720
SCREEN_HEIGHT = 1280
FPS = 30

# 게임 상태 정의
STATE_MAIN_MENU = 0
STATE_GAME = 1
STATE_RESULT = 2
STATE_LOADING = 3  # LLM 호출 로딩 화면

# 색상
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
LIGHT_GRAY = (220, 220, 220)
RED = (255, 0, 0)
PINK = (255, 200, 200)  # 선택된 블록 배경

# 폰트 경로 (임의)
FONT_PATH = "assets/Pretendard-Regular.otf"

# 상단/하단 레이아웃 높이
TOP_HEIGHT = 100
BOTTOM_HEIGHT = 150

class WordBlock:
    """
    문장 하나가 하나의 블록이 되며,
    화면 폭에 맞춰 줄바꿈한 텍스트를 여러 줄(lines)로 관리한다.
    - selected: 이 블록(문장)이 선택되었는지 여부
      선택된 블록은 PINK 배경이 표시됨.
    """
    def __init__(self, text, rect, index, lines):
        self.text = text
        self.lines = lines
        self.rect = rect
        self.index = index
        self.selected = False

    def draw(self, screen, font, offset=0):
        """
        offset(스크롤 위치)만큼 y 좌표를 위/아래로 이동하여 그린다.
        """
        draw_rect = self.rect.copy()
        draw_rect.y -= offset  # 스크롤 반영

        if self.selected:
            pygame.draw.rect(screen, PINK, draw_rect)

        line_height = font.get_linesize()
        x, y = draw_rect.x, draw_rect.y
        for line in self.lines:
            surf = font.render(line, True, BLACK)
            screen.blit(surf, (x, y))
            y += line_height

    def check_collision(self, pos, offset=0):
        """
        offset(스크롤 위치)을 반영하여 마우스 좌표와 충돌 검사.
        """
        shifted_rect = self.rect.copy()
        shifted_rect.y -= offset
        return shifted_rect.collidepoint(pos)


def wrap_text(sentence, font, max_width):
    """
    하나의 문장을 max_width에 맞춰 단어 단위로 줄바꿈 -> lines 리스트 반환
    """
    words = sentence.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        w, _ = font.size(test_line)
        if w <= max_width:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines


def create_word_blocks(sentences, font, content_rect):
    """
    문장들을 WordBlock으로 만들되,
    content 영역에 따라 y 좌표를 배치.
    """
    blocks = []
    x = 60  # 왼쪽 여백
    y = content_rect.top + 20  # content 상단 + 약간 여백
    max_width = content_rect.width - (x * 2)  # 좌우 여백을 고려한 폭
    line_spacing = 10

    for i, sentence in enumerate(sentences):
        lines = wrap_text(sentence, font, max_width)
        line_height = font.get_linesize()
        block_height = len(lines) * line_height

        rect = pygame.Rect(x, y, max_width, block_height)
        block = WordBlock(sentence, rect, i, lines)
        blocks.append(block)

        y += block_height + line_spacing

    return blocks


def get_total_content_height(blocks):
    """
    블록들의 전체 높이(마지막 블록의 bottom - content 영역 top)를 반환
    """
    if not blocks:
        return 0
    last_block = blocks[-1]
    # 블록의 실제 끝 - content의 시작
    return last_block.rect.bottom


def load_scores():
    try:
        with open("data/scores.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_scores(scores):
    with open("data/scores.json", "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("틀린 글 찾기 챌린지")
    clock = pygame.time.Clock()

    base_font = pygame.font.Font(FONT_PATH, 30)

    # BGM
    pygame.mixer.init()
    pygame.mixer.music.load("assets/bgm.mp3")

    # 레이아웃 사각형
    top_rect = pygame.Rect(0, 0, SCREEN_WIDTH, TOP_HEIGHT)
    bottom_rect = pygame.Rect(0, SCREEN_HEIGHT - BOTTOM_HEIGHT, SCREEN_WIDTH, BOTTOM_HEIGHT)
    content_rect = pygame.Rect(
        0,
        TOP_HEIGHT,
        SCREEN_WIDTH,
        SCREEN_HEIGHT - TOP_HEIGHT - BOTTOM_HEIGHT
    )

    # 상태
    game_state = STATE_LOADING
    load_type = "keywords"

    # 게임 변수
    selected_keyword = None
    error_indices = []
    word_blocks = []
    total_errors = 0
    scroll_offset = 0
    max_scroll = 0
    game_start_time = 0
    game_end_time = 0
    correct_count = 0

    # LLM 결과
    keywords = []
    data = None

    while True:
        clock.tick(FPS)

        # ──────────────────────────────────────────
        # 로딩 상태
        # ──────────────────────────────────────────
        if game_state == STATE_LOADING:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

            # 로딩 화면 표시
            screen.fill(WHITE)
            loading_surf = base_font.render("Loading...", True, BLACK)
            screen.blit(
                loading_surf,
                (SCREEN_WIDTH // 2 - loading_surf.get_width() // 2,
                 SCREEN_HEIGHT // 2)
            )
            pygame.display.update()

            try:
                if load_type == "keywords":
                    # 키워드 로딩
                    kw_data = generate_keywords()  # LLM 호출
                    keywords = kw_data.get("keywords", [])
                    game_state = STATE_MAIN_MENU

                elif load_type == "problem":
                    # 문제 생성 로딩
                    data = generate_problem(selected_keyword)
                    wrong_text = data.get("wrong_text", [])
                    right_text = data.get("right_text", [])
                    # 5개 틀린 문장 인덱스
                    error_indices = random.sample(range(len(wrong_text)), 5)
                    # 실제 플레이용 문장들
                    modified_list = right_text.copy()
                    for idx in error_indices:
                        modified_list[idx] = wrong_text[idx]

                    # 문장 블록 생성 (content 영역 기준)
                    word_blocks = create_word_blocks(modified_list, base_font, content_rect)
                    total_errors = len(error_indices)
                    correct_count = 0

                    # 스크롤 관련
                    scroll_offset = 0
                    total_height = get_total_content_height(word_blocks)
                    max_scroll = max(total_height - content_rect.height, 0)

                    game_start_time = time.time()
                    game_state = STATE_GAME

            except Exception as e:
                logging.error(f"Loading error: {e}")
                # 에러 시 임시로 메인 메뉴
                game_state = STATE_MAIN_MENU

        # ──────────────────────────────────────────
        # 메인 메뉴
        # ──────────────────────────────────────────
        elif game_state == STATE_MAIN_MENU:
            pygame.mixer.music.stop()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mouse_pos = pygame.mouse.get_pos()
                    btn_y = 250
                    # 키워드 버튼 클릭 확인
                    for kw in keywords:
                        rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, btn_y, 300, 60)
                        if rect.collidepoint(mouse_pos):
                            selected_keyword = kw
                            load_type = "problem"
                            game_state = STATE_LOADING
                            break
                        btn_y += 80

            # 메뉴 화면 그리기
            screen.fill(WHITE)

            title_surf = base_font.render("틀린 글 찾기 챌린지", True, BLACK)
            screen.blit(title_surf, (SCREEN_WIDTH // 2 - 150, 100))

            btn_y = 250
            for kw in keywords:
                rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, btn_y, 300, 60)
                pygame.draw.rect(screen, LIGHT_GRAY, rect)
                pygame.draw.rect(screen, BLACK, rect, 2)
                kw_surf = base_font.render(kw, True, BLACK)
                screen.blit(kw_surf, (rect.x + 20, rect.y + 10))
                btn_y += 80

            pygame.display.update()

        # ──────────────────────────────────────────
        # 게임 화면
        # ──────────────────────────────────────────
        elif game_state == STATE_GAME:
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(-1)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                elif event.type == pygame.MOUSEWHEEL:
                    # content 영역 안에서만 스크롤
                    mouse_x, mouse_y = pygame.mouse.get_pos()
                    if content_rect.collidepoint(mouse_x, mouse_y):
                        # event.y: 위로 양수, 아래로 음수
                        scroll_offset -= event.y * 30
                        if scroll_offset < 0:
                            scroll_offset = 0
                        if scroll_offset > max_scroll:
                            scroll_offset = max_scroll

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    # 왼쪽 버튼 클릭만 문장 선택/버튼 동작
                    if event.button == 1:
                        mouse_pos = pygame.mouse.get_pos()

                        # content 영역 클릭 시 문장 선택
                        if content_rect.collidepoint(mouse_pos):
                            for wb in word_blocks:
                                if wb.check_collision(mouse_pos, offset=scroll_offset):
                                    wb.selected = not wb.selected
                                    # 선택 개수 제한(5개)
                                    selected_count = sum(1 for b in word_blocks if b.selected)
                                    if selected_count > 5:
                                        # 가장 최근 클릭을 해제
                                        wb.selected = False
                                    break

                        # 상단의 "처음으로" 버튼
                        home_btn_rect = pygame.Rect(
                            SCREEN_WIDTH - 120, 20,
                            100, 40
                        )
                        if home_btn_rect.collidepoint(mouse_pos):
                            pygame.mixer.music.stop()
                            game_state = STATE_MAIN_MENU

                        # 하단의 "정답 제출" 버튼
                        submit_rect = pygame.Rect(
                            SCREEN_WIDTH // 2 - 150,
                            SCREEN_HEIGHT - BOTTOM_HEIGHT + 20,
                            300, 80
                        )
                        if submit_rect.collidepoint(mouse_pos):
                            selected_indices = [wb.index for wb in word_blocks if wb.selected]
                            correct_count = sum(1 for idx in selected_indices if idx in error_indices)
                            logging.info(f"selected_indices: {selected_indices}")
                            logging.info(f"error_indices: {error_indices}")
                            logging.info(f"correct_count: {correct_count}")

                            game_end_time = time.time()
                            game_state = STATE_RESULT

            # ────────────── 화면 그리기 ──────────────
            screen.fill(WHITE)

            # 1) 상단 영역 (타이머, "처음으로" 버튼)
            pygame.draw.rect(screen, LIGHT_GRAY, top_rect)
            pygame.draw.rect(screen, BLACK, top_rect, 2)

            elapsed_time = time.time() - game_start_time
            timer_surf = base_font.render(f"Time {elapsed_time:.1f}s", True, BLACK)
            screen.blit(timer_surf, (20, 30))

            home_btn_rect = pygame.Rect(SCREEN_WIDTH - 120, 20, 100, 40)
            pygame.draw.rect(screen, WHITE, home_btn_rect)
            pygame.draw.rect(screen, BLACK, home_btn_rect, 2)
            home_text = base_font.render("뒤로", True, BLACK)
            screen.blit(home_text, (home_btn_rect.x + 5, home_btn_rect.y + 5))

            # 2) content 영역 (문제/문장 블록)
            # 배경
            pygame.draw.rect(screen, WHITE, content_rect)
            # 경계선 표시
            pygame.draw.rect(screen, BLACK, content_rect, 2)

            # clip 설정 (content 영역 밖은 그리지 않음)
            prev_clip = screen.get_clip()
            screen.set_clip(content_rect)

            # 문장 블록 그리기
            for wb in word_blocks:
                wb.draw(screen, base_font, offset=scroll_offset)

            # clip 해제
            screen.set_clip(prev_clip)

            # 3) 하단 영역 (정답 제출 버튼)
            pygame.draw.rect(screen, LIGHT_GRAY, bottom_rect)
            pygame.draw.rect(screen, BLACK, bottom_rect, 2)

            submit_rect = pygame.Rect(
                SCREEN_WIDTH // 2 - 150,
                SCREEN_HEIGHT - BOTTOM_HEIGHT + 20,
                300, 80
            )
            pygame.draw.rect(screen, WHITE, submit_rect)
            pygame.draw.rect(screen, BLACK, submit_rect, 2)
            submit_text = base_font.render("정답 제출", True, BLACK)
            screen.blit(submit_text, (submit_rect.x + 60, submit_rect.y + 20))

            pygame.display.update()

        # ──────────────────────────────────────────
        # 결과 화면
        # ──────────────────────────────────────────
        elif game_state == STATE_RESULT:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mouse_pos = pygame.mouse.get_pos()

                    # 다시 시도 버튼(틀린 거 남아있을 때만)
                    retry_btn_rect = None
                    if correct_count < total_errors:
                        retry_btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, 550, 300, 80)
                        if retry_btn_rect.collidepoint(mouse_pos):
                            game_state = STATE_GAME

                    # 처음으로 버튼
                    home_btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, 700, 300, 80)
                    if home_btn_rect.collidepoint(mouse_pos):
                        game_state = STATE_MAIN_MENU

            screen.fill(WHITE)

            result_surf1 = base_font.render(
                f"오류 {total_errors}개 중 {correct_count}개 맞춤!",
                True,
                BLACK
            )
            screen.blit(result_surf1, (SCREEN_WIDTH // 2 - 150, 300))

            if correct_count == total_errors:
                final_time = game_end_time - game_start_time
                result_surf2 = base_font.render(
                    f"축하합니다! 소요 시간: {final_time:.1f}초",
                    True,
                    BLACK
                )
                screen.blit(result_surf2, (SCREEN_WIDTH // 2 - 200, 400))

                scores = load_scores()
                scores.append({
                    "keyword": selected_keyword,
                    "time": final_time,
                    "correct_count": correct_count,
                    "total_errors": total_errors
                })
                save_scores(scores)
            else:
                result_surf2 = base_font.render(
                    "아직 더 찾을 오류가 있습니다!",
                    True,
                    RED
                )
                screen.blit(result_surf2, (SCREEN_WIDTH // 2 - 170, 400))

            if correct_count < total_errors:
                retry_btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, 550, 300, 80)
                pygame.draw.rect(screen, LIGHT_GRAY, retry_btn_rect)
                pygame.draw.rect(screen, BLACK, retry_btn_rect, 3)
                retry_text = base_font.render("다시 시도", True, BLACK)
                screen.blit(retry_text, (retry_btn_rect.x + 60, retry_btn_rect.y + 20))

            home_btn_rect = pygame.Rect(SCREEN_WIDTH // 2 - 150, 700, 300, 80)
            pygame.draw.rect(screen, LIGHT_GRAY, home_btn_rect)
            pygame.draw.rect(screen, BLACK, home_btn_rect, 3)
            home_text = base_font.render("처음으로", True, BLACK)
            screen.blit(home_text, (home_btn_rect.x + 60, home_btn_rect.y + 20))

            pygame.display.update()


if __name__ == "__main__":
    main()
