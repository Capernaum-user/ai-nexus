#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Nexus GUI  —  멀티유저 채팅 + 파이프라인 통합
채팅방(좌) · 파이프라인 로그(중) · 대시보드(우)
"""

import tkinter as tk
from tkinter import font, filedialog
import subprocess
import threading
import os
import json
import re
import datetime
import urllib.request
import urllib.error
import socket
import time

# ── 경로 ──────────────────────────────────────────────────────────
MANAGER_DIR   = os.path.dirname(os.path.abspath(__file__))
MANAGER_PS1   = os.path.join(MANAGER_DIR, "manager.ps1")
STATE_FILE    = os.path.join(MANAGER_DIR, "STATE.json")
PLAN_FILE     = os.path.join(MANAGER_DIR, "PLAN.md")
QUEUE_FILE    = os.path.join(MANAGER_DIR, "TASK_QUEUE.json")
CLARIFY_QUEST_FILE = os.path.join(MANAGER_DIR, "CLARIFY_QUESTIONS.md")
CLARIFY_ANS_FILE   = os.path.join(MANAGER_DIR, "CLARIFICATIONS.md")
CONFIG_FILE   = os.path.join(MANAGER_DIR, "gui_config.json")
CONTEXT_FILE  = os.path.join(MANAGER_DIR, "CONTEXT.md")
LOG_DIR       = os.path.join(MANAGER_DIR, "logs")
CHAT_LOG_DIR  = os.path.join(LOG_DIR, "chat")
SERVER_DIR    = os.path.join(MANAGER_DIR, "server")
SERVER_PORT   = 8765

# ── 파이프라인 단계 ────────────────────────────────────────────────
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

AGENT_STYLE = {
    "gemini":  ("#0d2a38", "#89dceb", "#0a1e2d"),
    "claude":  ("#0d2a1a", "#a6e3a1", "#0a1e12"),
    "codex":   ("#22103a", "#cba6f7", "#180d2d"),
    "manager": ("#352010", "#fab387", "#28180a"),
}

# 캔버스 치수
NODE_H     = 46
ZZ_NODE_W  = 126
ZZ_COL_GAP = 14
ZZ_ROW_GAP = 24
ZZ_PAD_X   = 5
ZZ_PAD_TOP = 10
ZZ_TOTAL_W = ZZ_PAD_X * 2 + ZZ_NODE_W * 2 + ZZ_COL_GAP  # 276

# ── 다크 테마 ──────────────────────────────────────────────────────
BG_MAIN    = "#1e1e2e"
BG_DARK    = "#181825"
BG_TOP     = "#11111b"
BG_WS      = "#1a1a2e"
BG_ENTRY   = "#313244"
BG_CLARIFY = "#12122a"
BG_PANEL   = "#16162a"
BG_PHDR    = "#1a1a30"
BG_CHAT    = "#181830"

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
FG_INTENT  = "#f9e2af"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Nexus")
        self.root.geometry("1560x880")
        self.root.configure(bg=BG_MAIN)
        self.root.minsize(1100, 600)

        self.proc           = None
        self.clarify_mode   = False
        self.clarify_lines  = []
        self._last_spin     = ""
        self._plan_cache    = ""
        self._queue_cache   = ""
        self._state_cache   = ""

        # 채팅 상태
        self.chat_messages  = []   # 로컬 보관용
        self._chat_offset   = 0    # 서버에서 마지막으로 가져온 인덱스
        self.my_nick        = "Host"
        self.room_id        = "general"
        self.server_proc    = None
        self._server_ready  = False
        self._local_ip      = self._get_local_ip()
        self._chat_fetching = False   # 중복 요청 방지 플래그
        self._users_fetching = False
        self._my_pending = []         # 내가 보낸 (nick, text) — 서버 중복 방지용

        # 파이프라인 애니메이션
        self._node_rects    = {}
        self._pulse_state   = False
        self._current_stage = ""

        # 위저드
        self.wizard_frame  = None
        self.wz_goal       = None
        self.wz_notes      = None
        self.wz_proj_type  = None
        self.wz_quality    = None
        self.wz_env        = None
        self.wz_lang       = None
        self.wz_tech       = {}
        self.wz_output     = {}
        self.wz_err_lbl    = None
        self.wz_canvas     = None
        self.wz_canvas_win = None

        # OS 폴더 생성
        os.makedirs(CHAT_LOG_DIR, exist_ok=True)

        self._build_fonts()
        self._build_ui()
        self._load_config()
        self._welcome()
        self._clear_activity()
        self._draw_pipeline_canvas("")

        self._start_server()

        self._poll_state()
        self._poll_clarify()
        self._poll_tasks()
        self._poll_chat()
        self._anim_pipeline()

        self.root.bind("<Escape>", self._dismiss_clarify)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 폰트 ──────────────────────────────────────────────────────
    def _build_fonts(self):
        self.fn_mono    = font.Font(family="Consolas",      size=10)
        self.fn_dash    = font.Font(family="Consolas",      size=9)
        self.fn_dash_b  = font.Font(family="Consolas",      size=9, weight="bold")
        self.fn_ui      = font.Font(family="Malgun Gothic", size=11)
        self.fn_small   = font.Font(family="Malgun Gothic", size=9)
        self.fn_bold    = font.Font(family="Malgun Gothic", size=10, weight="bold")
        self.fn_title   = font.Font(family="Malgun Gothic", size=10, weight="bold")
        self.fn_cv_name  = font.Font(family="Consolas",    size=9,  weight="bold")
        self.fn_cv_desc  = font.Font(family="Malgun Gothic", size=8)
        self.fn_cv_badge = font.Font(family="Consolas",    size=8,  weight="bold")
        self.fn_cv_num   = font.Font(family="Consolas",    size=8)
        self.fn_chat_name = font.Font(family="Consolas",   size=9,  weight="bold")
        self.fn_chat_msg  = font.Font(family="Malgun Gothic", size=10)
        self.fn_chat_ts   = font.Font(family="Consolas",   size=8)

    # ══════════════════════════════════════════════════════════════
    # UI 구성
    # ══════════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── 상태 바 ──────────────────────────────────────────────
        topbar = tk.Frame(self.root, bg=BG_TOP, height=40)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        self.dot = tk.Label(topbar, text="●", fg=FG_GRAY, bg=BG_TOP,
                            font=("Consolas", 14))
        self.dot.pack(side="left", padx=(12, 3), pady=6)

        self.lbl_status = tk.Label(topbar, text="준비", fg=FG_GRAY, bg=BG_TOP,
                                    font=self.fn_small)
        self.lbl_status.pack(side="left", pady=6)

        tk.Label(topbar, text="  AI Nexus", fg=FG_MAIN, bg=BG_TOP,
                 font=self.fn_title).pack(side="left", pady=6)

        self.server_badge = tk.Label(topbar, text="● 서버 시작 중",
                                      fg=FG_GRAY, bg=BG_TOP, font=self.fn_small)
        self.server_badge.pack(side="left", padx=12, pady=6)

        tk.Button(topbar, text="✦ 새 프로젝트", command=self._force_new,
                  bg="#313244", fg=FG_SYSTEM, activebackground="#45475a",
                  activeforeground=FG_SYSTEM, relief="flat",
                  font=self.fn_small, padx=10, pady=4,
                  cursor="hand2", bd=0).pack(side="right", padx=4, pady=6)

        tk.Button(topbar, text="🗑 초기화", command=self._reset_project,
                  bg="#3a1a1a", fg=FG_ERR, activebackground="#5a2828",
                  activeforeground=FG_ERR, relief="flat",
                  font=self.fn_small, padx=10, pady=4,
                  cursor="hand2", bd=0).pack(side="right", padx=0, pady=6)

        # ── 작업 폴더 바 ─────────────────────────────────────────
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

        self.lbl_ws_hint = tk.Label(wsbar, text="미지정 시 ai-nexus/workspace/ 사용",
                                     fg=FG_GRAY, bg=BG_WS, font=self.fn_small)
        self.lbl_ws_hint.pack(side="right", padx=6)

        # ── 메인 영역 (3열) ───────────────────────────────────────
        main_area = tk.Frame(self.root, bg=BG_MAIN)
        main_area.pack(fill="both", expand=True)

        # LEFT: 채팅방 (500px)
        self._build_chat_room(main_area)
        tk.Frame(main_area, bg=FG_BORDER, width=1).pack(side="left", fill="y")

        # CENTER: 파이프라인 로그 (expand)
        self.log_outer = tk.Frame(main_area, bg=BG_MAIN)
        self.log_outer.pack(side="left", fill="both", expand=True)
        log_outer = self.log_outer

        self.chat = tk.Text(
            log_outer, bg=BG_MAIN, fg=FG_MAIN, font=self.fn_mono,
            relief="flat", wrap="word", state="disabled",
            padx=16, pady=10, selectbackground="#45475a",
            cursor="arrow", spacing1=1, spacing3=1,
        )
        csb = tk.Scrollbar(log_outer, command=self.chat.yview,
                            bg=BG_MAIN, troughcolor=BG_MAIN,
                            activebackground=FG_BORDER, width=10)
        self.chat.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)

        for name, color in {
            "user":  FG_USER,   "gemini": FG_GEMINI, "claude": FG_CLAUDE,
            "system": FG_SYSTEM, "warn":   FG_WARN,   "error":  FG_ERR,
            "accent": FG_ACCENT, "gray":   FG_GRAY,   "main":   FG_MAIN,
        }.items():
            self.chat.tag_configure(name, foreground=color)
        self.chat.tag_configure("bold_gemini", foreground=FG_GEMINI,
            font=font.Font(family="Consolas", size=10, weight="bold"))
        self.chat.tag_configure("bold_system", foreground=FG_SYSTEM,
            font=font.Font(family="Consolas", size=10, weight="bold"))

        tk.Frame(main_area, bg=FG_BORDER, width=1).pack(side="left", fill="y")

        # RIGHT: 대시보드 (460px)
        self._build_dashboard(main_area)

        # ── CLARIFY 패널 (CENTER log_outer 위 overlay) ────────────
        # place()로 배치 → 채팅 입력창/레이아웃에 영향 없음
        self.clarify_frame = tk.Frame(self.log_outer, bg=BG_CLARIFY,
                                       bd=1, relief="flat")

        # 헤더 행: 제목 + 건너뛰기/중지 버튼
        cq_hdr = tk.Frame(self.clarify_frame, bg="#0d1f30", height=30)
        cq_hdr.pack(fill="x")
        cq_hdr.pack_propagate(False)
        tk.Label(cq_hdr,
                 text="  🤔 Gemini 질문  —  번호별 답변 후 빈 줄(Enter)로 완료  |  ESC로 건너뜀",
                 fg=FG_GEMINI, bg="#0d1f30",
                 font=self.fn_dash_b).pack(side="left", pady=5)
        tk.Button(cq_hdr, text="■ 파이프라인 중지", command=self._stop_from_clarify,
                  bg="#3a1a1a", fg=FG_ERR, relief="flat",
                  font=self.fn_small, padx=8, pady=3,
                  cursor="hand2").pack(side="right", padx=4, pady=4)
        tk.Button(cq_hdr, text="⏩ 질문 건너뛰기", command=self._dismiss_clarify,
                  bg="#1a2a3a", fg=FG_WARN, relief="flat",
                  font=self.fn_small, padx=8, pady=3,
                  cursor="hand2").pack(side="right", padx=0, pady=4)

        cq_wrap = tk.Frame(self.clarify_frame, bg=BG_CLARIFY)
        cq_wrap.pack(fill="both", expand=True, padx=8, pady=(4, 6))

        self.clarify_q = tk.Text(
            cq_wrap, bg="#12122e", fg=FG_GEMINI,
            font=self.fn_mono, height=8, state="disabled",
            relief="flat", padx=10, pady=8, wrap="word",
        )
        cq_sb = tk.Scrollbar(cq_wrap, command=self.clarify_q.yview,
                              bg=BG_CLARIFY, troughcolor=BG_CLARIFY, width=8)
        self.clarify_q.configure(yscrollcommand=cq_sb.set)
        cq_sb.pack(side="right", fill="y")
        self.clarify_q.pack(side="left", fill="both", expand=True)

        # ── 입력 영역 (clarify / 직접 목표 입력) ─────────────────
        input_outer = tk.Frame(self.root, bg=BG_DARK, pady=8)
        input_outer.pack(fill="x", side="bottom")

        self.lbl_hint = tk.Label(
            input_outer,
            text="파이프라인 직접 목표 입력  (Enter로 전송)  —  또는 좌측 채팅에서 AI 분석 실행",
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

        self.btn_send = tk.Button(
            row, text="전송", command=self._send,
            bg=FG_GEMINI, fg=BG_MAIN, font=self.fn_bold,
            relief="flat", padx=20, pady=9,
            cursor="hand2", activebackground="#74c7ec", activeforeground=BG_MAIN,
        )
        self.btn_send.pack(side="right", padx=4)

    # ══════════════════════════════════════════════════════════════
    # 채팅방 패널 (LEFT)
    # ══════════════════════════════════════════════════════════════
    def _build_chat_room(self, parent):
        panel = tk.Frame(parent, bg=BG_CHAT, width=500)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)

        # 헤더
        hdr = tk.Frame(panel, bg=BG_PHDR, height=26)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="  💬", fg=FG_GEMINI, bg=BG_PHDR,
                 font=self.fn_dash_b).pack(side="left", pady=3)
        self.chat_room_lbl = tk.Label(hdr, text="채팅방  general",
                                       fg=FG_GEMINI, bg=BG_PHDR, font=self.fn_dash_b)
        self.chat_room_lbl.pack(side="left", pady=3)
        self.chat_users_lbl = tk.Label(hdr, text="", fg=FG_GRAY, bg=BG_PHDR,
                                        font=self.fn_small)
        self.chat_users_lbl.pack(side="left", padx=4, pady=3)

        tk.Button(hdr, text="💾", command=self._save_chat_log,
                  bg=BG_PHDR, fg=FG_GRAY, relief="flat",
                  font=self.fn_small, cursor="hand2", padx=4
                  ).pack(side="right", pady=3, padx=4)

        # 서버 정보 바
        info_bar = tk.Frame(panel, bg=BG_TOP, height=22)
        info_bar.pack(fill="x")
        info_bar.pack_propagate(False)
        self.srv_lbl = tk.Label(info_bar, text="  서버 준비 중...",
                                 fg=FG_GRAY, bg=BG_TOP, font=self.fn_small)
        self.srv_lbl.pack(side="left", pady=2)

        # 메시지 영역
        msg_wrap = tk.Frame(panel, bg=BG_CHAT)
        msg_wrap.pack(fill="both", expand=True)

        self.chat_room_box = tk.Text(
            msg_wrap, bg=BG_CHAT, fg=FG_MAIN, font=self.fn_chat_msg,
            relief="flat", wrap="word", state="disabled",
            padx=10, pady=8, selectbackground="#45475a",
            cursor="arrow", spacing1=3, spacing3=3,
        )
        crb_sb = tk.Scrollbar(msg_wrap, command=self.chat_room_box.yview,
                               bg=BG_CHAT, troughcolor=BG_CHAT,
                               activebackground=FG_BORDER, width=8)
        self.chat_room_box.configure(yscrollcommand=crb_sb.set)
        crb_sb.pack(side="right", fill="y")
        self.chat_room_box.pack(side="left", fill="both", expand=True)

        # 태그 설정
        self.chat_room_box.tag_configure("me_name",
            foreground=FG_USER, font=self.fn_chat_name)
        self.chat_room_box.tag_configure("other_name",
            foreground=FG_GEMINI, font=self.fn_chat_name)
        self.chat_room_box.tag_configure("me_text",  foreground=FG_MAIN)
        self.chat_room_box.tag_configure("other_text", foreground=FG_MAIN)
        self.chat_room_box.tag_configure("system_c", foreground=FG_GRAY,
            font=self.fn_chat_ts)
        self.chat_room_box.tag_configure("ts_tag",   foreground=FG_GRAY,
            font=self.fn_chat_ts)
        self.chat_room_box.tag_configure("intent_tag", foreground=FG_WARN,
            font=font.Font(family="Malgun Gothic", size=9, weight="bold"))

        # AI 분석 버튼
        ai_row = tk.Frame(panel, bg=BG_DARK, pady=5)
        ai_row.pack(fill="x", padx=8)

        self.btn_analyze = tk.Button(
            ai_row,
            text="🤖  AI가 대화 전체 분석 후 파이프라인 자동 시작",
            command=self._analyze_chat,
            bg="#162436", fg=FG_GEMINI,
            activebackground="#1e3050", activeforeground=FG_GEMINI,
            relief="flat", font=self.fn_bold, pady=9,
            cursor="hand2", bd=0,
        )
        self.btn_analyze.pack(fill="x")

        # 닉네임 + 입력 행
        nick_row = tk.Frame(panel, bg=BG_DARK)
        nick_row.pack(fill="x", padx=8, pady=(4, 0))

        tk.Label(nick_row, text="닉:", fg=FG_GRAY, bg=BG_DARK,
                 font=self.fn_small).pack(side="left")
        self.nick_var = tk.StringVar(value="Host")
        nick_e = tk.Entry(nick_row, textvariable=self.nick_var, width=10,
                          bg=BG_ENTRY, fg=FG_USER, font=self.fn_small,
                          relief="flat", insertbackground=FG_MAIN,
                          highlightthickness=1, highlightbackground=FG_BORDER)
        nick_e.pack(side="left", padx=(4, 0), ipady=4)

        msg_row = tk.Frame(panel, bg=BG_DARK)
        msg_row.pack(fill="x", padx=8, pady=(3, 8))

        self.chat_msg_var = tk.StringVar()
        chat_e = tk.Entry(msg_row, textvariable=self.chat_msg_var,
                          bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_chat_msg,
                          relief="flat", insertbackground=FG_MAIN,
                          highlightthickness=1, highlightbackground=FG_BORDER,
                          highlightcolor=FG_USER)
        chat_e.pack(side="left", fill="x", expand=True, ipady=8)
        chat_e.bind("<Return>", lambda _: self._send_chat())

        tk.Button(msg_row, text="전송", command=self._send_chat,
                  bg=FG_USER, fg=BG_MAIN, font=self.fn_bold,
                  relief="flat", padx=14, pady=8,
                  cursor="hand2",
                  activebackground="#74c7ec"
                  ).pack(side="right", padx=(6, 0))

    # ── 채팅방 메시지 추가 ────────────────────────────────────────
    def _append_chat_room(self, msg: dict):
        box = self.chat_room_box
        mtype = msg.get("type", "chat")
        ts    = msg.get("ts", "")
        user  = msg.get("user", "")
        text  = msg.get("text", "")

        box.configure(state="normal")

        if mtype == "room.join":
            box.insert("end", f"  {ts}  {user} 입장\n", "system_c")
        elif mtype == "room.leave":
            box.insert("end", f"  {ts}  {user} 퇴장\n", "system_c")
        elif mtype == "intent.detected":
            snippet = msg.get("snippet", "")
            box.insert("end", f"\n  🤖 작업 요청 감지: ", "intent_tag")
            box.insert("end", f'"{snippet}"\n\n', "other_text")
        elif mtype == "chat":
            is_me = (user == self.nick_var.get())
            name_tag = "me_name" if is_me else "other_name"
            text_tag = "me_text" if is_me else "other_text"
            box.insert("end", f"[{ts}] ", "ts_tag")
            box.insert("end", f"{user}", name_tag)
            box.insert("end", f"\n  {text}\n\n", text_tag)

        box.see("end")
        box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════
    # 서버 시작 / HTTP 통신
    # ══════════════════════════════════════════════════════════════
    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    def _start_server(self):
        cmd = [
            "python", "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0",
            "--port", str(SERVER_PORT),
            "--log-level", "warning",
        ]
        try:
            self.server_proc = subprocess.Popen(
                cmd, cwd=SERVER_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # 서버 준비 확인은 백그라운드에서 (메인 스레드 블로킹 방지)
            self.root.after(2000, self._check_server_ready)
        except Exception as e:
            self.srv_lbl.configure(text=f"  서버 오류: {e}", fg=FG_ERR)

    def _check_server_ready(self):
        """백그라운드 스레드에서 서버 준비 확인."""
        def _bg():
            for _ in range(20):   # 최대 20회 재시도
                try:
                    urllib.request.urlopen(
                        f"http://localhost:{SERVER_PORT}/api/state", timeout=1)
                    self.root.after(0, self._on_server_ready)
                    return
                except Exception:
                    time.sleep(1.5)
        threading.Thread(target=_bg, daemon=True).start()

    def _on_server_ready(self):
        self._server_ready = True
        ip_txt = f"  {self._local_ip}:{SERVER_PORT}  (브라우저 접속 가능)"
        self.srv_lbl.configure(text=ip_txt, fg=FG_CLAUDE)
        self.server_badge.configure(
            text=f"● 서버 ON  {self._local_ip}:{SERVER_PORT}", fg=FG_CLAUDE)
        self._sys_chat(f"서버 시작  —  {self._local_ip}:{SERVER_PORT}")
        self._sys_chat("브라우저에서 접속하거나 프로그램을 여러 명이 열면 채팅 가능")

    def _api_get(self, path: str):
        try:
            url = f"http://localhost:{SERVER_PORT}{path}"
            with urllib.request.urlopen(url, timeout=1) as r:
                return json.loads(r.read())
        except Exception:
            return None

    def _api_post(self, path: str, data: dict):
        try:
            url  = f"http://localhost:{SERVER_PORT}{path}"
            body = json.dumps(data).encode("utf-8")
            req  = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1) as r:
                return json.loads(r.read())
        except Exception:
            return None

    # ── 채팅 폴링 (메인 스레드는 스케줄만, 실제 HTTP는 백그라운드) ──
    def _poll_chat(self):
        if self._server_ready:
            if not self._chat_fetching:
                self._chat_fetching = True
                threading.Thread(target=self._fetch_messages_bg,
                                 daemon=True).start()
        self.root.after(600, self._poll_chat)

    def _fetch_messages_bg(self):
        """백그라운드: 메시지 + 유저 목록 동시 조회."""
        offset = self._chat_offset
        try:
            # 메시지
            url = f"http://localhost:{SERVER_PORT}/api/messages/{self.room_id}?after={offset}"
            with urllib.request.urlopen(url, timeout=1) as r:
                res = json.loads(r.read())
            new_msgs = res.get("messages", [])
            total    = res.get("total", offset)
            if new_msgs:
                self.root.after(0, self._on_new_messages, new_msgs, total)
            else:
                self._chat_offset = total
        except Exception:
            pass

        try:
            # 유저 목록 (느려도 UI 안 막음)
            url2 = f"http://localhost:{SERVER_PORT}/api/users/{self.room_id}"
            with urllib.request.urlopen(url2, timeout=1) as r:
                res2 = json.loads(r.read())
            users = res2.get("users", [])
            self.root.after(0, self._on_users_update, users)
        except Exception:
            pass

        self._chat_fetching = False

    def _on_new_messages(self, new_msgs: list, total: int):
        """메인 스레드: 새 메시지를 UI에 반영. 내가 보낸 메시지는 건너뜀."""
        for msg in new_msgs:
            if msg.get("type") == "chat":
                key = (msg.get("user", ""), msg.get("text", ""))
                if key in self._my_pending:
                    self._my_pending.remove(key)   # 첫 매칭 하나만 소비
                    self.chat_messages.append(msg) # 로그엔 저장
                    continue                        # 화면엔 이미 표시됨 — 스킵
            self.chat_messages.append(msg)
            self._append_chat_room(msg)
        self._chat_offset = total

    def _on_users_update(self, users: list):
        """메인 스레드: 유저 목록 라벨 갱신."""
        if users:
            self.chat_users_lbl.configure(
                text=f"• {len(users)}명: {', '.join(users)}")
        else:
            self.chat_users_lbl.configure(text="")

    # ── 채팅 전송 ────────────────────────────────────────────────
    def _send_chat(self):
        text = self.chat_msg_var.get().strip()
        if not text:
            return
        self.chat_msg_var.set("")
        nick = self.nick_var.get().strip() or "Host"

        # 즉시 로컬 표시 (딜레이 없음)
        msg = {"type": "chat", "user": nick, "text": text,
               "ts": datetime.datetime.now().strftime("%H:%M:%S")}
        self.chat_messages.append(msg)
        self._append_chat_room(msg)

        if self._server_ready:
            # fingerprint 등록 → 서버 폴링이 돌아올 때 이 메시지를 스킵
            self._my_pending.append((nick, text))
            threading.Thread(
                target=self._api_post,
                args=(f"/api/chat/{self.room_id}", {"user": nick, "text": text}),
                daemon=True,
            ).start()

    def _sys_chat(self, text: str):
        msg = {"type": "room.join", "user": "시스템",
               "ts": datetime.datetime.now().strftime("%H:%M:%S")}
        box = self.chat_room_box
        box.configure(state="normal")
        box.insert("end", f"  {text}\n", "system_c")
        box.see("end")
        box.configure(state="disabled")

    # ── AI 대화 분석 → 파이프라인 ─────────────────────────────────
    def _analyze_chat(self):
        if self.proc and self.proc.poll() is None:
            self._sys_chat("[!] 파이프라인이 이미 실행 중입니다.")
            return

        # 대화 내용 수집
        human_msgs = [
            m for m in self.chat_messages
            if m.get("type") == "chat"
        ]
        if not human_msgs:
            self._sys_chat("[!] 채팅 내용이 없습니다. 먼저 대화를 나눠보세요.")
            return

        # ── 채팅에서 Goal 직접 추출 (AI에게 넘길 실제 텍스트) ──────
        chat_lines = [
            f'{m.get("user","?")}: {m.get("text","")}'
            for m in human_msgs
        ]
        chat_block = "\n".join(chat_lines)

        # Goal = 대화 전문 (Gemini가 애매한 placeholder를 무시하지 못하도록)
        goal_full = chat_block
        # -Goal 인자는 너무 길면 PS 오류 → 300자 요약본 사용, 전문은 CONTEXT.md에
        goal_short = chat_block[:280] + ("..." if len(chat_block) > 280 else "")

        # ── CONTEXT.md: 명확한 형식으로 저장 ────────────────────────
        ctx_lines = [
            "# [중요] 사용자 채팅 대화 — 이것이 실제 작업 요청입니다",
            "",
            "아래는 사용자들이 채팅방에서 나눈 대화 전문입니다.",
            "이 대화 내용을 근거로 사용자가 원하는 것을 파악하고 실행하십시오.",
            "절대로 대화 내용과 관계없는 주제를 상상하거나 추측하지 마십시오.",
            "CLARIFY 단계에서 이미 대화에서 언급된 내용은 다시 묻지 마십시오.",
            "",
            "## 채팅 대화 전문",
            "",
        ]
        ctx_lines += [
            f"  [{m.get('ts','')}] {m.get('user','?')}: {m.get('text','')}"
            for m in human_msgs
        ]
        ctx_lines += [
            "",
            "## 반드시 지킬 지시사항",
            "- 위 대화에서 언급된 내용만을 근거로 작업 목표를 결정하십시오.",
            "- 대화에 없는 내용을 임의로 추가하거나 상상하지 마십시오.",
            "- 위 대화가 불명확하면 CLARIFY에서 위 대화와 관련된 질문만 하십시오.",
        ]
        ctx = "\n".join(ctx_lines)

        try:
            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                f.write(ctx)
        except Exception as e:
            self._sys_chat(f"[!] 컨텍스트 저장 실패: {e}")
            return

        # 기존 상태 완료 처리
        st = self._get_state()
        if st:
            try:
                st["is_complete"] = True
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False)
            except Exception:
                pass

        self._sys_chat(f"AI가 대화를 분석합니다... 파이프라인 시작")
        self._append(f"\n  🤖 대화 분석 → 파이프라인 시작\n", "user")
        self._run(["-Goal", goal_short, "-Auto", "-GUI"])

    # ── 채팅 로그 저장 ────────────────────────────────────────────
    def _save_chat_log(self):
        if not self.chat_messages:
            self._sys_chat("저장할 대화가 없습니다.")
            return

        now = datetime.datetime.now()
        fname = f"chat_{now.strftime('%Y%m%d_%H%M%S')}.md"
        fpath = os.path.join(CHAT_LOG_DIR, fname)

        participants = sorted(set(
            m.get("user", "") for m in self.chat_messages
            if m.get("type") == "chat"
        ))

        lines = [
            "# 채팅 로그",
            "",
            f"**날짜:** {now.strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**방:** {self.room_id}  ",
            f"**서버:** {self._local_ip}:{SERVER_PORT}  ",
            f"**참여자:** {', '.join(participants) or '없음'}  ",
            "",
            "---",
            "",
            "| 시간 | 사용자 | 내용 |",
            "|------|--------|------|",
        ]
        for m in self.chat_messages:
            mtype = m.get("type", "")
            ts   = m.get("ts", "")
            user = m.get("user", "")
            text = m.get("text", "")
            if mtype == "chat":
                lines.append(f"| {ts} | {user} | {text} |")
            elif mtype == "room.join":
                lines.append(f"| {ts} | — | ✅ {user} 입장 |")
            elif mtype == "room.leave":
                lines.append(f"| {ts} | — | ❌ {user} 퇴장 |")

        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._sys_chat(f"로그 저장 완료: logs/chat/{fname}")
        except Exception as e:
            self._sys_chat(f"저장 실패: {e}")

    # ══════════════════════════════════════════════════════════════
    # 우측 대시보드
    # ══════════════════════════════════════════════════════════════
    def _build_dashboard(self, parent):
        panel = tk.Frame(parent, bg=BG_PANEL, width=460)
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

        # A. 파이프라인
        self.pipe_hdr_lbl = section_hdr("🔄 파이프라인  0 / 13")

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
        self.pipe_canvas.bind(
            "<MouseWheel>",
            lambda e: self.pipe_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # 재개/중지
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

        # B. 처리 중
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

        # C. 계획 요약
        section_hdr("📋 계획 요약")
        self.plan_box = tk.Text(
            panel, bg=BG_PANEL, fg=FG_GRAY, font=self.fn_dash,
            height=5, state="disabled", relief="flat",
            wrap="word", padx=8, pady=5,
        )
        self.plan_box.pack(fill="x")

        # D. 작업 현황
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

    # ══════════════════════════════════════════════════════════════
    # 파이프라인 캔버스 (지그재그 2열)
    # ══════════════════════════════════════════════════════════════
    def _draw_pipeline_canvas(self, current: str):
        c = self.pipe_canvas
        c.delete("all")
        self._node_rects = {}

        try:
            cur_idx = PIPELINE.index(current)
        except ValueError:
            cur_idx = -1

        n      = len(PIPELINE_INFO)
        n_rows = (n + 1) // 2
        total_h = ZZ_PAD_TOP * 2 + n_rows * NODE_H + (n_rows - 1) * ZZ_ROW_GAP
        c.configure(scrollregion=(0, 0, ZZ_TOTAL_W, total_h))

        lx0 = ZZ_PAD_X
        lx1 = lx0 + ZZ_NODE_W
        rx0 = lx1 + ZZ_COL_GAP
        rx1 = rx0 + ZZ_NODE_W

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
            else:
                return dict(state="current",
                            node_fill=node_act_bg, node_outline=accent,
                            name_col=accent, desc_col=FG_MAIN,
                            badge_fill=badge_bg, badge_out=accent,
                            badge_col=accent, num_col=accent,
                            accent=accent, arr_col=FG_WARN)

        # 화살표 먼저
        for i, (name, agent, badge_txt, desc, short_name) in enumerate(PIPELINE_INFO):
            if i >= n - 1:
                break
            row = i // 2
            col = i % 2
            y_row = ZZ_PAD_TOP + row * (NODE_H + ZZ_ROW_GAP)
            sty   = get_style(i, agent)

            if col == 0:
                y_mid = y_row + NODE_H // 2
                c.create_line(lx1, y_mid, rx0, y_mid,
                              fill=sty["arr_col"], width=1,
                              arrow="last", arrowshape=(6, 8, 3))
            else:
                x_r_mid = rx0 + ZZ_NODE_W // 2
                x_l_mid = lx0 + ZZ_NODE_W // 2
                y_bot   = y_row + NODE_H
                y_turn  = y_bot + ZZ_ROW_GAP // 2
                y_next  = y_bot + ZZ_ROW_GAP
                c.create_line(x_r_mid, y_bot,
                              x_r_mid, y_turn,
                              x_l_mid, y_turn,
                              x_l_mid, y_next,
                              fill=sty["arr_col"], width=1,
                              arrow="last", arrowshape=(6, 8, 3))

        # 노드
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
            rect_id = c.create_rectangle(
                x0, y0, x1, y1,
                fill=sty["node_fill"], outline=sty["node_outline"],
                width=outline_w,
            )
            self._node_rects[name] = rect_id

            if state == "current":
                c.create_rectangle(x0, y0, x0 + 3, y1,
                                   fill=sty["accent"], outline=sty["accent"])

            bx0, bx1 = x0 + 4, x0 + 26
            by0, by1 = y0 + 8, y1 - 8
            c.create_rectangle(bx0, by0, bx1, by1,
                               fill=sty["badge_fill"], outline=sty["badge_out"], width=1)
            c.create_text((bx0 + bx1) // 2, (by0 + by1) // 2,
                          text=badge_txt, fill=sty["badge_col"],
                          font=self.fn_cv_badge, anchor="center")

            c.create_text(x0 + 30, y0 + 7,
                          text=short_name, fill=sty["name_col"],
                          font=self.fn_cv_name, anchor="nw")
            c.create_text(x0 + 30, y0 + 25,
                          text=desc, fill=sty["desc_col"],
                          font=self.fn_cv_desc, anchor="nw")

            if state == "done":
                c.create_text(x1 - 4, y0 + 7,
                              text="✓", fill="#4a8a4a",
                              font=self.fn_cv_name, anchor="ne")
            else:
                c.create_text(x1 - 4, y0 + 7,
                              text=f"{i + 1:02d}", fill=sty["num_col"],
                              font=self.fn_cv_num, anchor="ne")

            if name == "PARALLEL_EXECUTE":
                c.create_text(x1 - 4, y1 - 8,
                              text="↻", fill="#585b70",
                              font=self.fn_cv_num, anchor="ne")

        if cur_idx >= 0 and total_h > 0:
            row_cur   = cur_idx // 2
            y_mid_cur = ZZ_PAD_TOP + row_cur * (NODE_H + ZZ_ROW_GAP) + NODE_H // 2
            frac = max(0.0, (y_mid_cur - 120) / total_h)
            c.yview_moveto(frac)

    # ── 파이프라인 캔버스 업데이트 ───────────────────────────────
    def _update_pipeline_canvas(self):
        st  = self._get_state()
        sig = json.dumps(st) if st else ""
        if sig == self._state_cache:
            return
        self._state_cache = sig

        current = st.get("status", "") if st else ""
        self._current_stage = current
        self._draw_pipeline_canvas(current)

        try:
            idx = PIPELINE.index(current)
        except ValueError:
            idx = 0
        pct   = int(idx / len(PIPELINE) * 100)
        label = f"  🔄 파이프라인  {idx} / {len(PIPELINE)}  ({pct}%)"
        if st and st.get("is_complete"):
            label = "  🔄 파이프라인  완료 ✓"
        self.pipe_hdr_lbl.configure(text=label)

    # ── 파이프라인 애니메이션 (펄스) ──────────────────────────────
    def _anim_pipeline(self):
        if self._current_stage and self._current_stage in self._node_rects:
            self._pulse_state = not self._pulse_state
            rect_id = self._node_rects[self._current_stage]
            agent = next(
                (a for n, a, *_ in PIPELINE_INFO if n == self._current_stage),
                "gemini",
            )
            _, accent, _ = AGENT_STYLE[agent]
            try:
                width = 3 if self._pulse_state else 1
                self.pipe_canvas.itemconfig(rect_id, width=width)
            except Exception:
                pass
        self.root.after(600, self._anim_pipeline)

    # ══════════════════════════════════════════════════════════════
    # 설정
    # ══════════════════════════════════════════════════════════════
    def _load_config(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            ws = cfg.get("last_workspace", "")
            self.ws_var.set(ws)
            if ws:
                self.lbl_ws_hint.configure(text="")
            nick = cfg.get("nick", "Host")
            self.nick_var.set(nick)
        except Exception:
            pass

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "last_workspace": self.ws_var.get(),
                    "nick": self.nick_var.get(),
                }, f, ensure_ascii=False, indent=2)
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
            self._append(f"\n  📁 작업 폴더: {path}\n", "system")

    # ══════════════════════════════════════════════════════════════
    # 파이프라인 로그 (CENTER)
    # ══════════════════════════════════════════════════════════════
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
        self._append("━" * 58 + "\n", "gray")
        self._append("  AI Nexus  ·  멀티유저 채팅 + 파이프라인 자동화\n", "bold_system")
        self._append("━" * 58 + "\n\n", "gray")
        self._append("  ← 좌측 채팅방에서 대화 후 [AI 분석] 버튼으로 시작\n", "gray")
        self._append("  ↓ 아래 입력창에서 직접 목표를 입력해도 됩니다\n\n", "gray")

    # ══════════════════════════════════════════════════════════════
    # 폴링
    # ══════════════════════════════════════════════════════════════
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
            done = st.get("is_complete", False)
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
            hint = "파이프라인 직접 목표 입력  (Enter로 전송)  —  또는 좌측 채팅에서 AI 분석 실행"
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

        # log_outer 위에 overlay — 채팅 입력창과 레이아웃에 영향 없음
        self.clarify_frame.place(in_=self.log_outer,
                                  relx=0, rely=1.0, relwidth=1.0,
                                  anchor="sw", y=0)
        self.clarify_frame.lift()

        self._append("\n", "gray")
        self._append("  ┌─ Gemini 질문 ──────────────────────────────────────┐\n", "bold_gemini")
        for ln in q.strip().splitlines():
            self._append(f"  │  {ln}\n", "gemini")
        self._append("  └─ 번호별로 답변 후 빈 줄(Enter)로 완료  |  ESC = 건너뛰기 ──┘\n\n", "bold_gemini")

    def _ensure_clarify_shown(self):
        if os.path.exists(CLARIFY_QUEST_FILE) and not self.clarify_mode:
            self._show_clarify()

    def _hide_clarify(self):
        self.clarify_mode = False
        try:
            self.clarify_frame.place_forget()
        except Exception:
            pass

    def _dismiss_clarify(self, event=None):
        """ESC 또는 '건너뛰기' — 빈 답변 기록 후 파이프라인 계속 진행."""
        if not self.clarify_mode:
            return
        try:
            with open(CLARIFY_ANS_FILE, "w", encoding="utf-8") as f:
                f.write("(사용자가 질문을 건너뜀 — AI가 적절히 판단하여 계속 진행)")
        except Exception:
            pass
        self._hide_clarify()
        self._append("  ⏩ 질문 건너뜀 — AI가 자체 판단으로 계속 진행합니다.\n\n", "warn")

    def _stop_from_clarify(self):
        """Clarify 중 파이프라인 완전 중지."""
        self._hide_clarify()
        self._stop()
        # 질문 파일 삭제해 폴링 루프 정리
        try:
            if os.path.exists(CLARIFY_QUEST_FILE):
                os.remove(CLARIFY_QUEST_FILE)
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

    # ══════════════════════════════════════════════════════════════
    # 입력 / 버튼
    # ══════════════════════════════════════════════════════════════
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

    # ══════════════════════════════════════════════════════════════
    # 의도 파악 위저드
    # ══════════════════════════════════════════════════════════════
    def _show_wizard(self):
        if self.wizard_frame is None:
            self._build_wizard_panel()
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
        try:
            ctx = self._compile_context(goal)
            with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
                f.write(ctx)
        except Exception as e:
            self.wz_err_lbl.configure(text=f"⚠  저장 오류: {e}")
            return
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
            "CLARIFY 단계에서 이 문서에 이미 답된 항목은 절대 다시 묻지 마십시오.\n",
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

        wrap = tk.Frame(self.wizard_frame, bg=BG_DARK)
        wrap.pack(fill="both", expand=True)

        self.wz_canvas = tk.Canvas(wrap, bg=BG_DARK, bd=0, highlightthickness=0)
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
        C = BG_PANEL
        D = BG_DARK

        def sec_hdr(text):
            f = tk.Frame(parent, bg=D)
            f.pack(fill="x", padx=20, pady=(18, 4))
            tk.Label(f, text=text, fg=FG_GEMINI, bg=D,
                     font=self.fn_bold).pack(side="left")
            tk.Frame(f, bg=FG_BORDER, height=1).pack(
                side="left", fill="x", expand=True, padx=(10, 0), pady=9)

        def card():
            f = tk.Frame(parent, bg=C, padx=18, pady=12)
            f.pack(fill="x", padx=20, pady=(0, 2))
            return f

        def hint(pf, text):
            tk.Label(pf, text=text, fg=FG_GRAY, bg=C,
                     font=self.fn_small).pack(anchor="w", pady=(0, 8))

        sec_hdr("1 │ 프로젝트 목표  *필수")
        c1 = card()
        hint(c1, "구체적일수록 AI가 정확하게 이해합니다.")
        self.wz_goal = tk.Text(
            c1, bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_ui,
            relief="flat", height=5, wrap="word",
            insertbackground=FG_MAIN, highlightthickness=1,
            highlightbackground=FG_BORDER, highlightcolor=FG_GEMINI,
            padx=10, pady=8)
        self.wz_goal.pack(fill="x")
        self.wz_goal.bind("<Tab>", lambda e: (
            self.wz_goal.tk_focusNext().focus(), "break")[1])

        sec_hdr("2 │ 프로젝트 유형")
        c2 = card()
        self.wz_proj_type = tk.StringVar(value="AI가 판단")
        types = [
            ("🌐 웹 애플리케이션",     "웹 애플리케이션 (프론트+백엔드)"),
            ("⚙️ API / 백엔드 서버",   "REST API / 백엔드 서버"),
            ("🖥️ 데스크톱 프로그램",   "데스크톱 프로그램"),
            ("🤖 스크립트 / 자동화",   "스크립트 / 자동화 도구"),
            ("📊 데이터 분석 / AI",    "데이터 분석 / AI 모델"),
            ("📝 문서 / 콘텐츠",       "문서 / 콘텐츠 작성"),
            ("🔀 AI가 판단",           "AI가 판단"),
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

        sec_hdr("3 │ 기술 스택  (복수 선택)")
        c3 = card()
        hint(c3, "선택 안 하면 AI가 자동 선택")
        self.wz_tech = {}
        techs = [
            "Python", "JavaScript / TypeScript", "React / Next.js",
            "FastAPI / Django / Flask", "Node.js / Express", "Vue / Svelte",
            "SQL 데이터베이스", "NoSQL (MongoDB 등)", "Docker / 컨테이너",
            "AI/ML (PyTorch, sklearn)", "AWS / GCP / Azure SDK", "AI가 선택",
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

        sec_hdr("4 │ 결과물 형태  (복수 선택)")
        c4 = card()
        self.wz_output = {}
        outs = [
            ("✅ 실행 가능한 소스 코드",       "실행 가능한 소스 코드"),
            ("📄 API 명세 / 문서",              "API 명세 / 문서"),
            ("🧪 테스트 코드 포함",             "테스트 코드 포함"),
            ("🐳 배포 설정 (Dockerfile / CI)", "배포 설정 파일"),
            ("📖 사용 설명서",                  "사용 설명서"),
            ("📊 분석 리포트 / 요약",           "분석 리포트"),
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

        sec_hdr("5 │ 품질 수준")
        c5 = card()
        self.wz_quality = tk.StringVar(value="균형")
        qualities = [
            ("🚀 빠른 프로토타입", "빠른 프로토타입",
             "일단 동작하면 OK — 아이디어 확인용"),
            ("⚖️ 균형  ✓ 권장",   "균형",
             "실제 사용 가능한 수준 — 대부분의 프로젝트에 적합"),
            ("💎 프로덕션 품질",   "프로덕션 품질",
             "테스트·보안·최적화까지 — 시간이 걸려도 OK"),
        ]
        for lbl, val, desc in qualities:
            rf = tk.Frame(c5, bg=C, pady=2)
            rf.pack(fill="x")
            tk.Radiobutton(rf, text=lbl, variable=self.wz_quality, value=val,
                           bg=C, fg=FG_MAIN, selectcolor=BG_DARK,
                           activebackground=C, activeforeground=FG_GEMINI,
                           font=self.fn_small, cursor="hand2",
                           ).pack(side="left", padx=4)
            tk.Label(rf, text=f"   {desc}", fg=FG_GRAY, bg=C,
                     font=self.fn_small).pack(side="left")

        sec_hdr("6 │ 실행 / 배포 환경")
        c6 = card()
        self.wz_env = tk.StringVar(value="AI가 결정")
        envs = [
            ("Windows 로컬",       "Windows 로컬"),
            ("Linux 서버",         "Linux 서버"),
            ("Docker 컨테이너",    "Docker 컨테이너"),
            ("클라우드 (AWS/GCP)", "클라우드 (AWS / GCP / Azure)"),
            ("Vercel / Netlify",   "Vercel / Netlify"),
            ("AI가 결정",          "AI가 결정"),
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

        sec_hdr("8 │ 추가 제약사항  (선택)")
        c8 = card()
        hint(c8, "피해야 할 것, 반드시 포함할 것, 참고 링크 등 자유롭게")
        self.wz_notes = tk.Text(
            c8, bg=BG_ENTRY, fg=FG_MAIN, font=self.fn_small,
            relief="flat", height=4, wrap="word",
            insertbackground=FG_MAIN, highlightthickness=1,
            highlightbackground=FG_BORDER, highlightcolor=FG_GEMINI,
            padx=10, pady=8)
        self.wz_notes.pack(fill="x")

        tk.Frame(parent, bg=D, height=24).pack()

    # ══════════════════════════════════════════════════════════════
    # 파이프라인 실행
    # ══════════════════════════════════════════════════════════════
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
        ag_tag  = {"gemini": "ag_gem", "claude": "ag_cla", "codex": "ag_cod"}.get(agent, "ag_cla")

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

    def _reset_project(self):
        """현재 프로젝트 완전 초기화 — 런타임 파일 삭제 + 화면 리셋."""
        # 실행 중인 파이프라인 중지
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc = None

        self._hide_clarify()

        # 삭제할 런타임 파일 목록
        runtime_files = [
            STATE_FILE, PLAN_FILE, QUEUE_FILE,
            CONTEXT_FILE, CLARIFY_QUEST_FILE, CLARIFY_ANS_FILE,
            os.path.join(MANAGER_DIR, "GOAL.md"),
            os.path.join(MANAGER_DIR, "INTAKE.md"),
            os.path.join(MANAGER_DIR, "CONTEXT.md"),
            os.path.join(MANAGER_DIR, "RESEARCH.md"),
            os.path.join(MANAGER_DIR, "DEEP_RESEARCH.md"),
            os.path.join(MANAGER_DIR, "HALLCHECK.md"),
            os.path.join(MANAGER_DIR, "REVISIONS.md"),
            os.path.join(MANAGER_DIR, "CLARIFY_QUESTIONS.md"),
            os.path.join(MANAGER_DIR, "CLARIFICATIONS.md"),
            os.path.join(MANAGER_DIR, "ACCEPTANCE_CRITERIA.md"),
        ]
        deleted = 0
        for fpath in runtime_files:
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
                    deleted += 1
            except Exception:
                pass

        # UI 상태 리셋
        self._state_cache  = ""
        self._plan_cache   = ""
        self._queue_cache  = ""
        self._current_stage = ""
        self._node_rects   = {}

        self._draw_pipeline_canvas("")
        self._clear_activity()
        self.pipe_hdr_lbl.configure(text="  🔄 파이프라인  0 / 13")
        self.btn_send.configure(state="normal")

        # 로그 클리어 후 환영 메시지
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._welcome()
        self._append(f"  🗑 초기화 완료  (파일 {deleted}개 삭제)\n", "system")
        self._append("  새 프로젝트를 시작하세요.\n\n", "gray")

    def _on_close(self):
        self._save_config()
        if self.chat_messages:
            try:
                self._save_chat_log()
            except Exception:
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        if self.server_proc and self.server_proc.poll() is None:
            self.server_proc.terminate()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
