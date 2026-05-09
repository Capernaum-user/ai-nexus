#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Manager GUI  —  중앙 관리자
Gemini(두뇌) + Claude(손) 자동 실행 채팅 인터페이스
"""

import tkinter as tk
from tkinter import font, filedialog
import subprocess
import threading
import os
import json
import re

# ── 경로 ─────────────────────────────────────────────────────
MANAGER_DIR        = r"D:\AI_Control\ai_manager"
MANAGER_PS1        = os.path.join(MANAGER_DIR, "manager.ps1")
STATE_FILE         = os.path.join(MANAGER_DIR, "STATE.json")
PLAN_FILE          = os.path.join(MANAGER_DIR, "PLAN.md")
QUEUE_FILE         = os.path.join(MANAGER_DIR, "TASK_QUEUE.json")
CLARIFY_QUEST_FILE = os.path.join(MANAGER_DIR, "CLARIFY_QUESTIONS.md")
CLARIFY_ANS_FILE   = os.path.join(MANAGER_DIR, "CLARIFICATIONS.md")
CONFIG_FILE        = os.path.join(MANAGER_DIR, "gui_config.json")
CONTEXT_FILE       = os.path.join(MANAGER_DIR, "CONTEXT.md")

# ── 파이프라인 단계 정의 ──────────────────────────────────────
PIPELINE = [
    "INTAKE", "CLARIFY", "RESEARCH", "DEEP_RESEARCH", "HALLCHECK",
    "PLAN", "PARALLEL_EXECUTE", "INTEGRATE", "CODEX_REVIEW",
    "GEMINI_CHECK", "CLAUDE_RECHECK", "INT_REVIEW", "FINISH",
]

# (상태명, 담당AI, 배지, 한국어설명, 짧은표시명)
PIPELINE_INFO = [
    ("INTAKE",           "gemini",  "Gem", "요청 분석 · 파악",   "INTAKE"),
    ("CLARIFY",          "gemini",  "Gem", "불명확 부분 질문",    "CLARIFY"),
    ("RESEARCH",         "gemini",  "Gem", "기술 스택 조사",      "RESEARCH"),
    ("DEEP_RESEARCH",    "gemini",  "Gem", "딥서치 · 외부조사",  "DEEP SRCH"),
    ("HALLCHECK",        "codex",   "Cox", "환각 검증",           "HALLCHECK"),
    ("PLAN",             "gemini",  "Gem", "작업 분해 · 계획",    "PLAN"),
    ("PARALLEL_EXECUTE", "manager", "Mgr", "병렬 실행 엔진",      "// EXEC"),
    ("INTEGRATE",        "claude",  "Cla", "통합 연결 검증",      "INTEGRATE"),
    ("CODEX_REVIEW",     "codex",   "Cox", "품질 · 보안 심사",   "CODE REV"),
    ("GEMINI_CHECK",     "gemini",  "Gem", "교차 검증",           "GEM CHK"),
    ("CLAUDE_RECHECK",   "claude",  "Cla", "최종 교차 검증",      "CLA CHK"),
    ("INT_REVIEW",       "gemini",  "Gem", "최종 판정",           "INT REV"),
    ("FINISH",           "manager", "Mgr", "보고서 저장",         "FINISH"),
]

# 에이전트별 스타일 (배지배경, 배지글자/테두리, 노드활성배경)
AGENT_STYLE = {
    "gemini":  ("#0d2a38", "#89dceb", "#0a1e2d"),
    "claude":  ("#0d2a1a", "#a6e3a1", "#0a1e12"),
    "codex":   ("#22103a", "#cba6f7", "#180d2d"),
    "manager": ("#352010", "#fab387", "#28180a"),
}

# ── 캔버스 노드 치수 (지그재그 2열 레이아웃) ────────────────
NODE_H      = 46     # 노드 높이 (공통)
ZZ_NODE_W   = 126    # 열당 노드 너비
ZZ_COL_GAP  = 14     # 두 열 사이 수평 간격
ZZ_ROW_GAP  = 24     # 행 간 수직 간격 (래핑 화살표 공간)
ZZ_PAD_X    = 5      # 좌우 여백
ZZ_PAD_TOP  = 10     # 상단 여백
ZZ_TOTAL_W  = ZZ_PAD_X * 2 + ZZ_NODE_W * 2 + ZZ_COL_GAP  # = 276

# ── 다크 테마 ─────────────────────────────────────────────────
BG_MAIN    = "#1e1e2e"
BG_DARK    = "#181825"
BG_TOP     = "#11111b"
BG_WS      = "#1a1a2e"
BG_ENTRY   = "#313244"
BG_CLARIFY = "#12122a"
BG_PANEL   = "#16162a"
BG_PHDR    = "#1a1a30"

FG_MAIN    = "#cdd6f4"
FG_GRAY    = "#585b70"
FG_BORDER  = "#45475a"
FG_USER    = "#89b4fa"
FG_GEMINI  = "#89dceb"
FG_CLAUDE  = "#a6e3a1"
FG_SYSTEM  = "#fab387"
FG_WARN    = "#f9e2af"
FG_ERR     = "#f38ba8"
FG_ACCENT  = "#cba6f7"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Manager")
        self.root.geometry("1300x800")
        self.root.configure(bg=BG_MAIN)
        self.root.minsize(900, 520)

        self.proc           = None
        self.clarify_mode   = False
        self.clarify_lines  = []
        self._last_spin     = ""

        self._plan_cache    = ""
        self._queue_cache   = ""
        self._state_cache   = ""

        # 위저드 (lazy build)
        self.wizard_frame   = None
        self.wz_goal        = None
        self.wz_notes       = None
        self.wz_proj_type   = None
        self.wz_quality     = None
        self.wz_env         = None
        self.wz_lang        = None
        self.wz_tech        = {}
        self.wz_output      = {}
        self.wz_err_lbl     = None
        self.wz_canvas      = None
        self.wz_canvas_win  = None

        self._build_fonts()
        self._build_ui()
        self._load_config()
        self._welcome()
        self._clear_activity()
        self._draw_pipeline_canvas("")   # 초기 빈 그래프

        self._poll_state()
        self._poll_clarify()
        self._poll_tasks()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 폰트 ─────────────────────────────────────────────────
    def _build_fonts(self):
        self.fn_mono        = font.Font(family="Consolas",     size=10)
        self.fn_dash        = font.Font(family="Consolas",     size=9)
        self.fn_dash_b      = font.Font(family="Consolas",     size=9,  weight="bold")
        self.fn_ui          = font.Font(family="Malgun Gothic", size=11)
        self.fn_small       = font.Font(family="Malgun Gothic", size=9)
        self.fn_bold        = font.Font(family="Malgun Gothic", size=10, weight="bold")
        self.fn_title       = font.Font(family="Malgun Gothic", size=10, weight="bold")
        # 캔버스 전용
        self.fn_cv_name     = font.Font(family="Consolas",     size=9,  weight="bold")
        self.fn_cv_desc     = font.Font(family="Malgun Gothic", size=8)
        self.fn_cv_badge    = font.Font(family="Consolas",     size=8,  weight="bold")
        self.fn_cv_num      = font.Font(family="Consolas",     size=8)

    # ══════════════════════════════════════════════════════════
    # UI 구성
    # ══════════════════════════════════════════════════════════
    def _build_ui(self):

        # ── 1. 상태 바 ────────────────────────────────────────
        topbar = tk.Frame(self.root, bg=BG_TOP, height=40)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self.dot = tk.Label(topbar, text="●", fg=FG_GRAY, bg=BG_TOP,
                            font=("Consolas", 14))
        self.dot.pack(side="left", padx=(12, 3), pady=6)

        self.lbl_status = tk.Label(topbar, text="준비", fg=FG_GRAY, bg=BG_TOP,
                                    font=self.fn_small)
        self.lbl_status.pack(side="left", pady=6)

        tk.Label(topbar, text="  AI Manager", fg=FG_MAIN, bg=BG_TOP,
                 font=self.fn_title).pack(side="left", pady=6)

        tk.Button(topbar, text="✦ 새 프로젝트", command=self._force_new,
                  bg="#313244", fg=FG_SYSTEM, activebackground="#45475a",
                  activeforeground=FG_SYSTEM, relief="flat",
                  font=self.fn_small, padx=10, pady=4,
                  cursor="hand2", bd=0).pack(side="right", padx=4, pady=6)

        # ── 2. 작업 폴더 바 ───────────────────────────────────
        wsbar = tk.Frame(self.root, bg=BG_WS, height=36)
        wsbar.pack(fill="x")
        wsbar.pack_propagate(False)

        tk.Label(wsbar, text="📁 작업 폴더", fg=FG_GEMINI, bg=BG_WS,
                 font=self.fn_small).pack(side="left", padx=(12, 6), pady=8)

        self.ws_var = tk.StringVar()
        self.ws_entry = tk.Entry(
            wsbar, textvariable=self.ws_var,
            bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_small, relief="flat",
            insertbackground=FG_MAIN, highlightthickness=1,
            highlightbackground=FG_BORDER, highlightcolor=FG_GEMINI,
        )
        self.ws_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        self.ws_entry.bind("<FocusOut>", lambda _: self._save_config())

        tk.Button(wsbar, text="📂 선택", command=self._browse_ws,
                  bg="#313244", fg=FG_GEMINI, activebackground="#45475a",
                  activeforeground=FG_GEMINI, relief="flat",
                  font=self.fn_small, padx=10, pady=4,
                  cursor="hand2", bd=0).pack(side="right", padx=(0, 10), pady=5)

        self.lbl_ws_hint = tk.Label(wsbar, text="미지정 시 ai_manager/workspace/ 사용",
                                     fg=FG_GRAY, bg=BG_WS, font=self.fn_small)
        self.lbl_ws_hint.pack(side="right", padx=6)

        # ── 3. 메인 영역 ──────────────────────────────────────
        main_area = tk.Frame(self.root, bg=BG_MAIN)
        main_area.pack(fill="both", expand=True)

        # ── 3-A. 채팅 출력 (좌) ───────────────────────────────
        chat_outer = tk.Frame(main_area, bg=BG_MAIN)
        chat_outer.pack(side="left", fill="both", expand=True)

        self.chat = tk.Text(
            chat_outer, bg=BG_MAIN, fg=FG_MAIN, font=self.fn_mono,
            relief="flat", wrap="word", state="disabled",
            padx=16, pady=10, selectbackground="#45475a",
            cursor="arrow", spacing1=1, spacing3=1,
        )
        csb = tk.Scrollbar(chat_outer, command=self.chat.yview,
                            bg=BG_MAIN, troughcolor=BG_MAIN,
                            activebackground=FG_BORDER, width=10)
        self.chat.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)

        for name, color in {
            "user": FG_USER, "gemini": FG_GEMINI, "claude": FG_CLAUDE,
            "system": FG_SYSTEM, "warn": FG_WARN, "error": FG_ERR,
            "accent": FG_ACCENT, "gray": FG_GRAY, "main": FG_MAIN,
        }.items():
            self.chat.tag_configure(name, foreground=color)
        self.chat.tag_configure("bold_gemini", foreground=FG_GEMINI,
            font=font.Font(family="Consolas", size=10, weight="bold"))
        self.chat.tag_configure("bold_system", foreground=FG_SYSTEM,
            font=font.Font(family="Consolas", size=10, weight="bold"))

        # ── 구분선 ────────────────────────────────────────────
        tk.Frame(main_area, bg=FG_BORDER, width=1).pack(side="left", fill="y")

        # ── 3-B. 우측 대시보드 ────────────────────────────────
        self._build_dashboard(main_area)

        # ── 4. CLARIFY 패널 (숨김) ────────────────────────────
        self.clarify_frame = tk.Frame(self.root, bg=BG_CLARIFY, pady=6)

        tk.Label(self.clarify_frame,
                 text="  Gemini 질문  —  번호별로 답변 후 빈 줄(Enter)로 완료",
                 fg=FG_GEMINI, bg=BG_CLARIFY,
                 font=self.fn_bold).pack(anchor="w", padx=10, pady=(4, 2))

        clarify_q_wrap = tk.Frame(self.clarify_frame, bg=BG_CLARIFY)
        clarify_q_wrap.pack(fill="x", padx=10, pady=(0, 4))

        self.clarify_q = tk.Text(
            clarify_q_wrap, bg="#12122e", fg=FG_GEMINI,
            font=self.fn_mono, height=14, state="disabled",
            relief="flat", padx=10, pady=8, wrap="word",
        )
        clarify_sb = tk.Scrollbar(clarify_q_wrap, command=self.clarify_q.yview,
                                   bg=BG_CLARIFY, troughcolor=BG_CLARIFY, width=8)
        self.clarify_q.configure(yscrollcommand=clarify_sb.set)
        clarify_sb.pack(side="right", fill="y")
        self.clarify_q.pack(side="left", fill="x", expand=True)

        # ── 5. 입력 영역 ──────────────────────────────────────
        input_outer = tk.Frame(self.root, bg=BG_DARK, pady=8)
        input_outer.pack(fill="x", side="bottom")

        self.lbl_hint = tk.Label(
            input_outer,
            text="목표를 입력하면 새 프로젝트를 시작합니다  (Enter로 전송)",
            fg=FG_GRAY, bg=BG_DARK, font=self.fn_small,
        )
        self.lbl_hint.pack(anchor="w", padx=14, pady=(0, 4))

        row = tk.Frame(input_outer, bg=BG_DARK)
        row.pack(fill="x", padx=8)

        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(
            row, textvariable=self.entry_var,
            bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_ui, relief="flat",
            insertbackground=FG_MAIN, highlightthickness=1,
            highlightbackground=FG_BORDER, highlightcolor=FG_GEMINI,
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(4, 8))
        self.entry.bind("<Return>", lambda _: self._send())
        self.entry.focus()

        self.btn_send = tk.Button(
            row, text="전송", command=self._send,
            bg=FG_GEMINI, fg=BG_MAIN, font=self.fn_bold,
            relief="flat", padx=20, pady=9,
            cursor="hand2", activebackground="#74c7ec", activeforeground=BG_MAIN,
        )
        self.btn_send.pack(side="right", padx=4)

    # ══════════════════════════════════════════════════════════
    # 우측 대시보드
    # ══════════════════════════════════════════════════════════
    def _build_dashboard(self, parent):
        panel = tk.Frame(parent, bg=BG_PANEL, width=308)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)

        def section_hdr(text, color=FG_SYSTEM):
            hdr = tk.Frame(panel, bg=BG_PHDR, height=26)
            hdr.pack(fill="x")
            hdr.pack_propagate(False)
            lbl = tk.Label(hdr, text=f"  {text}", fg=color, bg=BG_PHDR,
                           font=self.fn_dash_b)
            lbl.pack(side="left", pady=3)
            return lbl

        # ── A. 파이프라인 플로우차트 (Canvas) ────────────────
        self.pipe_hdr_lbl = section_hdr("🔄 파이프라인  0 / 14")

        pipe_wrap = tk.Frame(panel, bg=BG_PANEL)
        pipe_wrap.pack(fill="x")

        self.pipe_canvas = tk.Canvas(
            pipe_wrap, bg=BG_PANEL, bd=0, highlightthickness=0,
            height=345, width=292,
        )
        pipe_csb = tk.Scrollbar(pipe_wrap, orient="vertical",
                                command=self.pipe_canvas.yview,
                                bg=BG_PANEL, troughcolor=BG_PANEL,
                                activebackground=FG_BORDER, width=8)
        self.pipe_canvas.configure(yscrollcommand=pipe_csb.set)
        pipe_csb.pack(side="right", fill="y")
        self.pipe_canvas.pack(side="left", fill="both", expand=True)

        # 마우스 휠 스크롤
        self.pipe_canvas.bind(
            "<MouseWheel>",
            lambda e: self.pipe_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # ── 재개 / 중지 버튼 ──────────────────────────────────
        btn_row = tk.Frame(panel, bg=BG_PANEL, pady=6)
        btn_row.pack(fill="x", padx=8)

        self.btn_resume = tk.Button(
            btn_row, text="▶  재개", command=self._resume,
            bg="#1a3a20", fg=FG_CLAUDE,
            activebackground="#2a5a30", activeforeground=FG_CLAUDE,
            relief="flat", font=self.fn_bold, padx=0, pady=7,
            cursor="hand2", bd=0,
        )
        self.btn_resume.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop = tk.Button(
            btn_row, text="■  중지", command=self._stop,
            bg="#3a1a1a", fg=FG_ERR,
            activebackground="#5a2828", activeforeground=FG_ERR,
            relief="flat", font=self.fn_bold, padx=0, pady=7,
            cursor="hand2", bd=0,
        )
        self.btn_stop.pack(side="right", fill="x", expand=True, padx=(4, 0))

        # ── B. 처리 중 (스피너) ───────────────────────────────
        section_hdr("⚡ 처리 중", FG_WARN)
        self.activity_box = tk.Text(
            panel, bg=BG_PANEL, font=self.fn_dash,
            height=2, state="disabled", relief="flat",
            wrap="word", padx=8, pady=5,
        )
        self.activity_box.pack(fill="x")
        for n, c in [
            ("idle",   FG_GRAY), ("ag_gem", FG_GEMINI),
            ("ag_cla", FG_CLAUDE), ("ag_cod", FG_ACCENT),
            ("bar_af", FG_WARN), ("bar_ae", FG_GRAY),
            ("sec",    FG_SYSTEM), ("spin_c", FG_WARN),
        ]:
            self.activity_box.tag_configure(n, foreground=c)

        # ── C. 계획 요약 ──────────────────────────────────────
        section_hdr("📋 계획 요약")
        self.plan_box = tk.Text(
            panel, bg=BG_PANEL, fg=FG_GRAY, font=self.fn_dash,
            height=5, state="disabled", relief="flat",
            wrap="word", padx=8, pady=5,
        )
        self.plan_box.pack(fill="x")

        # ── D. 작업 현황 ──────────────────────────────────────
        self.task_hdr_lbl = section_hdr("📊 작업 현황")

        task_wrap = tk.Frame(panel, bg=BG_PANEL)
        task_wrap.pack(fill="both", expand=True)

        self.task_box = tk.Text(
            task_wrap, bg=BG_PANEL, fg=FG_MAIN, font=self.fn_dash,
            state="disabled", relief="flat", wrap="word", padx=6, pady=4,
        )
        tsb = tk.Scrollbar(task_wrap, command=self.task_box.yview,
                            bg=BG_PANEL, troughcolor=BG_PANEL, width=8)
        self.task_box.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.task_box.pack(side="left", fill="both", expand=True)

        for n, c in [
            ("in_prog",   FG_WARN),  ("done_t",    FG_CLAUDE),
            ("pending_t", FG_GRAY),  ("failed_t",  FG_ERR),
            ("gem_tag",   FG_GEMINI),("cla_tag",   FG_CLAUDE),
            ("cod_tag",   FG_ACCENT),("hdr_t",     FG_SYSTEM),
        ]:
            self.task_box.tag_configure(n, foreground=c)
        self.task_box.tag_configure(
            "bold_t", font=font.Font(family="Consolas", size=9, weight="bold"))

    # ══════════════════════════════════════════════════════════
    # 파이프라인 캔버스 그리기 (지그재그 2열 레이아웃)
    # ══════════════════════════════════════════════════════════
    def _draw_pipeline_canvas(self, current: str):
        c = self.pipe_canvas
        c.delete("all")

        try:
            cur_idx = PIPELINE.index(current)
        except ValueError:
            cur_idx = -1

        n      = len(PIPELINE_INFO)
        n_rows = (n + 1) // 2
        total_h = ZZ_PAD_TOP * 2 + n_rows * NODE_H + (n_rows - 1) * ZZ_ROW_GAP
        c.configure(scrollregion=(0, 0, ZZ_TOTAL_W, total_h))

        # 열 x 좌표
        lx0 = ZZ_PAD_X                           # 왼쪽 열 왼쪽
        lx1 = lx0 + ZZ_NODE_W                    # 왼쪽 열 오른쪽
        rx0 = lx1 + ZZ_COL_GAP                   # 오른쪽 열 왼쪽
        rx1 = rx0 + ZZ_NODE_W                    # 오른쪽 열 오른쪽

        # 상태별 스타일 반환
        def get_style(idx, agent):
            badge_bg, accent, node_act_bg = AGENT_STYLE[agent]
            if cur_idx < 0 or idx > cur_idx:
                return dict(state="pending",
                            node_fill="#0f1020", node_outline="#252535",
                            name_col="#3a3a58", desc_col="#2e2e48",
                            badge_fill="#141428", badge_out="#252535",
                            badge_col="#3a3a58", num_col="#2e2e48",
                            accent=accent, arr_col="#303048")
            elif idx < cur_idx:
                return dict(state="done",
                            node_fill="#0c1510", node_outline="#2a3a2a",
                            name_col="#3a6a3a", desc_col="#2e4e2e",
                            badge_fill=badge_bg, badge_out="#3a5a3a",
                            badge_col="#4a8a4a", num_col="#3a6a3a",
                            accent=accent, arr_col="#3a6a3a")
            else:  # current
                return dict(state="current",
                            node_fill=node_act_bg, node_outline=accent,
                            name_col=accent, desc_col=FG_MAIN,
                            badge_fill=badge_bg, badge_out=accent,
                            badge_col=accent, num_col=accent,
                            accent=accent, arr_col=FG_WARN)

        # ── 1단계: 화살표 먼저 그리기 (노드 아래에 위치) ──────
        for i, (name, agent, badge_txt, desc, short_name) in enumerate(PIPELINE_INFO):
            if i >= n - 1:
                break
            row = i // 2
            col = i % 2
            y_row = ZZ_PAD_TOP + row * (NODE_H + ZZ_ROW_GAP)
            sty   = get_style(i, agent)

            if col == 0:
                # 수평 화살표: 왼쪽 열 → 오른쪽 열 (같은 행)
                y_mid = y_row + NODE_H // 2
                c.create_line(lx1, y_mid, rx0, y_mid,
                              fill=sty["arr_col"], width=1,
                              arrow="last", arrowshape=(6, 8, 3))
            else:
                # 래핑 화살표: 오른쪽 열 하단 → L자 → 다음 행 왼쪽 열 상단
                x_r_mid  = rx0 + ZZ_NODE_W // 2
                x_l_mid  = lx0 + ZZ_NODE_W // 2
                y_bot    = y_row + NODE_H
                y_turn   = y_bot + ZZ_ROW_GAP // 2
                y_next   = y_bot + ZZ_ROW_GAP
                c.create_line(x_r_mid, y_bot,
                              x_r_mid, y_turn,
                              x_l_mid, y_turn,
                              x_l_mid, y_next,
                              fill=sty["arr_col"], width=1,
                              arrow="last", arrowshape=(6, 8, 3))

        # ── 2단계: 노드 그리기 ─────────────────────────────────
        for i, (name, agent, badge_txt, desc, short_name) in enumerate(PIPELINE_INFO):
            row  = i // 2
            col  = i % 2
            y0   = ZZ_PAD_TOP + row * (NODE_H + ZZ_ROW_GAP)
            y1   = y0 + NODE_H
            x0   = lx0 if col == 0 else rx0
            x1   = lx1 if col == 0 else rx1
            sty  = get_style(i, agent)
            state = sty["state"]

            outline_w = 2 if state == "current" else 1
            c.create_rectangle(x0, y0, x1, y1,
                               fill=sty["node_fill"], outline=sty["node_outline"],
                               width=outline_w)

            if state == "current":
                c.create_rectangle(x0, y0, x0 + 3, y1,
                                   fill=sty["accent"], outline=sty["accent"])

            # 에이전트 배지
            bx0, bx1 = x0 + 4, x0 + 26
            by0, by1 = y0 + 8, y1 - 8
            c.create_rectangle(bx0, by0, bx1, by1,
                               fill=sty["badge_fill"], outline=sty["badge_out"], width=1)
            c.create_text((bx0 + bx1) // 2, (by0 + by1) // 2,
                          text=badge_txt, fill=sty["badge_col"],
                          font=self.fn_cv_badge, anchor="center")

            # 짧은 단계명
            c.create_text(x0 + 30, y0 + 7,
                          text=short_name, fill=sty["name_col"],
                          font=self.fn_cv_name, anchor="nw")

            # 설명 (짧게)
            c.create_text(x0 + 30, y0 + 25,
                          text=desc, fill=sty["desc_col"],
                          font=self.fn_cv_desc, anchor="nw")

            # 번호 / 완료 아이콘
            if state == "done":
                c.create_text(x1 - 4, y0 + 7,
                              text="✓", fill="#4a8a4a",
                              font=self.fn_cv_name, anchor="ne")
            else:
                c.create_text(x1 - 4, y0 + 7,
                              text=f"{i + 1:02d}", fill=sty["num_col"],
                              font=self.fn_cv_num, anchor="ne")

            # PARALLEL_EXECUTE: 루프 힌트
            if name == "PARALLEL_EXECUTE":
                c.create_text(x1 - 4, y1 - 8,
                              text="↻", fill="#585b70",
                              font=self.fn_cv_num, anchor="ne")

        # 자동 스크롤: 현재 단계를 화면 중앙으로
        if cur_idx >= 0 and total_h > 0:
            row_cur  = cur_idx // 2
            y_mid_cur = ZZ_PAD_TOP + row_cur * (NODE_H + ZZ_ROW_GAP) + NODE_H // 2
            frac = max(0.0, (y_mid_cur - 120) / total_h)
            c.yview_moveto(frac)

    # ── 파이프라인 캔버스 업데이트 ────────────────────────────
    def _update_pipeline_canvas(self):
        st  = self._get_state()
        sig = json.dumps(st) if st else ""
        if sig == self._state_cache:
            return
        self._state_cache = sig

        current = st.get("status", "") if st else ""
        self._draw_pipeline_canvas(current)

        try:
            idx = PIPELINE.index(current)
        except ValueError:
            idx = 0
        pct = int(idx / len(PIPELINE) * 100)
        label = f"  🔄 파이프라인  {idx} / {len(PIPELINE)}  ({pct}%)"
        if st and st.get("is_complete"):
            label = f"  🔄 파이프라인  완료 ✓"
        self.pipe_hdr_lbl.configure(text=label)

    # ══════════════════════════════════════════════════════════
    # 설정 저장/불러오기
    # ══════════════════════════════════════════════════════════
    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ws = cfg.get("last_workspace", "")
            self.ws_var.set(ws)
            if ws:
                self.lbl_ws_hint.configure(text="")
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_workspace": self.ws_var.get()},
                          f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _browse_ws(self):
        init = self.ws_var.get() or MANAGER_DIR
        path = filedialog.askdirectory(title="작업 폴더 선택", initialdir=init)
        if path:
            path = os.path.normpath(path)
            self.ws_var.set(path)
            self.lbl_ws_hint.configure(text="")
            self._save_config()
            self._append(f"\n  📁 작업 폴더 설정: {path}\n", "system")

    # ══════════════════════════════════════════════════════════
    # 채팅 출력
    # ══════════════════════════════════════════════════════════
    def _append(self, text, tag="gray"):
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _classify(self, raw: str):
        line = re.sub(r"\x1b\[[0-9;?]*[mGKHFJl]", "", raw)
        line = line.replace("\r", "").rstrip()
        if not line:
            return None, None
        lo = line.lower()

        if "__SPINNER__:" in line:
            m = re.search(r"__SPINNER__:(\w+):(\d+):(\d+):(.)", line)
            if m:
                return f"{m.group(1)}:{m.group(2)}:{m.group(3)}:{m.group(4)}", "__spinner__"
            return None, None

        if "[gemini]" in lo:                                    return line, "gemini"
        if "[claude]" in lo:                                    return line, "claude"
        if "[codex]"  in lo:                                    return line, "accent"
        if "[error]"  in lo or "failed" in lo or "오류:" in lo: return line, "error"
        if "[warn]"   in lo or "경고" in lo:                   return line, "warn"
        if "━━" in line or "===" in line:                      return line, "system"
        if "[info]"   in lo:                                    return line, "gray"
        return line, "main"

    def _welcome(self):
        self._append("━" * 62 + "\n", "gray")
        self._append("  AI Manager  ·  Gemini(두뇌) + Claude(손)\n", "bold_system")
        self._append("━" * 62 + "\n\n", "gray")
        self._append("  ① 위의 📁 작업 폴더를 먼저 선택하세요.\n", "gray")
        self._append("  ② 목표를 입력하면 AI들이 그 폴더 안에서 작업합니다.\n\n", "gray")
        self._append("  우측 패널 — 파이프라인 플로우차트 · 계획 · 작업 현황\n\n", "gray")

    # ══════════════════════════════════════════════════════════
    # 폴링
    # ══════════════════════════════════════════════════════════
    def _get_state(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _poll_state(self):
        st      = self._get_state()
        running = self.proc is not None and self.proc.poll() is None

        if running:
            self.dot.configure(fg=FG_CLAUDE)
            status = f"실행 중 — {st['status'] if st else '?'}"
        elif st:
            done   = st.get("is_complete", False)
            self.dot.configure(fg=FG_CLAUDE if done else FG_SYSTEM)
            status = f"{'완료' if done else '대기'} — {st.get('status','?')}"
        else:
            self.dot.configure(fg=FG_GRAY)
            status = "준비"

        self.lbl_status.configure(text=status)

        if self.clarify_mode:
            hint = "Gemini 질문에 답변 중 · 빈 줄(Enter)로 완료"
        elif running:
            hint = "AI 실행 중 · ■ 중지로 중단 가능"
        elif st and not st.get("is_complete") and st.get("status") not in ("FINISH","FAILED",None):
            hint = "진행 중 프로젝트 있음 · 수정 지시 입력  또는  ▶ 재개"
        else:
            hint = "목표를 입력하면 새 프로젝트를 시작합니다  (Enter로 전송)"
        self.lbl_hint.configure(text=hint)

        ws = self.ws_var.get().strip()
        if ws:
            self.ws_entry.configure(fg=FG_MAIN if os.path.isdir(ws) else FG_WARN)

        self.root.after(2000, self._poll_state)

    def _poll_clarify(self):
        exists = os.path.exists(CLARIFY_QUEST_FILE)
        if exists and not self.clarify_mode:
            self._show_clarify()
        elif not exists and self.clarify_mode:
            self._hide_clarify()
        self.root.after(800, self._poll_clarify)

    def _show_clarify(self):
        self.clarify_mode  = True
        self.clarify_lines = []
        try:
            with open(CLARIFY_QUEST_FILE, "r", encoding="utf-8") as f:
                q = f.read()
        except Exception:
            q = "(질문을 읽지 못했습니다)"

        self.clarify_q.configure(state="normal")
        self.clarify_q.delete("1.0", "end")
        self.clarify_q.insert("end", q)
        self.clarify_q.configure(state="disabled")
        self.clarify_frame.pack(fill="x", before=self.entry.master.master)

        self._append("\n", "gray")
        self._append("  ┌─ Gemini 질문 ─────────────────────────────────────────┐\n", "bold_gemini")
        for ln in q.strip().splitlines():
            self._append(f"  │  {ln}\n", "gemini")
        self._append("  └─ 번호별로 답변 후 빈 줄(Enter)로 완료 ───────────────────┘\n\n", "bold_gemini")

    def _ensure_clarify_shown(self):
        """subprocess 출력에서 CLARIFY 신호 감지 시 즉시 패널 표시"""
        if os.path.exists(CLARIFY_QUEST_FILE) and not self.clarify_mode:
            self._show_clarify()

    def _hide_clarify(self):
        self.clarify_mode = False
        try:
            self.clarify_frame.pack_forget()
        except Exception:
            pass

    def _submit_clarify(self, text: str):
        if text == "":
            content = "\n".join(self.clarify_lines)
            try:
                with open(CLARIFY_ANS_FILE, "w", encoding="utf-8") as f:
                    f.write(content)
                self._append("  ✓ 답변 전송 완료 — AI가 계속 진행합니다.\n\n", "system")
            except Exception as e:
                self._append(f"  ✗ 파일 쓰기 실패: {e}\n", "error")
        else:
            self.clarify_lines.append(text)
            self._append(f"  → {text}\n", "user")

    # ══════════════════════════════════════════════════════════
    # 대시보드 업데이트 (3초 폴링)
    # ══════════════════════════════════════════════════════════
    def _poll_tasks(self):
        try:
            self._update_pipeline_canvas()
            self._update_plan()
            self._update_tasks()
        except Exception:
            pass
        self.root.after(3000, self._poll_tasks)

    def _update_plan(self):
        if not os.path.exists(PLAN_FILE):
            sig = ""
        else:
            sig = str(os.path.getmtime(PLAN_FILE))
        if sig == self._plan_cache:
            return
        self._plan_cache = sig

        self.plan_box.configure(state="normal")
        self.plan_box.delete("1.0", "end")

        if not os.path.exists(PLAN_FILE):
            self.plan_box.insert("end", "(계획 수립 전)", "pending_t")
            self.plan_box.configure(state="disabled")
            return

        with open(PLAN_FILE, "r", encoding="utf-8") as f:
            raw = f.read()

        summary_lines = []
        for line in raw.splitlines():
            if re.match(r"^##?\s*(작업|TASK|task)", line, re.I):
                break
            clean = re.sub(r"^#+\s*", "", line).strip()
            if clean:
                summary_lines.append(clean)

        summary = "\n".join(summary_lines).strip()
        if not summary:
            summary = raw.strip()
        if len(summary) > 420:
            summary = summary[:417] + "…"

        self.plan_box.insert("end", summary)
        self.plan_box.configure(state="disabled", fg=FG_MAIN)

    def _update_tasks(self):
        if not os.path.exists(QUEUE_FILE):
            sig = ""
        else:
            sig = str(os.path.getmtime(QUEUE_FILE))
        if sig == self._queue_cache:
            return
        self._queue_cache = sig

        self.task_box.configure(state="normal")
        self.task_box.delete("1.0", "end")

        if not os.path.exists(QUEUE_FILE):
            self.task_box.insert("end", "(작업 큐 없음)", "pending_t")
            self.task_box.configure(state="disabled")
            self.task_hdr_lbl.configure(text="  📊 작업 현황")
            return

        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        tasks = data.get("tasks", [])
        if not tasks:
            self.task_box.insert("end", "(작업 없음)", "pending_t")
            self.task_box.configure(state="disabled")
            self.task_hdr_lbl.configure(text="  📊 작업 현황")
            return

        counts = {}
        for t in tasks:
            s = t.get("status", "pending")
            counts[s] = counts.get(s, 0) + 1

        done  = counts.get("done", 0)
        total = len(tasks)
        self.task_hdr_lbl.configure(text=f"  📊 작업 현황  {done}/{total} 완료")

        STATUS_ORDER = [
            ("in_progress", "⚡ 진행 중",  "in_prog"),
            ("failed",      "❌ 실패",     "failed_t"),
            ("pending",     "⏳ 대기",     "pending_t"),
            ("done",        "✅ 완료",     "done_t"),
        ]
        AGENT_TAG = {
            "gemini": ("gem_tag", "Gem"),
            "claude": ("cla_tag", "Cla"),
            "codex":  ("cod_tag", "Cox"),
        }

        for status_key, label, text_tag in STATUS_ORDER:
            group = [t for t in tasks if t.get("status", "pending") == status_key]
            if not group:
                continue
            self.task_box.insert("end", f"{label} ({len(group)})\n", ("hdr_t", "bold_t"))
            for t in group:
                agent = t.get("agent", "claude").lower()
                a_tag, a_short = AGENT_TAG.get(
                    next((k for k in AGENT_TAG if k in agent), "claude"),
                    ("cla_tag", "Cla"),
                )
                tid   = t.get("id", "?")
                title = t.get("title", "?")
                if len(title) > 26:
                    title = title[:24] + "…"
                self.task_box.insert("end", f"  [{a_short}] ", (a_tag,))
                self.task_box.insert("end", f"{tid} ", "pending_t")
                self.task_box.insert("end", f"{title}\n", (text_tag,))
            self.task_box.insert("end", "\n")

        self.task_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════
    # 입력 / 버튼
    # ══════════════════════════════════════════════════════════
    def _send(self):
        text = self.entry_var.get().strip()
        self.entry_var.set("")

        if self.clarify_mode:
            self._submit_clarify(text)
            return

        if self.proc is not None and self.proc.poll() is None:
            self._append("\n  [!] 실행 중입니다. ■ 중지 후 시도하세요.\n", "warn")
            return

        st = self._get_state()

        if text == "":
            if st and not st.get("is_complete"):
                self._resume()
            return

        ws = self.ws_var.get().strip()
        if not ws:
            self._append("\n  ⚠ 작업 폴더 미지정 — 기본 workspace/ 폴더를 사용합니다.\n", "warn")

        self._append(f"\n  ▶ {text}\n", "user")

        has_active = (
            st is not None
            and not st.get("is_complete", False)
            and st.get("status") not in ("FINISH", "FAILED")
        )
        self._run(["-Revise", text, "-Auto", "-GUI"] if has_active
                  else ["-Goal",  text, "-Auto", "-GUI"])

    def _resume(self):
        if self.proc and self.proc.poll() is None:
            self._append("\n  [!] 이미 실행 중입니다.\n", "warn")
            return
        self._append("\n  ▶ 재개\n", "user")
        self._run(["-Resume", "-Auto", "-GUI"])

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append("\n  ■ 중지 요청됨\n", "warn")

    def _force_new(self):
        self._show_wizard()

    # ══════════════════════════════════════════════════════════
    # 의도 파악 위저드
    # ══════════════════════════════════════════════════════════
    def _show_wizard(self):
        if self.wizard_frame is None:
            self._build_wizard_panel()
        # 필드 초기화
        self.wz_goal.delete("1.0", "end")
        self.wz_notes.delete("1.0", "end")
        self.wz_err_lbl.configure(text="")
        self.wz_proj_type.set("AI가 판단")
        self.wz_quality.set("균형")
        self.wz_env.set("AI가 결정")
        self.wz_lang.set("한국어 주석 + 한국어 문서")
        for v in self.wz_tech.values():
            v.set(False)
        for v in self.wz_output.values():
            v.set(False)
        self.wz_canvas.yview_moveto(0)
        self.wizard_frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.wizard_frame.lift()
        self.wz_goal.focus()

    def _hide_wizard(self):
        if self.wizard_frame:
            self.wizard_frame.place_forget()

    def _wizard_submit(self):
        goal = self.wz_goal.get("1.0", "end").strip()
        if not goal:
            self.wz_err_lbl.configure(text="⚠  목표를 입력해주세요.")
            self.wz_goal.focus()
            return
        self.wz_err_lbl.configure(text="")
        # CONTEXT.md 작성
        try:
            ctx = self._compile_context(goal)
            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                f.write(ctx)
        except Exception as e:
            self.wz_err_lbl.configure(text=f"⚠  저장 오류: {e}")
            return
        # 기존 프로젝트 완료 처리
        st = self._get_state()
        if st:
            try:
                st["is_complete"] = True
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False)
            except Exception:
                pass
        self._hide_wizard()
        short = goal[:70] + "..." if len(goal) > 70 else goal
        self._append(f"\n  ▶ {short}\n", "user")
        self._run(["-Goal", goal, "-Auto", "-GUI"])

    def _compile_context(self, goal: str) -> str:
        parts = [
            "# 프로젝트 컨텍스트 (사용자 사전 설정)",
            "이 문서는 사용자가 프로젝트 시작 전에 입력한 상세 컨텍스트입니다.",
            "CLARIFY 단계에서 이 문서에 이미 답된 항목은 절대 다시 묻지 마십시오.",
            "이 문서에 없는 항목만 필요 시 질문하십시오.\n",
        ]
        pt = self.wz_proj_type.get()
        if pt and pt != "AI가 판단":
            parts.append(f"## 프로젝트 유형\n{pt}")
        tech = [k for k, v in self.wz_tech.items() if v.get() and k != "AI가 선택"]
        if tech:
            parts.append("## 선호 기술 스택\n" + "\n".join(f"- {t}" for t in tech))
        outs = [k for k, v in self.wz_output.items() if v.get()]
        if outs:
            parts.append("## 결과물 형태\n" + "\n".join(f"- {o}" for o in outs))
        q = self.wz_quality.get()
        if q:
            parts.append(f"## 품질 수준\n{q}")
        env = self.wz_env.get()
        if env and env != "AI가 결정":
            parts.append(f"## 실행/배포 환경\n{env}")
        lang = self.wz_lang.get()
        if lang:
            parts.append(f"## 언어 설정\n{lang}")
        notes = self.wz_notes.get("1.0", "end").strip()
        if notes:
            parts.append(f"## 추가 제약사항\n{notes}")
        return "\n\n".join(parts)

    def _build_wizard_panel(self):
        self.wizard_frame = tk.Frame(self.root, bg=BG_DARK)

        # ── 헤더 ────────────────────────────────────────────
        hdr = tk.Frame(self.wizard_frame, bg=BG_TOP, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  🎯  새 프로젝트 설정",
                 fg=FG_MAIN, bg=BG_TOP,
                 font=self.fn_bold).pack(side="left", padx=12, pady=8)
        tk.Label(hdr,
                 text="처음에 많이 알려줄수록 AI가 중간에 멈추지 않고 끝까지 완성합니다",
                 fg=FG_GRAY, bg=BG_TOP,
                 font=self.fn_small).pack(side="left", padx=4)

        # ── 스크롤 캔버스 영역 ────────────────────────────
        wrap = tk.Frame(self.wizard_frame, bg=BG_DARK)
        wrap.pack(fill="both", expand=True)

        self.wz_canvas = tk.Canvas(wrap, bg=BG_DARK, bd=0,
                                   highlightthickness=0)
        wz_sb = tk.Scrollbar(wrap, orient="vertical",
                             command=self.wz_canvas.yview,
                             bg=BG_DARK, troughcolor=BG_DARK,
                             activebackground=FG_BORDER, width=10)
        self.wz_canvas.configure(yscrollcommand=wz_sb.set)
        wz_sb.pack(side="right", fill="y")
        self.wz_canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(self.wz_canvas, bg=BG_DARK)
        self.wz_canvas_win = self.wz_canvas.create_window(
            (0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
            lambda e: self.wz_canvas.configure(
                scrollregion=self.wz_canvas.bbox("all")))
        self.wz_canvas.bind("<Configure>",
            lambda e: self.wz_canvas.itemconfig(
                self.wz_canvas_win, width=e.width))
        self.wz_canvas.bind("<MouseWheel>",
            lambda e: self.wz_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"))

        self._build_wizard_sections(inner)

        # ── 푸터 ────────────────────────────────────────────
        ftr = tk.Frame(self.wizard_frame, bg=BG_TOP, height=58)
        ftr.pack(fill="x")
        ftr.pack_propagate(False)
        self.wz_err_lbl = tk.Label(ftr, text="", fg=FG_ERR, bg=BG_TOP,
                                    font=self.fn_small)
        self.wz_err_lbl.pack(side="left", padx=16)
        tk.Button(ftr, text="  🚀  시작하기  ", command=self._wizard_submit,
                  bg="#1a4a28", fg=FG_CLAUDE, relief="flat",
                  font=self.fn_bold, padx=18, pady=8,
                  cursor="hand2",
                  activebackground="#2a6a38",
                  activeforeground=FG_CLAUDE).pack(
                  side="right", padx=6, pady=10)
        tk.Button(ftr, text="취소", command=self._hide_wizard,
                  bg="#313244", fg=FG_GRAY, relief="flat",
                  font=self.fn_small, padx=14, pady=8,
                  cursor="hand2",
                  activebackground="#45475a").pack(
                  side="right", padx=2, pady=10)

    def _build_wizard_sections(self, parent):
        C = BG_PANEL   # 카드 배경
        D = BG_DARK    # 섹션 배경

        def sec_hdr(text):
            """섹션 구분선 + 제목"""
            f = tk.Frame(parent, bg=D)
            f.pack(fill="x", padx=20, pady=(18, 4))
            tk.Label(f, text=text, fg=FG_GEMINI, bg=D,
                     font=self.fn_bold).pack(side="left")
            tk.Frame(f, bg=FG_BORDER, height=1).pack(
                side="left", fill="x", expand=True, padx=(10, 0), pady=9)

        def card():
            """카드 프레임"""
            f = tk.Frame(parent, bg=C, padx=18, pady=12)
            f.pack(fill="x", padx=20, pady=(0, 2))
            return f

        def hint(parent_f, text):
            tk.Label(parent_f, text=text, fg=FG_GRAY, bg=C,
                     font=self.fn_small).pack(anchor="w", pady=(0, 8))

        # ── 1. 목표 (필수) ────────────────────────────────
        sec_hdr("1 │ 프로젝트 목표  *필수")
        c1 = card()
        hint(c1, "구체적일수록 AI가 정확하게 이해합니다. 예: 'FastAPI로 할일 관리 REST API 만들기, JWT 인증 포함'")
        self.wz_goal = tk.Text(
            c1, bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_ui,
            relief="flat", height=5, wrap="word",
            insertbackground=FG_MAIN,
            highlightthickness=1,
            highlightbackground=FG_BORDER,
            highlightcolor=FG_GEMINI, padx=10, pady=8)
        self.wz_goal.pack(fill="x")
        # Tab 키가 다음 위젯으로 이동하도록
        self.wz_goal.bind("<Tab>", lambda e: (
            self.wz_goal.tk_focusNext().focus(), "break")[1])

        # ── 2. 프로젝트 유형 ────────────────────────────
        sec_hdr("2 │ 프로젝트 유형")
        c2 = card()
        self.wz_proj_type = tk.StringVar(value="AI가 판단")
        types = [
            ("🌐 웹 애플리케이션",      "웹 애플리케이션 (프론트+백엔드)"),
            ("⚙️ API / 백엔드 서버",    "REST API / 백엔드 서버"),
            ("🖥️ 데스크톱 프로그램",    "데스크톱 프로그램"),
            ("🤖 스크립트 / 자동화",    "스크립트 / 자동화 도구"),
            ("📊 데이터 분석 / AI",     "데이터 분석 / AI 모델"),
            ("📝 문서 / 콘텐츠 작성",   "문서 / 콘텐츠 작성"),
            ("🔀 AI가 판단",            "AI가 판단"),
        ]
        g2 = tk.Frame(c2, bg=C)
        g2.pack(fill="x")
        for i, (lbl, val) in enumerate(types):
            tk.Radiobutton(g2, text=lbl, variable=self.wz_proj_type, value=val,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).grid(row=i // 3, column=i % 3, sticky="w",
                                  padx=10, pady=3)

        # ── 3. 기술 스택 ────────────────────────────────
        sec_hdr("3 │ 기술 스택 선호도  (복수 선택 가능)")
        c3 = card()
        hint(c3, "선택 안 하면 AI가 자동으로 가장 적합한 기술을 선택합니다")
        self.wz_tech = {}
        techs = [
            "Python",                     "JavaScript / TypeScript",  "React / Next.js",
            "FastAPI / Django / Flask",   "Node.js / Express",        "Vue / Svelte",
            "SQL 데이터베이스",            "NoSQL (MongoDB 등)",       "Docker / 컨테이너",
            "AI/ML (PyTorch, sklearn)",   "AWS / GCP / Azure SDK",    "AI가 선택",
        ]
        g3 = tk.Frame(c3, bg=C)
        g3.pack(fill="x")
        for i, name in enumerate(techs):
            var = tk.BooleanVar(value=False)
            self.wz_tech[name] = var
            tk.Checkbutton(g3, text=name, variable=var,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).grid(row=i // 3, column=i % 3, sticky="w",
                                  padx=10, pady=3)

        # ── 4. 결과물 형태 ──────────────────────────────
        sec_hdr("4 │ 결과물 형태  (복수 선택 가능)")
        c4 = card()
        self.wz_output = {}
        outs = [
            ("✅ 실행 가능한 소스 코드",          "실행 가능한 소스 코드"),
            ("📄 API 명세 / 문서 (README 등)",    "API 명세 / 문서"),
            ("🧪 테스트 코드 포함",               "테스트 코드 포함"),
            ("🐳 배포 설정 (Dockerfile / CI)",    "배포 설정 파일"),
            ("📖 사용 설명서",                    "사용 설명서"),
            ("📊 분석 리포트 / 요약",             "분석 리포트"),
        ]
        g4 = tk.Frame(c4, bg=C)
        g4.pack(fill="x")
        for i, (lbl, val) in enumerate(outs):
            var = tk.BooleanVar(value=False)
            self.wz_output[val] = var
            tk.Checkbutton(g4, text=lbl, variable=var,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).grid(row=i // 2, column=i % 2, sticky="w",
                                  padx=10, pady=3)

        # ── 5. 품질 수준 ────────────────────────────────
        sec_hdr("5 │ 품질 수준")
        c5 = card()
        self.wz_quality = tk.StringVar(value="균형")
        qualities = [
            ("🚀 빠른 프로토타입",
             "균형",   # 라디오 값
             "빠른 프로토타입",
             "일단 동작하면 OK — 아이디어 확인용"),
            ("⚖️ 균형  ✓ 권장",
             "균형",
             "균형",
             "실제 사용 가능한 수준 — 대부분의 프로젝트에 적합"),
            ("💎 프로덕션 품질",
             "프로덕션 품질",
             "프로덕션 품질",
             "테스트·보안·최적화까지 — 시간이 걸려도 OK"),
        ]
        qualities = [
            ("🚀 빠른 프로토타입",  "빠른 프로토타입",  "일단 동작하면 OK — 아이디어 확인용"),
            ("⚖️ 균형  ✓ 권장",     "균형",             "실제 사용 가능한 수준 — 대부분의 프로젝트에 적합"),
            ("💎 프로덕션 품질",    "프로덕션 품질",    "테스트·보안·최적화까지 — 시간이 걸려도 OK"),
        ]
        for lbl, val, desc in qualities:
            row_f = tk.Frame(c5, bg=C, pady=2)
            row_f.pack(fill="x")
            tk.Radiobutton(row_f, text=lbl, variable=self.wz_quality, value=val,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).pack(side="left", padx=4)
            tk.Label(row_f, text=f"   {desc}", fg=FG_GRAY, bg=C,
                     font=self.fn_small).pack(side="left")

        # ── 6. 실행 환경 ────────────────────────────────
        sec_hdr("6 │ 실행 / 배포 환경")
        c6 = card()
        self.wz_env = tk.StringVar(value="AI가 결정")
        envs = [
            ("Windows 로컬",         "Windows 로컬"),
            ("Linux 서버",           "Linux 서버"),
            ("Docker 컨테이너",      "Docker 컨테이너"),
            ("클라우드 (AWS/GCP)",   "클라우드 (AWS / GCP / Azure)"),
            ("Vercel / Netlify",     "Vercel / Netlify"),
            ("AI가 결정",            "AI가 결정"),
        ]
        g6 = tk.Frame(c6, bg=C)
        g6.pack(fill="x")
        for i, (lbl, val) in enumerate(envs):
            tk.Radiobutton(g6, text=lbl, variable=self.wz_env, value=val,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).grid(row=i // 3, column=i % 3, sticky="w",
                                  padx=10, pady=3)

        # ── 7. 언어 설정 ────────────────────────────────
        sec_hdr("7 │ 코드 언어 설정")
        c7 = card()
        self.wz_lang = tk.StringVar(value="한국어 주석 + 한국어 문서")
        langs = [
            ("한국어 주석 + 한국어 문서", "한국어 주석 + 한국어 문서"),
            ("영어 주석 + 영어 문서",     "영어 주석 + 영어 문서"),
            ("영어 주석 + 한국어 문서",   "영어 주석 + 한국어 문서"),
        ]
        g7 = tk.Frame(c7, bg=C)
        g7.pack(fill="x")
        for i, (lbl, val) in enumerate(langs):
            tk.Radiobutton(g7, text=lbl, variable=self.wz_lang, value=val,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).grid(row=0, column=i, sticky="w", padx=12, pady=3)

        # ── 8. 추가 요구사항 ─────────────────────────────
        sec_hdr("8 │ 추가 제약사항 / 특이사항  (선택)")
        c8 = card()
        hint(c8, "피해야 할 것, 반드시 포함할 것, 참고 링크, 기존 코드 위치 등 자유롭게 작성")
        self.wz_notes = tk.Text(
            c8, bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_small,
            relief="flat", height=4, wrap="word",
            insertbackground=FG_MAIN,
            highlightthickness=1,
            highlightbackground=FG_BORDER,
            highlightcolor=FG_GEMINI, padx=10, pady=8)
        self.wz_notes.pack(fill="x")

        # 여백
        tk.Frame(parent, bg=D, height=24).pack()

    def _run(self, args: list):
        ws = self.ws_var.get().strip()
        if ws:
            args = args + ["-WorkspaceDir", ws]

        self.btn_send.configure(state="disabled")

        def worker():
            cmd = [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", MANAGER_PS1,
            ] + args
            self.proc = subprocess.Popen(
                cmd, cwd=MANAGER_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for raw in self.proc.stdout:
                line, tag = self._classify(raw)
                if tag == "__spinner__":
                    self.root.after(0, self._update_activity, line)
                elif line is not None:
                    # CLARIFY 대기 신호 즉시 감지 (폴링 800ms 대기 없이)
                    if "gui에서 답변을 기다리는 중" in line.lower():
                        self.root.after(200, self._ensure_clarify_shown)
                    self.root.after(0, self._append, line + "\n", tag)
            self.proc.wait()
            self.root.after(0, self._on_finish, self.proc.returncode)

        threading.Thread(target=worker, daemon=True).start()

    def _update_activity(self, info: str):
        parts = info.split(":")
        if len(parts) < 4:
            return
        agent, elapsed, max_t, spin = parts[0], int(parts[1]), int(parts[2]), parts[3]

        ratio   = min(elapsed / max_t, 1.0)
        bar_len = 18
        filled  = int(bar_len * ratio)

        ag_tag = {"gemini": "ag_gem", "claude": "ag_cla", "codex": "ag_cod"}.get(agent, "ag_cla")

        self.activity_box.configure(state="normal")
        self.activity_box.delete("1.0", "end")
        self.activity_box.insert("end", f" {spin} ", "spin_c")
        self.activity_box.insert("end", f"[{agent}]  ", (ag_tag,))
        self.activity_box.insert("end", "█" * filled, "bar_af")
        self.activity_box.insert("end", "░" * (bar_len - filled) + "\n", "bar_ae")
        self.activity_box.insert("end", f"     {elapsed}s", "sec")
        self.activity_box.insert("end", f" / {max_t}s\n", "bar_ae")
        self.activity_box.configure(state="disabled")

    def _clear_activity(self):
        self.activity_box.configure(state="normal")
        self.activity_box.delete("1.0", "end")
        self.activity_box.insert("end", " (대기 중)\n", "idle")
        self.activity_box.configure(state="disabled")

    def _on_finish(self, rc: int):
        self._clear_activity()
        self.btn_send.configure(state="normal")
        self.entry.focus()
        ws  = self.ws_var.get().strip()
        loc = ws if ws else os.path.join(MANAGER_DIR, "workspace")
        if rc == 0:
            self._append(f"  ✓ 완료  —  결과물 위치: {loc}\n\n", "system")
        else:
            self._append(f"  ✗ 종료 코드: {rc}\n\n", "error")

    def _on_close(self):
        self._save_config()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
