"""
AI Bot 4 - Windows GUI
CustomTkinter tabbed UI.
"""

import customtkinter as ctk
import threading
import queue
import sys
import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

try:
    from ctkdateentry import CTkDateEntry
except ImportError:
    CTkDateEntry = None

# Import bot modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import path_utils
    import runtime_config
    import order_executor
    import simulation_engine
    import config
    import app_logger
    import price_cache
except ImportError as e:
    print(f"Import error: {e}")
    price_cache = None


# Theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Paths (path_utils, PyInstaller-safe)
SCRIPT_DIR = path_utils.get_base_dir()
TRADES_FILE = os.path.join(SCRIPT_DIR, "trades.json")
HISTORY_FILE = os.path.join(SCRIPT_DIR, "signal_history.json")
REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports")
SIM_TRADES_FILE = os.path.join(SCRIPT_DIR, "simulation_trades.json")
SIM_HISTORY_FILE = os.path.join(SCRIPT_DIR, "simulation_signal_history.json")
SIM_ML_PREDICTIONS_FILE = os.path.join(SCRIPT_DIR, "simulation_ml_predictions.jsonl")


class LogRedirector:
    """Redirects stdout/stderr to GUI."""
    
    def __init__(self, log_queue: queue.Queue, original_stream):
        self.log_queue = log_queue
        self.original_stream = original_stream
    
    def write(self, text):
        if text.strip():
            self.log_queue.put(text)
        if self.original_stream:
            self.original_stream.write(text)
    
    def flush(self):
        if self.original_stream:
            self.original_stream.flush()


class AIBotApp(ctk.CTk):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        try:
            app_logger.setup_logging()
        except Exception:
            pass
        self.title("AI Bot 4 - Trading Bot")
        self.geometry("1000x750")
        self.minsize(900, 650)
        
        # Runtime config
        self.rc = runtime_config.get_config()
        
        # Bot thread
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_running = False
        self.stop_event = threading.Event()
        
        # Log queue
        self.log_queue = queue.Queue()
        
        # Build UI
        self._create_ui()
        
        # Log redirect
        sys.stdout = LogRedirector(self.log_queue, sys.__stdout__)
        sys.stderr = LogRedirector(self.log_queue, sys.__stderr__)
        
        # Initial balance refresh
        self._refresh_balance()
        
        # Periodic updates
        self._update_logs()
        self._update_balance_display()
        self._schedule_sim_live_refresh()
        
        # On close
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
    
    def _create_ui(self):
        """Builds main UI."""
        
        # Main grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # === HEADER ===
        self._create_header()
        
        # === TAB VIEW ===
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        
        # Tabs
        self.tab_main = self.tabview.add("Home")
        self.tab_sim = self.tabview.add("Simulation")
        self.tab_stats = self.tabview.add("Statistics")
        self.tab_trades = self.tabview.add("Trades")
        self.tab_reports = self.tabview.add("Reports")
        self.tab_settings = self.tabview.add("Settings")
        
        # Tab contents
        self._create_main_tab()
        self._create_simulation_tab()
        self._create_stats_tab()
        self._create_trades_tab()
        self._create_reports_tab()
        self._create_settings_tab()
        
        # === STATUS BAR ===
        self._create_status_bar()
    
    def _create_header(self):
        """Header section."""
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)
        
        # Title
        title_label = ctk.CTkLabel(
            header_frame, 
            text="🤖 AI Bot 4", 
            font=ctk.CTkFont(size=26, weight="bold")
        )
        title_label.grid(row=0, column=0, sticky="w")
        
        # Controls
        btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_frame.grid(row=0, column=2, sticky="e")
        
        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="Start",
            width=110,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#28a745",
            hover_color="#218838",
            command=self._toggle_bot
        )
        self.start_btn.pack(side="left", padx=5)
        
        # New trades toggle
        self.new_trade_switch = ctk.CTkSwitch(
            btn_frame,
            text="Accept new trades",
            font=ctk.CTkFont(size=12),
            command=self._toggle_new_trades,
            onvalue=True,
            offvalue=False
        )
        self.new_trade_switch.pack(side="left", padx=10)
        if self.rc.allow_new_trades:
            self.new_trade_switch.select()
    
    # ==================== MAIN TAB ====================
    def _create_main_tab(self):
        """Main tab."""
        self.tab_main.grid_columnconfigure(0, weight=1)
        self.tab_main.grid_rowconfigure(1, weight=1)
        
        # Top - settings
        settings_frame = ctk.CTkFrame(self.tab_main)
        settings_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        for i in range(6):
            settings_frame.grid_columnconfigure(i, weight=1)
        
        # === BALANCE ===
        balance_frame = ctk.CTkFrame(settings_frame, fg_color=("#e8f5e9", "#1b4332"))
        balance_frame.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(balance_frame, text="Balance",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        self.balance_label = ctk.CTkLabel(balance_frame, text="Current: -- USDT",
                                          font=ctk.CTkFont(size=15))
        self.balance_label.pack(pady=1)
        
        self.pnl_label = ctk.CTkLabel(balance_frame, text="P&L: -- USDT (---%)",
                                      font=ctk.CTkFont(size=12))
        self.pnl_label.pack(pady=1)
        
        self.next_trade_label = ctk.CTkLabel(balance_frame, text="Next trade: -- USDT",
                                             font=ctk.CTkFont(size=11))
        self.next_trade_label.pack(pady=(1, 8))
        
        ctk.CTkButton(balance_frame, text="Refresh", width=90,
                      command=self._refresh_balance).pack(pady=(3, 8))
        
        # === API ===
        api_frame = ctk.CTkFrame(settings_frame)
        api_frame.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(api_frame, text="API settings",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        self.api_key_entry = ctk.CTkEntry(api_frame, placeholder_text="API Key", width=180, show="•")
        self.api_key_entry.pack(pady=3, padx=8)
        
        self.api_secret_entry = ctk.CTkEntry(api_frame, placeholder_text="API Secret", width=180, show="•")
        self.api_secret_entry.pack(pady=3, padx=8)
        
        # Load saved values
        if self.rc.api_key:
            self.api_key_entry.insert(0, self.rc.api_key)
        if self.rc.api_secret:
            self.api_secret_entry.insert(0, self.rc.api_secret)
        
        ctk.CTkButton(api_frame, text="Save", width=90,
                      command=self._save_api_keys).pack(pady=(3, 8))
        
        # === TRADE SETTINGS ===
        trade_frame = ctk.CTkFrame(settings_frame)
        trade_frame.grid(row=0, column=2, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(trade_frame, text="Trade settings",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        init_frame = ctk.CTkFrame(trade_frame, fg_color="transparent")
        init_frame.pack(pady=3, padx=8, fill="x")
        ctk.CTkLabel(init_frame, text="Start $:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.initial_balance_entry = ctk.CTkEntry(init_frame, width=90)
        self.initial_balance_entry.pack(side="right")
        
        self.fixed_trade_switch = ctk.CTkSwitch(
            trade_frame,
            text="Use fixed amount",
            font=ctk.CTkFont(size=11),
            command=self._toggle_fixed_trade_amount
        )
        self.fixed_trade_switch.pack(pady=3, padx=8)
        if self.rc.use_fixed_trade_amount:
            self.fixed_trade_switch.select()
        
        pct_frame = ctk.CTkFrame(trade_frame, fg_color="transparent")
        pct_frame.pack(pady=3, padx=8, fill="x")
        ctk.CTkLabel(pct_frame, text="Trade %:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.trade_pct_entry = ctk.CTkEntry(pct_frame, width=90)
        self.trade_pct_entry.pack(side="right")
        
        fixed_frame = ctk.CTkFrame(trade_frame, fg_color="transparent")
        fixed_frame.pack(pady=3, padx=8, fill="x")
        ctk.CTkLabel(fixed_frame, text="Fixed amount ($):", font=ctk.CTkFont(size=11)).pack(side="left")
        self.fixed_trade_entry = ctk.CTkEntry(fixed_frame, width=90, placeholder_text="10")
        self.fixed_trade_entry.pack(side="right")
        
        # Load saved values
        if self.rc.initial_balance > 0:
            self.initial_balance_entry.insert(0, str(self.rc.initial_balance))
        self.trade_pct_entry.insert(0, str(int(self.rc.trade_percent * 100)))
        self.fixed_trade_entry.insert(0, str(self.rc.fixed_trade_amount_usdt))
        
        # Toggle-dependent entry state
        self._update_trade_mode_inputs()
        
        ctk.CTkButton(trade_frame, text="Apply", width=90,
                      command=self._save_trade_settings).pack(pady=(3, 8))
        
        # === STATUS ===
        status_frame = ctk.CTkFrame(settings_frame)
        status_frame.grid(row=0, column=3, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(status_frame, text="Bot status",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        self.status_label = ctk.CTkLabel(status_frame, text="Stopped",
                                         font=ctk.CTkFont(size=15))
        self.status_label.pack(pady=3)
        
        self.trade_mode_label = ctk.CTkLabel(status_frame, 
                                             text="Mode: Test" if not self.rc.auto_trade else "Mode: Live",
                                             font=ctk.CTkFont(size=11))
        self.trade_mode_label.pack(pady=1)
        
        self.auto_trade_switch = ctk.CTkSwitch(status_frame, text="Live trading",
                                               font=ctk.CTkFont(size=11),
                                               command=self._toggle_auto_trade)
        self.auto_trade_switch.pack(pady=(3, 2))
        if self.rc.auto_trade:
            self.auto_trade_switch.select()

        self.sim_mode_switch = ctk.CTkSwitch(status_frame, text="Simulation mode",
                                             font=ctk.CTkFont(size=11),
                                             command=self._toggle_simulation_mode)
        self.sim_mode_switch.pack(pady=(2, 2))
        if self.rc.simulation_mode:
            self.sim_mode_switch.select()

        ctk.CTkButton(status_frame, text="Simulation settings", width=130, height=26,
                      font=ctk.CTkFont(size=10),
                      command=self._open_simulation_settings).pack(pady=(2, 8))

        # === ML ===
        ml_frame = ctk.CTkFrame(settings_frame)
        ml_frame.grid(row=0, column=4, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(ml_frame, text="ML settings",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        self.ml_threshold_switch = ctk.CTkSwitch(
            ml_frame, 
            text="Custom threshold",
            font=ctk.CTkFont(size=11),
            command=self._toggle_ml_threshold
        )
        self.ml_threshold_switch.pack(pady=3)
        if self.rc.use_custom_ml_threshold:
            self.ml_threshold_switch.select()

        self.ml_threshold_entry = ctk.CTkEntry(ml_frame, width=60, placeholder_text="0.52")
        self.ml_threshold_entry.pack(pady=3)
        self.ml_threshold_entry.insert(0, str(self.rc.ml_threshold))
        
        # Entry state update
        self.ml_threshold_entry.configure(state="normal" if self.rc.use_custom_ml_threshold else "disabled")

        ctk.CTkButton(ml_frame, text="Save", width=80, height=24,
                      command=self._save_ml_settings).pack(pady=(3, 8))
        
        # === TP/SL ===
        tpsl_frame = ctk.CTkFrame(settings_frame, fg_color=("#fff3e0", "#3e2723"))
        tpsl_frame.grid(row=0, column=5, padx=8, pady=8, sticky="nsew")
        
        ctk.CTkLabel(tpsl_frame, text="TP/SL settings",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(8, 3))
        
        sl_row = ctk.CTkFrame(tpsl_frame, fg_color="transparent")
        sl_row.pack(pady=2, padx=8, fill="x")
        ctk.CTkLabel(sl_row, text="SL %:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.sl_pct_entry = ctk.CTkEntry(sl_row, width=60)
        self.sl_pct_entry.pack(side="right")
        self.sl_pct_entry.insert(0, str(self.rc.sl_pct))
        
        tp1_row = ctk.CTkFrame(tpsl_frame, fg_color="transparent")
        tp1_row.pack(pady=2, padx=8, fill="x")
        ctk.CTkLabel(tp1_row, text="TP1 %:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.tp1_pct_entry = ctk.CTkEntry(tp1_row, width=60)
        self.tp1_pct_entry.pack(side="right")
        self.tp1_pct_entry.insert(0, str(self.rc.tp1_pct))
        
        tp2_row = ctk.CTkFrame(tpsl_frame, fg_color="transparent")
        tp2_row.pack(pady=2, padx=8, fill="x")
        ctk.CTkLabel(tp2_row, text="TP2 %:", font=ctk.CTkFont(size=11)).pack(side="left")
        self.tp2_pct_entry = ctk.CTkEntry(tp2_row, width=60)
        self.tp2_pct_entry.pack(side="right")
        self.tp2_pct_entry.insert(0, str(self.rc.tp2_pct))
        
        ctk.CTkButton(tpsl_frame, text="Save", width=80, height=24,
                      command=self._save_tpsl_settings).pack(pady=(3, 8))
        
        # Log panel
        self.tab_main.grid_rowconfigure(1, weight=1)
        log_frame = ctk.CTkFrame(self.tab_main)
        log_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)
        
        header = ctk.CTkFrame(log_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=3)
        
        ctk.CTkLabel(header, text="Bot logs",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Clear", width=70, height=26,
                      command=self._clear_logs).pack(side="right")
        
        self.log_textbox = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.log_textbox.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")
        
        # Highlight for live Binance log lines
        self.log_textbox._textbox.tag_configure("binance_real", foreground="#FFD700", background="#8B0000", font=("Consolas", 11, "bold"))
    
    # ==================== SIMULATION TAB ====================
    def _create_simulation_tab(self):
        """Simulation tab with Trades and Live sub-tabs."""
        self.tab_sim.grid_columnconfigure(0, weight=1)
        self.tab_sim.grid_rowconfigure(0, weight=1)
        
        # Sub-tabs
        self.sim_subtabview = ctk.CTkTabview(self.tab_sim)
        self.sim_subtabview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        self.sim_subtab_trades = self.sim_subtabview.add("Trades")
        self.sim_subtab_live = self.sim_subtabview.add("Live positions")
        
        # --- Trades sub-tab ---
        self.sim_subtab_trades.grid_columnconfigure(0, weight=1)
        self.sim_subtab_trades.grid_rowconfigure(1, weight=1)
        
        sim_header = ctk.CTkFrame(self.sim_subtab_trades, fg_color="transparent")
        sim_header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        sim_header.grid_columnconfigure(0, weight=1)
        
        row1 = ctk.CTkFrame(sim_header, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(row1, text="Simulation trade history",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkLabel(row1, text="Date:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(20, 5))
        if CTkDateEntry:
            self.sim_trades_date_from = CTkDateEntry(row1, width=115, height=28)
        else:
            self.sim_trades_date_from = ctk.CTkEntry(row1, width=100, placeholder_text="YYYY-MM-DD")
        self.sim_trades_date_from.pack(side="left", padx=2)
        ctk.CTkLabel(row1, text="—").pack(side="left", padx=2)
        if CTkDateEntry:
            self.sim_trades_date_to = CTkDateEntry(row1, width=115, height=28)
        else:
            self.sim_trades_date_to = ctk.CTkEntry(row1, width=100, placeholder_text="YYYY-MM-DD")
        self.sim_trades_date_to.pack(side="left", padx=2)
        self.sim_trades_filter_type = ctk.CTkOptionMenu(row1, width=130,
            values=["Open date", "Close date"])
        self.sim_trades_filter_type.pack(side="left", padx=5)
        
        row2 = ctk.CTkFrame(sim_header, fg_color="transparent")
        row2.pack(fill="x")
        ctk.CTkLabel(row2, text="View:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 5))
        self.sim_trades_view_filter = ctk.CTkOptionMenu(row2, width=130,
            values=["All", "Open only", "Closed only"])
        self.sim_trades_view_filter.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="Outcome:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(15, 5))
        self.sim_trades_result_filter = ctk.CTkOptionMenu(row2, width=100,
            values=["All", "Win", "BL", "Lose"])
        self.sim_trades_result_filter.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="ML confidence min:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(15, 5))
        self.sim_trades_ml_min = ctk.CTkEntry(row2, width=70, placeholder_text="0.50")
        self.sim_trades_ml_min.pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Reset", width=70,
                      command=self._reset_sim_trades_filter).pack(side="left", padx=(15, 2))
        ctk.CTkButton(row2, text="Refresh", width=100,
                      command=self._refresh_sim_trades).pack(side="left", padx=5)
        
        self.sim_trades_textbox = ctk.CTkTextbox(self.sim_subtab_trades,
                                                font=ctk.CTkFont(family="Consolas", size=11))
        self.sim_trades_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # --- Live positions sub-tab ---
        self.sim_subtab_live.grid_columnconfigure(0, weight=1)
        self.sim_subtab_live.grid_rowconfigure(1, weight=1)
        
        live_header = ctk.CTkFrame(self.sim_subtab_live, fg_color="transparent")
        live_header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        live_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(live_header, text="📡 Live positions (Binance-style)",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        ctk.CTkButton(live_header, text="Refresh", width=100,
                     command=self._refresh_sim_live_positions).pack(side="right", padx=5)
        
        self.sim_live_scrollframe = ctk.CTkScrollableFrame(self.sim_subtab_live,
                                                           fg_color="transparent")
        self.sim_live_scrollframe.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # Initial refresh
        self.after(500, self._refresh_sim_trades)
        self.after(600, self._refresh_sim_live_positions)
    
    # ==================== STATISTICS TAB ====================
    def _create_stats_tab(self):
        """Statistics tab."""
        self.tab_stats.grid_columnconfigure(0, weight=1)
        self.tab_stats.grid_columnconfigure(1, weight=1)
        self.tab_stats.grid_rowconfigure(0, weight=1)
        
        # Left - general stats
        left_frame = ctk.CTkFrame(self.tab_stats)
        left_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        stats_title_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        stats_title_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(stats_title_frame, text="General statistics",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        self.sim_stats_switch = ctk.CTkSwitch(stats_title_frame, text="Simulation",
                                              font=ctk.CTkFont(size=11),
                                              command=self._refresh_stats)
        self.sim_stats_switch.pack(side="right", padx=5)
        
        # Date filter card
        filter_card = ctk.CTkFrame(left_frame, fg_color=("#e8e8e8", "#2d2d2d"), corner_radius=8)
        filter_card.pack(fill="x", padx=15, pady=(0, 12))
        filter_card.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(filter_card, text="Date range",
                      font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(8, 4))
        row1 = ctk.CTkFrame(filter_card, fg_color="transparent")
        row1.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=2)
        row1.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row1, text="Start", font=ctk.CTkFont(size=10)).grid(row=0, column=0, padx=(0, 5), sticky="w")
        if CTkDateEntry:
            self.stats_date_from = CTkDateEntry(row1, width=115, height=28)
        else:
            self.stats_date_from = ctk.CTkEntry(row1, width=95, placeholder_text="YYYY-MM-DD")
        self.stats_date_from.grid(row=0, column=1, padx=(0, 15))
        ctk.CTkLabel(row1, text="End", font=ctk.CTkFont(size=10)).grid(row=0, column=2, padx=(0, 5), sticky="w")
        if CTkDateEntry:
            self.stats_date_to = CTkDateEntry(row1, width=115, height=28)
        else:
            self.stats_date_to = ctk.CTkEntry(row1, width=95, placeholder_text="YYYY-MM-DD")
        self.stats_date_to.grid(row=0, column=3, sticky="w")
        
        row2 = ctk.CTkFrame(filter_card, fg_color="transparent")
        row2.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(2, 4))
        row2.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row2, text="Filter by", font=ctk.CTkFont(size=10)).grid(row=0, column=0, padx=(0, 5), sticky="w")
        self.stats_filter_type = ctk.CTkOptionMenu(row2, width=130,
            values=["Open date", "Close date"])
        self.stats_filter_type.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(row2, text="ML confidence min:", font=ctk.CTkFont(size=10)).grid(row=0, column=2, padx=(15, 5), sticky="w")
        self.stats_ml_min = ctk.CTkEntry(row2, width=70, placeholder_text="0.50")
        self.stats_ml_min.grid(row=0, column=3, sticky="w")
        row3 = ctk.CTkFrame(filter_card, fg_color="transparent")
        row3.grid(row=3, column=0, columnspan=4, sticky="ew", padx=10, pady=(2, 8))
        row3.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row3, text="Source:", font=ctk.CTkFont(size=10)).grid(row=0, column=0, padx=(0, 5), sticky="w")
        self.stats_source_filter = ctk.CTkOptionMenu(row3, width=130,
            values=["All", "Live Binance", "Shadow"])
        self.stats_source_filter.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(row3, text="Reset", width=65,
                      command=self._reset_stats_filter).grid(row=0, column=2, padx=(15, 2), sticky="e")
        ctk.CTkButton(row3, text="Refresh", width=95,
                      command=self._refresh_stats).grid(row=0, column=3, padx=2, sticky="e")
        
        self.stats_labels = {}
        stats_items = [
            ("sim_balance_start", "Start balance:"),
            ("sim_balance_current", "Current balance:"),
            ("sim_balance_pnl", "Balance P&L:"),
            ("total_trades", "Total trades:"),
            ("open_trades", "Open trades:"),
            ("wins", "Wins:"),
            ("losses", "Losses:"),
            ("breakeven", "Breakeven:"),
            ("win_rate", "Win Rate:"),
            ("total_pnl", "Total P&L:"),
            ("avg_pnl", "Avg P&L:")
        ]
        
        for key, label in stats_items:
            frame = ctk.CTkFrame(left_frame, fg_color="transparent")
            frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left")
            self.stats_labels[key] = ctk.CTkLabel(frame, text="--", font=ctk.CTkFont(size=13, weight="bold"))
            self.stats_labels[key].pack(side="right")
            if key == "sim_balance_current":
                def _refresh_sim_balance():
                    try:
                        simulation_engine.get_engine().sync_balance_from_history()
                    except Exception:
                        pass
                    self._refresh_stats()
                self.stats_balance_refresh_btn = ctk.CTkButton(frame, text="Refresh", width=70,
                                                               command=_refresh_sim_balance)
                self.stats_balance_refresh_btn.pack(side="right", padx=(8, 0))

        self._sim_stat_keys = {"sim_balance_start", "sim_balance_current", "sim_balance_pnl"}
        self._update_sim_stats_visibility()
        
        # Right - ML stats
        right_frame = ctk.CTkFrame(self.tab_stats)
        right_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(right_frame, text="ML statistics",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 10))
        
        self.ml_stats_labels = {}
        ml_stats_items = [
            ("ml_total", "Total predictions:"),
            ("ml_accepted", "Accepted:"),
            ("ml_rejected", "Rejected:"),
            ("ml_accept_rate", "Accept rate:"),
            ("shadow_total", "Shadow trades:"),
            ("shadow_wins", "Shadow wins:"),
            ("shadow_losses", "Shadow losses:")
        ]
        
        for key, label in ml_stats_items:
            frame = ctk.CTkFrame(right_frame, fg_color="transparent")
            frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=13)).pack(side="left")
            self.ml_stats_labels[key] = ctk.CTkLabel(frame, text="--", font=ctk.CTkFont(size=13, weight="bold"))
            self.ml_stats_labels[key].pack(side="right")
        
        # Initial refresh
        self.after(1000, self._refresh_stats)
    
    # ==================== TRADES TAB ====================
    def _create_trades_tab(self):
        """Trades tab."""
        self.tab_trades.grid_columnconfigure(0, weight=1)
        self.tab_trades.grid_rowconfigure(1, weight=1)
        
        # Header
        header = ctk.CTkFrame(self.tab_trades, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        
        # Row: title + dates
        row1 = ctk.CTkFrame(header, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 4))
        
        ctk.CTkLabel(row1, text="Trade history",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        
        ctk.CTkLabel(row1, text="Date:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(20, 5))
        if CTkDateEntry:
            self.trades_date_from = CTkDateEntry(row1, width=115, height=28)
        else:
            self.trades_date_from = ctk.CTkEntry(row1, width=100, placeholder_text="YYYY-MM-DD")
        self.trades_date_from.pack(side="left", padx=2)
        ctk.CTkLabel(row1, text="—").pack(side="left", padx=2)
        if CTkDateEntry:
            self.trades_date_to = CTkDateEntry(row1, width=115, height=28)
        else:
            self.trades_date_to = ctk.CTkEntry(row1, width=100, placeholder_text="YYYY-MM-DD")
        self.trades_date_to.pack(side="left", padx=2)
        self.trades_filter_type = ctk.CTkOptionMenu(row1, width=130,
            values=["Open date", "Close date"])
        self.trades_filter_type.pack(side="left", padx=5)
        
        # Row: source + ML + buttons
        row2 = ctk.CTkFrame(header, fg_color="transparent")
        row2.pack(fill="x")
        
        ctk.CTkLabel(row2, text="Source:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 5))
        self.trades_source_filter = ctk.CTkOptionMenu(row2, width=130,
            values=["All", "Live Binance", "Shadow"])
        self.trades_source_filter.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="Outcome:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(15, 5))
        self.trades_result_filter = ctk.CTkOptionMenu(row2, width=100,
            values=["All", "Win", "BL", "Lose"])
        self.trades_result_filter.pack(side="left", padx=2)
        ctk.CTkLabel(row2, text="ML confidence min:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(15, 5))
        self.trades_ml_min = ctk.CTkEntry(row2, width=70, placeholder_text="0.50")
        self.trades_ml_min.pack(side="left", padx=2)
        ctk.CTkButton(row2, text="Reset", width=70,
                      command=self._reset_trades_filter).pack(side="left", padx=(15, 2))
        ctk.CTkButton(row2, text="Refresh", width=100,
                      command=self._refresh_trades).pack(side="left", padx=5)
        
        # Trade list
        self.trades_textbox = ctk.CTkTextbox(self.tab_trades, 
                                             font=ctk.CTkFont(family="Consolas", size=11))
        self.trades_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # Initial refresh
        self.after(1500, self._refresh_trades)
    
    # ==================== REPORTS TAB ====================
    def _create_reports_tab(self):
        """Reports tab."""
        self.tab_reports.grid_columnconfigure(0, weight=1)
        self.tab_reports.grid_rowconfigure(1, weight=1)
        
        # Header
        header = ctk.CTkFrame(self.tab_reports, fg_color="transparent")
        header.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        ctk.CTkLabel(header, text="Excel reports",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        
        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.pack(side="right")
        
        ctk.CTkButton(btn_frame, text="📊 /excel", width=100,
                      command=lambda: self._load_report("excel")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🤖 /excelai", width=100,
                      command=lambda: self._load_report("excelai")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Refresh", width=80,
                      command=self._refresh_reports).pack(side="left", padx=5)
        
        # Report content
        self.reports_textbox = ctk.CTkTextbox(self.tab_reports,
                                              font=ctk.CTkFont(family="Consolas", size=11))
        self.reports_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        
        # Initial refresh
        self.after(2000, self._refresh_reports)
    
    def _create_status_bar(self):
        """Status bar."""
        status_bar = ctk.CTkFrame(self, height=28, fg_color=("#d0d0d0", "#2b2b2b"))
        status_bar.grid(row=2, column=0, sticky="ew")
        
        self.status_bar_label = ctk.CTkLabel(status_bar, text="Ready", font=ctk.CTkFont(size=10))
        self.status_bar_label.pack(side="left", padx=10)
        
        self.time_label = ctk.CTkLabel(status_bar, text=datetime.now().strftime("%H:%M:%S"),
                                       font=ctk.CTkFont(size=10))
        self.time_label.pack(side="right", padx=10)
        
        self._update_time()
    
    # ==================== SETTINGS TAB ====================
    def _create_settings_tab(self):
        """Advanced settings tab."""
        self.tab_settings.grid_columnconfigure(0, weight=1)
        self.tab_settings.grid_rowconfigure(1, weight=1)
        
        # Title
        ctk.CTkLabel(self.tab_settings, text="⚙️ Advanced settings",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
        
        # Container
        content = ctk.CTkFrame(self.tab_settings)
        content.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        
        # === SLIPPAGE BUFFER ===
        buffer_frame = ctk.CTkFrame(content, fg_color=("#e3f2fd", "#1a237e"))
        buffer_frame.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(buffer_frame, text="🛡️ Slippage buffer settings",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(15, 5))
        
        ctk.CTkLabel(buffer_frame,
                     text="Moves SL toward the market to offset slippage on\nSTOP_MARKET orders.",
                     font=ctk.CTkFont(size=11),
                     text_color=("#546e7a", "#b0bec5"),
                     justify="center").pack(pady=(0, 12))
        
        # Initial SL buffer
        sl_buf_row = ctk.CTkFrame(buffer_frame, fg_color="transparent")
        sl_buf_row.pack(pady=6, padx=20, fill="x")
        ctk.CTkLabel(sl_buf_row, text="Initial SL buffer %:", 
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.sl_buffer_entry = ctk.CTkEntry(sl_buf_row, width=80)
        self.sl_buffer_entry.pack(side="right")
        self.sl_buffer_entry.insert(0, str(self.rc.sl_buffer_pct))
        
        ctk.CTkLabel(sl_buf_row, text="(suggested: 0.03)",
                     font=ctk.CTkFont(size=10),
                     text_color=("#78909c", "#90a4ae")).pack(side="right", padx=8)
        
        # BE SL buffer
        be_buf_row = ctk.CTkFrame(buffer_frame, fg_color="transparent")
        be_buf_row.pack(pady=6, padx=20, fill="x")
        ctk.CTkLabel(be_buf_row, text="BE SL buffer %:", 
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.be_buffer_entry = ctk.CTkEntry(be_buf_row, width=80)
        self.be_buffer_entry.pack(side="right")
        self.be_buffer_entry.insert(0, str(self.rc.be_buffer_pct))
        
        ctk.CTkLabel(be_buf_row, text="(suggested: 0.08)",
                     font=ctk.CTkFont(size=10),
                     text_color=("#78909c", "#90a4ae")).pack(side="right", padx=8)
        
        # Info
        info_frame = ctk.CTkFrame(buffer_frame, fg_color=("#e8eaf6", "#283593"), corner_radius=8)
        info_frame.pack(pady=(10, 5), padx=20, fill="x")
        
        ctk.CTkLabel(info_frame,
                     text="Buffer nudges the stop toward the market:\n"
                          "LONG → SL moved slightly up\n"
                          "SHORT → SL moved slightly down\n"
                          "0 = buffer off (no slippage offset)",
                     font=ctk.CTkFont(size=10),
                     justify="left").pack(padx=12, pady=8)
        
        ctk.CTkButton(buffer_frame, text="Save", width=120, height=32,
                      fg_color="#1565c0", hover_color="#0d47a1",
                      command=self._save_buffer_settings).pack(pady=(8, 15))
        
        # === MULTI-TRADE ===
        multi_trade_frame = ctk.CTkFrame(content, fg_color=("#e8f5e9", "#1b5e20"))
        multi_trade_frame.grid(row=0, column=1, padx=15, pady=15, sticky="nsew")
        
        ctk.CTkLabel(multi_trade_frame, text="📊 Multi-trade settings",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(15, 5))
        
        ctk.CTkLabel(multi_trade_frame,
                     text="Allows multiple same-direction trades\non the same symbol.",
                     font=ctk.CTkFont(size=11),
                     text_color=("#546e7a", "#b0bec5"),
                     justify="center").pack(pady=(0, 12))
        
        # Max trades per coin
        max_trades_row = ctk.CTkFrame(multi_trade_frame, fg_color="transparent")
        max_trades_row.pack(pady=6, padx=20, fill="x")
        ctk.CTkLabel(max_trades_row, text="Max trades per coin:", 
                     font=ctk.CTkFont(size=13)).pack(side="left")
        self.max_trades_entry = ctk.CTkEntry(max_trades_row, width=80)
        self.max_trades_entry.pack(side="right")
        self.max_trades_entry.insert(0, str(self.rc.max_trades_per_coin))
        
        ctk.CTkLabel(max_trades_row, text="(1-10)",
                     font=ctk.CTkFont(size=10),
                     text_color=("#78909c", "#90a4ae")).pack(side="right", padx=8)
        
        # Info
        info_frame2 = ctk.CTkFrame(multi_trade_frame, fg_color=("#c8e6c9", "#2e7d32"), corner_radius=8)
        info_frame2.pack(pady=(10, 5), padx=20, fill="x")
        
        ctk.CTkLabel(info_frame2,
                     text="Rules:\n"
                          "- Only stacks same direction (LONG+LONG or SHORT+SHORT)\n"
                          "- Each trade has its own TP/SL\n"
                          "- Opposite signals are skipped\n"
                          "- 1 = legacy (one trade per coin)",
                     font=ctk.CTkFont(size=10),
                     justify="left").pack(padx=12, pady=8)
        
        ctk.CTkButton(multi_trade_frame, text="Save", width=120, height=32,
                      fg_color="#2e7d32", hover_color="#1b5e20",
                      command=self._save_multi_trade_settings).pack(pady=(8, 15))
    
    # ==================== DATA REFRESH ====================
    
    def _parse_date_or_none(self, s) -> Optional[object]:
        """Returns None for empty input, else a date.
        Supported formats: YYYY-MM-DD, DD/MM/YYYY, DD.MM.YYYY"""
        if s is None or (isinstance(s, str) and not str(s).strip()):
            return None
        val = str(s).strip()
        if not val:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(val, fmt).date()
            except (ValueError, TypeError):
                continue
        return None
    
    def _get_date_from_widget(self, widget):
        """Reads date string from Entry or CTkDateEntry."""
        if CTkDateEntry and isinstance(widget, CTkDateEntry):
            return widget.variable.get() if hasattr(widget, 'variable') else ""
        return widget.get() if hasattr(widget, 'get') else ""
    
    def _signal_in_date_range(self, signal: dict, date_from, date_to, use_close: bool) -> bool:
        """Whether signal falls in the date range."""
        if date_from is None and date_to is None:
            return True
        time_str = signal.get('close_time') if use_close else signal.get('start_time')
        if not time_str:
            return False
        try:
            sig_date = datetime.strptime(str(time_str).strip()[:10], "%Y-%m-%d").date()
            if date_from is not None and sig_date < date_from:
                return False
            if date_to is not None and sig_date > date_to:
                return False
            return True
        except (ValueError, TypeError):
            return False
    
    def _prediction_in_date_range(self, record: dict, date_from, date_to) -> bool:
        """Whether ML prediction record falls in the date range."""
        if date_from is None and date_to is None:
            return True
        ts = record.get('timestamp', '')
        if not ts:
            return False
        try:
            pred_date = datetime.fromisoformat(ts.replace('Z', '+00:00')).date()
            if date_from is not None and pred_date < date_from:
                return False
            if date_to is not None and pred_date > date_to:
                return False
            return True
        except (ValueError, TypeError):
            return False
    
    def _load_ml_predictions(self) -> List[dict]:
        """Reads ml_predictions.jsonl into a list."""
        ml_file = os.path.join(SCRIPT_DIR, "ml_predictions.jsonl")
        if not os.path.exists(ml_file):
            return []
        predictions = []
        try:
            with open(ml_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            if isinstance(rec, dict):
                                predictions.append(rec)
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass
        return predictions
    
    def _parse_signal_start_time(self, s: str) -> Optional[datetime]:
        """Parses signal start_time to datetime, e.g. '2026-02-12 14:33:54'"""
        if not s or not isinstance(s, str):
            return None
        val = str(s).strip()
        if not val:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                part = val[:19] if len(val) >= 19 else val[:10]
                return datetime.strptime(part, fmt)
            except (ValueError, TypeError):
                continue
        return None
    
    def _get_confidence_for_signal(self, symbol: str, start_time_str: str, 
                                    predictions: List[dict]) -> Optional[float]:
        """
        Best ML confidence for (symbol + start_time) within ~4h; prefers accepted=true.
        """
        start_dt = self._parse_signal_start_time(start_time_str)
        if start_dt is None:
            return None
        candidates = []
        for p in predictions:
            if p.get('symbol') != symbol:
                continue
            ts = p.get('timestamp', '')
            if not ts:
                continue
            try:
                pred_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                diff = abs((pred_dt.replace(tzinfo=None) if pred_dt.tzinfo else pred_dt) - start_dt)
                if isinstance(diff, timedelta) and diff <= timedelta(hours=4):
                    candidates.append((p, diff))
            except (ValueError, TypeError):
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda x: (0 if x[0].get('accepted') else 1, x[1]))
        return candidates[0][0].get('confidence')
    
    def _parse_ml_min_filter(self, widget) -> Optional[float]:
        """ML min confidence from widget; None if empty/invalid."""
        val = widget.get() if hasattr(widget, 'get') else ""
        if val is None or (isinstance(val, str) and not str(val).strip()):
            return None
        try:
            f = float(str(val).strip().replace(",", "."))
            return max(0.0, min(1.0, f)) if 0 <= f <= 1 else None
        except (ValueError, TypeError):
            return None
    
    def _reset_stats_filter(self):
        """Clears stats date and ML filters."""
        for w in (self.stats_date_from, self.stats_date_to):
            if CTkDateEntry and isinstance(w, CTkDateEntry):
                w.variable.set("")
            elif hasattr(w, 'delete'):
                w.delete(0, "end")
        if hasattr(self, 'stats_ml_min') and hasattr(self.stats_ml_min, 'delete'):
            self.stats_ml_min.delete(0, "end")
        self._refresh_stats()
    
    def _refresh_simulation_stats(self):
        """Refreshes simulation statistics."""
        try:
            sim = simulation_engine.get_engine()
            stats = sim.get_stats()

            self.stats_labels["sim_balance_start"].configure(
                text=f"{stats['starting_balance']:.2f} USDT")
            self.stats_labels["sim_balance_current"].configure(
                text=f"{stats['current_balance']:.2f} USDT")
            pnl_text = f"{stats['balance_pnl']:+.2f} USDT ({stats['balance_pnl_pct']:+.1f}%)"
            self.stats_labels["sim_balance_pnl"].configure(
                text=pnl_text,
                text_color="#28a745" if stats['balance_pnl'] >= 0 else "#dc3545")

            self.stats_labels["total_trades"].configure(text=str(stats['total_trades']))
            self.stats_labels["open_trades"].configure(text=str(stats['open_trades']))
            self.stats_labels["wins"].configure(text=str(stats['wins']), text_color="#28a745")
            self.stats_labels["losses"].configure(text=str(stats['losses']), text_color="#dc3545")
            self.stats_labels["breakeven"].configure(text=str(stats['breakeven']), text_color="#ffc107")
            self.stats_labels["win_rate"].configure(text=f"{stats['win_rate']:.1f}%")
            self.stats_labels["total_pnl"].configure(
                text=f"{stats['total_pnl_pct']:+.2f}%",
                text_color="#28a745" if stats['total_pnl_pct'] >= 0 else "#dc3545")
            self.stats_labels["avg_pnl"].configure(text=f"{stats['avg_pnl_pct']:+.2f}%")

            sim_ml_file = os.path.join(SCRIPT_DIR, "simulation_ml_predictions.jsonl")
            if os.path.exists(sim_ml_file):
                predictions = []
                with open(sim_ml_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                predictions.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass
                accepted = len([p for p in predictions if p.get('accepted')])
                rejected = len([p for p in predictions if not p.get('accepted')])
                self.ml_stats_labels["ml_total"].configure(text=str(len(predictions)))
                self.ml_stats_labels["ml_accepted"].configure(text=str(accepted))
                self.ml_stats_labels["ml_rejected"].configure(text=str(rejected))
                self.ml_stats_labels["ml_accept_rate"].configure(
                    text=f"{accepted/len(predictions)*100:.1f}%" if predictions else "--")
            else:
                for k in ["ml_total", "ml_accepted", "ml_rejected", "ml_accept_rate"]:
                    self.ml_stats_labels[k].configure(text="--")

            # Shadow istatistikleri: ml_predictions.jsonl'den (reddedilen sinyaller)
            ml_file = os.path.join(SCRIPT_DIR, "ml_predictions.jsonl")
            if os.path.exists(ml_file):
                shadow_preds = []
                date_from = self._parse_date_or_none(self._get_date_from_widget(self.stats_date_from) if hasattr(self, 'stats_date_from') else None)
                date_to = self._parse_date_or_none(self._get_date_from_widget(self.stats_date_to) if hasattr(self, 'stats_date_to') else None)
                ml_min = self._parse_ml_min_filter(self.stats_ml_min) if hasattr(self, 'stats_ml_min') else None
                with open(ml_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                rec = json.loads(line)
                                if isinstance(rec, dict) and rec.get('outcome_source') == 'shadow':
                                    if self._prediction_in_date_range(rec, date_from, date_to):
                                        if ml_min is None or (rec.get('confidence') or 0) >= ml_min:
                                            shadow_preds.append(rec)
                            except json.JSONDecodeError:
                                pass
                shadow_wins = len([p for p in shadow_preds if 'win' in (p.get('outcome') or '') or 'tp' in (p.get('outcome') or '')])
                shadow_losses = len([p for p in shadow_preds if p.get('outcome') == 'would_lose'])
                self.ml_stats_labels["shadow_total"].configure(text=str(len(shadow_preds)))
                self.ml_stats_labels["shadow_wins"].configure(text=str(shadow_wins), text_color="#28a745")
                self.ml_stats_labels["shadow_losses"].configure(text=str(shadow_losses), text_color="#dc3545")
            else:
                for k in ["shadow_total", "shadow_wins", "shadow_losses"]:
                    self.ml_stats_labels[k].configure(text="--")

        except Exception as e:
            print(f"Simulation stats error: {e}")

    def _refresh_stats(self):
        """Refreshes statistics."""
        self._update_sim_stats_visibility()
        show_sim = bool(self.sim_stats_switch.get()) if hasattr(self, 'sim_stats_switch') else False

        if show_sim:
            self._refresh_simulation_stats()
            return

        for key in self._sim_stat_keys:
            if key in self.stats_labels:
                self.stats_labels[key].configure(text="--")

        try:
            date_from = self._parse_date_or_none(self._get_date_from_widget(self.stats_date_from) if hasattr(self, 'stats_date_from') else None)
            date_to = self._parse_date_or_none(self._get_date_from_widget(self.stats_date_to) if hasattr(self, 'stats_date_to') else None)
            use_close = hasattr(self, 'stats_filter_type') and self.stats_filter_type.get() == "Close date"
            ml_min = self._parse_ml_min_filter(self.stats_ml_min) if hasattr(self, 'stats_ml_min') else None
            predictions_all = self._load_ml_predictions() if ml_min is not None else []
            
            # Signal history'den istatistikler
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        signals = []
                    else:
                        signals = data.get('signals', [])
                    
                    signals = [s for s in signals if isinstance(s, dict) and self._signal_in_date_range(s, date_from, date_to, use_close)]
                    
                    # Trade source filtreleme
                    source_filter = self.stats_source_filter.get() if hasattr(self, 'stats_source_filter') else "All"
                    if source_filter == "Live Binance":
                        signals = [s for s in signals if s.get('trade_source', 'binance') == 'binance']
                    elif source_filter == "Shadow":
                        signals = [s for s in signals if s.get('trade_source') == 'shadow']
                    
                    if ml_min is not None:
                        signals = [s for s in signals if (self._get_confidence_for_signal(
                            s.get('symbol', ''), s.get('start_time', ''), predictions_all) or 0) >= ml_min]
                    closed = [s for s in signals if s.get('status') == 'CLOSED']
                    open_trades = [s for s in signals if s.get('status') == 'OPEN']
                    
                    wins = len([s for s in closed if (s.get('profit_pct') or 0) > 0])
                    losses = len([s for s in closed if (s.get('profit_pct') or 0) < 0])
                    breakeven = len([s for s in closed if (s.get('profit_pct') or 0) == 0])
                    
                    total_pnl = sum(s.get('profit_pct', 0) or 0 for s in closed)
                    avg_pnl = total_pnl / len(closed) if closed else 0
                    win_rate = (wins / len(closed) * 100) if closed else 0
                    
                    self.stats_labels["total_trades"].configure(text=str(len(signals)))
                    self.stats_labels["open_trades"].configure(text=str(len(open_trades)))
                    self.stats_labels["wins"].configure(text=str(wins), text_color="#28a745")
                    self.stats_labels["losses"].configure(text=str(losses), text_color="#dc3545")
                    self.stats_labels["breakeven"].configure(text=str(breakeven), text_color="#ffc107")
                    self.stats_labels["win_rate"].configure(text=f"{win_rate:.1f}%")
                    self.stats_labels["total_pnl"].configure(text=f"{total_pnl:+.2f}%",
                                                            text_color="#28a745" if total_pnl >= 0 else "#dc3545")
                    self.stats_labels["avg_pnl"].configure(text=f"{avg_pnl:+.2f}%")
            
            # ML predictions'dan istatistikler
            ml_file = os.path.join(SCRIPT_DIR, "ml_predictions.jsonl")
            if os.path.exists(ml_file):
                predictions = []
                with open(ml_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                rec = json.loads(line)
                                if isinstance(rec, dict) and self._prediction_in_date_range(rec, date_from, date_to):
                                    if ml_min is None or (rec.get('confidence') or 0) >= ml_min:
                                        predictions.append(rec)
                            except json.JSONDecodeError:
                                pass
                
                accepted = len([p for p in predictions if p.get('accepted')])
                rejected = len([p for p in predictions if not p.get('accepted')])
                shadow = [p for p in predictions if p.get('outcome_source') == 'shadow']
                shadow_wins = len([p for p in shadow if 'win' in (p.get('outcome') or '') or 'tp' in (p.get('outcome') or '')])
                shadow_losses = len([p for p in shadow if p.get('outcome') == 'would_lose'])
                
                self.ml_stats_labels["ml_total"].configure(text=str(len(predictions)))
                self.ml_stats_labels["ml_accepted"].configure(text=str(accepted))
                self.ml_stats_labels["ml_rejected"].configure(text=str(rejected))
                self.ml_stats_labels["ml_accept_rate"].configure(
                    text=f"{accepted/len(predictions)*100:.1f}%" if predictions else "--")
                self.ml_stats_labels["shadow_total"].configure(text=str(len(shadow)))
                self.ml_stats_labels["shadow_wins"].configure(text=str(shadow_wins), text_color="#28a745")
                self.ml_stats_labels["shadow_losses"].configure(text=str(shadow_losses), text_color="#dc3545")
                
        except Exception as e:
            print(f"Stats update error: {e}")
    
    def _reset_trades_filter(self):
        """Clears trades filters."""
        for w in (self.trades_date_from, self.trades_date_to):
            if CTkDateEntry and isinstance(w, CTkDateEntry):
                w.variable.set("")
            elif hasattr(w, 'delete'):
                w.delete(0, "end")
        if hasattr(self, 'trades_ml_min') and hasattr(self.trades_ml_min, 'delete'):
            self.trades_ml_min.delete(0, "end")
        if hasattr(self, 'trades_result_filter'):
            self.trades_result_filter.set("All")
        self._refresh_trades()
    
    def _refresh_trades(self):
        """Refreshes trade list."""
        try:
            self.trades_textbox.delete("1.0", "end")
            
            date_from = self._parse_date_or_none(self._get_date_from_widget(self.trades_date_from) if hasattr(self, 'trades_date_from') else None)
            date_to = self._parse_date_or_none(self._get_date_from_widget(self.trades_date_to) if hasattr(self, 'trades_date_to') else None)
            use_close = hasattr(self, 'trades_filter_type') and self.trades_filter_type.get() == "Close date"
            ml_min = self._parse_ml_min_filter(self.trades_ml_min) if hasattr(self, 'trades_ml_min') else None
            source_filter = self.trades_source_filter.get() if hasattr(self, 'trades_source_filter') else "All"
            predictions = self._load_ml_predictions()
            
            # Open trades (Live Binance or All only)
            if source_filter != "Shadow" and os.path.exists(TRADES_FILE):
                with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                    trades = json.load(f)
                    if isinstance(trades, dict) and trades:
                        open_list = []
                        for s, val in trades.items():
                            if isinstance(val, list):
                                for t in val:
                                    if isinstance(t, dict) and t.get('status') == 'OPEN':
                                        open_list.append((s, t))
                            elif isinstance(val, dict) and val.get('status') == 'OPEN':
                                open_list.append((s, val))
                        if ml_min is not None:
                            open_list = [(s, t) for s, t in open_list
                                        if (self._get_confidence_for_signal(s, t.get('start_time', ''), predictions) or 0) >= ml_min]
                        if open_list:
                            self.trades_textbox.insert("end", "═══ OPEN POSITIONS ═══\n\n")
                            for symbol, trade in open_list:
                                tid = trade.get('trade_id', trade.get('signal_id', '?'))
                                amt = trade.get('amount', '-')
                                self.trades_textbox.insert("end", 
                                    f"📌 {symbol} | {trade.get('signal')} | Entry: {trade.get('entry')} | Size: {amt}\n"
                                    f"   SL: {trade.get('sl')} | TP1: {trade.get('tp1')} | TP2: {trade.get('tp2')}\n"
                                    f"   Opened: {trade.get('start_time')} | TP1 Hit: {trade.get('tp1_hit')} | ID: {tid}\n\n")
            
            # Closed trades
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        signals = []
                    else:
                        signals = data.get('signals', [])
                    closed = [s for s in signals if isinstance(s, dict) and s.get('status') == 'CLOSED'
                              and self._signal_in_date_range(s, date_from, date_to, use_close)]
                    
                    # Trade source filtreleme
                    if source_filter == "Live Binance":
                        closed = [s for s in closed if s.get('trade_source', 'binance') == 'binance']
                    elif source_filter == "Shadow":
                        closed = [s for s in closed if s.get('trade_source') == 'shadow']
                    
                    if ml_min is not None:
                        closed = [s for s in closed if (self._get_confidence_for_signal(
                            s.get('symbol', ''), s.get('start_time', ''), predictions) or 0) >= ml_min]
                    result_filter = self.trades_result_filter.get() if hasattr(self, 'trades_result_filter') else "All"
                    be_band = getattr(simulation_engine, 'BREAKEVEN_BAND_PCT', 0.5)
                    if result_filter == "Win":
                        closed = [s for s in closed if (s.get('profit_pct') or 0) > be_band]
                    elif result_filter == "BL":
                        closed = [s for s in closed
                                  if s.get('profit_pct') is not None
                                  and -be_band <= (s.get('profit_pct') or 0) <= be_band]
                    elif result_filter == "Lose":
                        closed = [s for s in closed if (s.get('profit_pct') or 0) < -be_band]
                    closed.reverse()  # Newest first
                    
                    self.trades_textbox.insert("end", f"\n═══ CLOSED TRADES ({len(closed)}) ═══\n\n")
                    
                    for signal in closed[:50]:  # Last 50 trades
                        profit = signal.get('profit_pct', 0) or 0
                        be_band = getattr(simulation_engine, 'BREAKEVEN_BAND_PCT', 0.5)
                        is_be = -be_band <= profit <= be_band
                        emoji = "✅" if profit > be_band else ("⚠️" if is_be else "❌")
                        conf = self._get_confidence_for_signal(signal.get('symbol', ''), signal.get('start_time', ''), predictions)
                        conf_str = f" | Conf: {conf:.2f}" if conf is not None else ""
                        
                        # Trade source tag
                        trade_src = signal.get('trade_source', 'binance')
                        if trade_src == 'shadow':
                            src_tag = "👻 SHADOW"
                        else:
                            src_tag = "LIVE"
                        
                        # Exit price
                        close_price = signal.get('close_price')
                        exit_str = f" → Exit: {close_price}" if close_price else ""
                        
                        self.trades_textbox.insert("end",
                            f"{emoji} [{src_tag}] {signal.get('symbol')} | {signal.get('signal')} | {signal.get('close_reason')}{conf_str}\n"
                            f"   Entry: {signal.get('entry')}{exit_str} | P&L: {profit:+.2f}%\n"
                            f"   {signal.get('start_time')} → {signal.get('close_time')}\n\n")
                            
        except Exception as e:
            self.trades_textbox.insert("end", f"Error: {e}")
    
    def _refresh_reports(self):
        """Refreshes report list."""
        try:
            self.reports_textbox.delete("1.0", "end")
            
            if os.path.exists(REPORTS_DIR):
                files = sorted(Path(REPORTS_DIR).glob("*.xlsx"), key=os.path.getmtime, reverse=True)
                
                self.reports_textbox.insert("end", "═══ AVAILABLE REPORTS ═══\n\n")
                
                for f in files[:20]:
                    mtime = datetime.fromtimestamp(os.path.getmtime(f))
                    size = os.path.getsize(f) / 1024
                    self.reports_textbox.insert("end",
                        f"📊 {f.name}\n"
                        f"   Date: {mtime.strftime('%Y-%m-%d %H:%M')} | Size: {size:.1f} KB\n\n")
                
                if not files:
                    self.reports_textbox.insert("end", "No reports generated yet.\n")
            else:
                self.reports_textbox.insert("end", "Reports folder not found.\n")
                
        except Exception as e:
            self.reports_textbox.insert("end", f"Error: {e}")
    
    def _load_report(self, report_type: str):
        """Generate report via telegram_commands."""
        self._log(f"📊 {report_type} report is being generated...")
        
        def generate():
            try:
                import telegram_commands
                if report_type == "excel":
                    telegram_commands.generate_excel_report()
                else:
                    telegram_commands.generate_ai_performance_report()
                self.after(0, self._refresh_reports)
                self._log(f"✅ {report_type} report generated!")
            except Exception as e:
                self._log(f"❌ Report error: {e}")
        
        threading.Thread(target=generate, daemon=True).start()
    
    # ==================== EVENT HANDLERS ====================
    
    def _toggle_bot(self):
        if not self.bot_running:
            self._start_bot()
        else:
            self._stop_bot()
    
    def _start_bot(self):
        self.bot_running = True
        self.stop_event.clear()
        
        self.start_btn.configure(text="Stop", fg_color="#dc3545", hover_color="#c82333")
        self.status_label.configure(text="Running")
        self.status_bar_label.configure(text="Bot running...")
        
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()
        
        try:
            app_logger.get_logger(__name__).info("Bot started")
        except Exception:
            pass
        self._log("✅ Bot started")
    
    def _stop_bot(self):
        self.bot_running = False
        self.stop_event.set()
        
        self.start_btn.configure(text="Start", fg_color="#28a745", hover_color="#218838")
        self.status_label.configure(text="Stopped")
        self.status_bar_label.configure(text="Bot stopped")
        
        try:
            app_logger.get_logger(__name__).info("Bot stopped")
        except Exception:
            pass
        self._log("Bot stopped")
    
    def _run_bot(self):
        try:
            import main
            main.run_bot()
        except Exception as e:
            try:
                app_logger.get_logger(__name__).exception("Bot error")
            except Exception:
                pass
            self._log(f"❌ Bot error: {e}")
            self.after(0, self._stop_bot)
    
    def _toggle_new_trades(self):
        self.rc.allow_new_trades = self.new_trade_switch.get()
        self.rc.save_to_file()
        
        if self.rc.allow_new_trades:
            self._log("✅ Accepting new trades ON")
        else:
            self._log("⚠️ Accepting new trades OFF")
    
    def _toggle_auto_trade(self):
        self.rc.auto_trade = self.auto_trade_switch.get()
        self.rc.save_to_file()

        if self.rc.auto_trade and hasattr(self, 'sim_mode_switch'):
            self.sim_mode_switch.deselect()

        mode_text = "Live" if self.rc.auto_trade else "Test"
        self.trade_mode_label.configure(text=f"Mode: {mode_text}")

        if self.rc.auto_trade:
            self._log("LIVE TRADING MODE ON!")
        else:
            self._log("Test mode active")
    
    def _toggle_simulation_mode(self):
        is_sim = bool(self.sim_mode_switch.get())
        self.rc.simulation_mode = is_sim
        self.rc.save_to_file()

        if is_sim:
            self.auto_trade_switch.deselect()
            self.trade_mode_label.configure(text="Mode: Simulation")
            if self.rc.simulation_current_balance <= 0:
                self.rc.reset_simulation()
            self._log("Simulation mode ON")
            if hasattr(self, '_refresh_sim_trades'):
                self._refresh_sim_trades()
            if hasattr(self, '_refresh_sim_live_positions'):
                self._refresh_sim_live_positions()
        else:
            self.trade_mode_label.configure(text="Mode: Test")
            self._log("Simulation mode off")

    def _open_simulation_settings(self):
        """Simulation settings popup."""
        popup = ctk.CTkToplevel(self)
        popup.title("Simulation settings")
        popup.geometry("380x340")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        ctk.CTkLabel(popup, text="Simulation settings",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(15, 10))

        row1 = ctk.CTkFrame(popup, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row1, text="Starting balance (USDT):", font=ctk.CTkFont(size=12)).pack(side="left")
        sim_balance_entry = ctk.CTkEntry(row1, width=100)
        sim_balance_entry.pack(side="right")
        sim_balance_entry.insert(0, str(self.rc.simulation_balance))

        sim_fixed_switch = ctk.CTkSwitch(popup, text="Use fixed amount",
                                         font=ctk.CTkFont(size=12))
        sim_fixed_switch.pack(pady=5, padx=20)
        if self.rc.simulation_use_fixed_amount:
            sim_fixed_switch.select()

        row2 = ctk.CTkFrame(popup, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row2, text="Fixed amount (USDT):", font=ctk.CTkFont(size=12)).pack(side="left")
        sim_fixed_entry = ctk.CTkEntry(row2, width=100)
        sim_fixed_entry.pack(side="right")
        sim_fixed_entry.insert(0, str(self.rc.simulation_fixed_amount))

        row3 = ctk.CTkFrame(popup, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(row3, text="Trade percent (%):", font=ctk.CTkFont(size=12)).pack(side="left")
        sim_pct_entry = ctk.CTkEntry(row3, width=100)
        sim_pct_entry.pack(side="right")
        sim_pct_entry.insert(0, str(int(self.rc.simulation_trade_percent * 100)))

        def save_sim_settings():
            try:
                bal = float(sim_balance_entry.get() or 10000)
                self.rc.simulation_balance = max(1, bal)
                self.rc.simulation_use_fixed_amount = bool(sim_fixed_switch.get())
                self.rc.simulation_fixed_amount = float(sim_fixed_entry.get() or 100)
                pct_val = float(sim_pct_entry.get() or 5) / 100
                self.rc.simulation_trade_percent = pct_val
                self.rc.save_to_file()
                self._log(f"Simulation settings saved: Bakiye={bal}, "
                          f"Sabit={'Yes' if self.rc.simulation_use_fixed_amount else 'No'}")
                popup.destroy()
            except ValueError:
                self._log("Invalid value")

        def reset_sim():
            self.rc.reset_simulation()
            self.rc.save_to_file()
            self._log(f"Simulation reset: {self.rc.simulation_balance} USDT")
            popup.destroy()

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(pady=15)

        ctk.CTkButton(btn_frame, text="Save", width=120,
                      fg_color="#28a745", hover_color="#218838",
                      command=save_sim_settings).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Reset", width=120,
                      fg_color="#dc3545", hover_color="#c82333",
                      command=reset_sim).pack(side="left", padx=5)

    def _reset_sim_trades_filter(self):
        """Reset simulation trade filters."""
        for w in (self.sim_trades_date_from, self.sim_trades_date_to):
            if CTkDateEntry and isinstance(w, CTkDateEntry):
                try:
                    w.variable.set("")
                except Exception:
                    pass
            elif hasattr(w, 'delete'):
                w.delete(0, "end")
        if hasattr(self, 'sim_trades_ml_min') and hasattr(self.sim_trades_ml_min, 'delete'):
            self.sim_trades_ml_min.delete(0, "end")
        if hasattr(self, 'sim_trades_result_filter'):
            self.sim_trades_result_filter.set("All")
        self._refresh_sim_trades()

    def _load_sim_ml_predictions(self) -> List[dict]:
        """Reads simulation_ml_predictions.jsonl."""
        if not os.path.exists(SIM_ML_PREDICTIONS_FILE):
            return []
        predictions = []
        try:
            with open(SIM_ML_PREDICTIONS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            if isinstance(rec, dict):
                                predictions.append(rec)
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass
        return predictions

    def _sim_signal_in_date_range(self, signal: dict, date_from, date_to, use_close: bool) -> bool:
        """Whether sim signal is in date range."""
        if date_from is None and date_to is None:
            return True
        time_str = signal.get('close_time') if use_close else signal.get('start_time')
        if not time_str:
            return False
        try:
            sig_date = datetime.strptime(str(time_str).strip()[:10], "%Y-%m-%d").date()
            if date_from is not None and sig_date < date_from:
                return False
            if date_to is not None and sig_date > date_to:
                return False
            return True
        except (ValueError, TypeError):
            return False

    def _get_confidence_for_sim_signal(self, symbol: str, start_time_str: str,
                                       predictions: List[dict]) -> Optional[float]:
        """ML confidence for sim trade from history or predictions."""
        # Prefer ml_confidence on signal_history when present
        # Match predictions by symbol + timestamp (~4h window)
        start_dt = self._parse_signal_start_time(start_time_str)
        if start_dt is None:
            return None
        candidates = []
        for p in predictions:
            if p.get('symbol') != symbol:
                continue
            ts = p.get('timestamp', '')
            if not ts:
                continue
            try:
                pred_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                diff = abs((pred_dt.replace(tzinfo=None) if pred_dt.tzinfo else pred_dt) - start_dt)
                if isinstance(diff, timedelta) and diff <= timedelta(hours=4):
                    candidates.append((p, diff))
            except (ValueError, TypeError):
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda x: (0 if x[0].get('accepted') else 1, x[1]))
        return candidates[0][0].get('confidence')

    def _refresh_sim_trades(self):
        """Refreshes simulation trade history."""
        try:
            if not hasattr(self, 'sim_trades_textbox'):
                return
            self.sim_trades_textbox.delete("1.0", "end")

            if not self.rc.simulation_mode:
                self.sim_trades_textbox.insert("end", "Enable simulation mode.\n")
                return

            date_from = self._parse_date_or_none(
                self._get_date_from_widget(self.sim_trades_date_from) if hasattr(self, 'sim_trades_date_from') else None)
            date_to = self._parse_date_or_none(
                self._get_date_from_widget(self.sim_trades_date_to) if hasattr(self, 'sim_trades_date_to') else None)
            use_close = hasattr(self, 'sim_trades_filter_type') and self.sim_trades_filter_type.get() == "Close date"
            ml_min = self._parse_ml_min_filter(self.sim_trades_ml_min) if hasattr(self, 'sim_trades_ml_min') else None
            view_filter = self.sim_trades_view_filter.get() if hasattr(self, 'sim_trades_view_filter') else "All"
            predictions = self._load_sim_ml_predictions()

            sim = simulation_engine.get_engine()
            all_open = sim.get_open_trades()
            closed = []

            # Open positions
            if view_filter in ("All", "Open only") and all_open:
                open_ml_map = {}
                if os.path.exists(SIM_HISTORY_FILE):
                    try:
                        with open(SIM_HISTORY_FILE, 'r', encoding='utf-8') as f:
                            hist_data = json.load(f)
                            for s in (hist_data.get('signals') or []):
                                if isinstance(s, dict) and s.get('status') == 'OPEN':
                                    sid = s.get('signal_id')
                                    mc = s.get('ml_confidence')
                                    if sid and isinstance(mc, (int, float)):
                                        open_ml_map[sid] = mc
                    except Exception:
                        pass
                open_list = []
                for symbol, trades in all_open.items():
                    trades_sorted = sorted(trades, key=lambda t: t.get('start_time', ''))
                    for idx, t in enumerate(trades_sorted, 1):
                        tid = t.get('trade_id') or t.get('signal_id')
                        conf = open_ml_map.get(tid) if tid else None
                        if conf is None:
                            conf = self._get_confidence_for_sim_signal(
                                symbol, t.get('start_time', ''), predictions)
                        if isinstance(conf, (int, float)):
                            conf = float(conf)
                        elif conf is not None:
                            conf = float(conf)
                        if ml_min is not None and (conf or 0) < ml_min:
                            continue
                        open_list.append((symbol, t, idx, conf))
                if open_list:
                    self.sim_trades_textbox.insert("end", "═══ OPEN POSITIONS ═══\n\n")
                    for symbol, t, idx, conf in open_list:
                        entry = t.get("entry", 0)
                        notional = t.get("notional_usdt", 0)
                        direction = t.get("signal", "?")
                        sl, tp1, tp2 = t.get("sl"), t.get("tp1"), t.get("tp2")
                        st = t.get("start_time", "")
                        conf_str = f" | ML: {conf:.2f}" if conf is not None else ""
                        self.sim_trades_textbox.insert("end",
                            f"📌 {symbol} #{idx} | {direction} | Entry: {entry:.6f} | "
                            f"Notional: {notional:.2f} USDT{conf_str}\n"
                            f"   SL: {sl} | TP1: {tp1} | TP2: {tp2} | {st}\n\n")

            # Closed trades
            if view_filter in ("All", "Closed only") and os.path.exists(SIM_HISTORY_FILE):
                with open(SIM_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        signals = []
                    else:
                        signals = data.get('signals', [])
                    closed = [s for s in signals if isinstance(s, dict) and s.get('status') == 'CLOSED'
                              and self._sim_signal_in_date_range(s, date_from, date_to, use_close)]
                    if ml_min is not None:
                        closed = [s for s in closed if (self._get_confidence_for_sim_signal(
                            s.get('symbol', ''), s.get('start_time', ''), predictions) or 0) >= ml_min]
                    result_filter = self.sim_trades_result_filter.get() if hasattr(self, 'sim_trades_result_filter') else "All"
                    be_band = getattr(simulation_engine, 'BREAKEVEN_BAND_PCT', 0.5)
                    if result_filter == "Win":
                        closed = [s for s in closed if (s.get('profit_pct') or 0) > be_band]
                    elif result_filter == "BL":
                        closed = [s for s in closed
                                  if s.get('profit_pct') is not None
                                  and -be_band <= (s.get('profit_pct') or 0) <= be_band]
                    elif result_filter == "Lose":
                        closed = [s for s in closed if (s.get('profit_pct') or 0) < -be_band]
                    closed.reverse()
                    self.sim_trades_textbox.insert("end", f"\n═══ CLOSED TRADES ({len(closed)}) ═══\n\n")
                    for signal in closed[:100]:
                        profit = signal.get('profit_pct', 0) or 0
                        be_band = getattr(simulation_engine, 'BREAKEVEN_BAND_PCT', 0.5)
                        is_be = -be_band <= profit <= be_band
                        emoji = "✅" if profit > be_band else ("⚠️" if is_be else "❌")
                        conf = signal.get('ml_confidence')
                        if conf == "-" or not isinstance(conf, (int, float)):
                            conf = self._get_confidence_for_sim_signal(
                                signal.get('symbol', ''), signal.get('start_time', ''), predictions)
                        conf_str = f" | ML: {conf:.2f}" if conf is not None and isinstance(conf, (int, float)) else ""
                        close_reason = signal.get('close_reason', '')
                        close_price = signal.get('close_price')
                        exit_str = f" → Exit: {close_price}" if close_price else ""
                        self.sim_trades_textbox.insert("end",
                            f"{emoji} {signal.get('symbol')} | {signal.get('signal', '')} | "
                            f"{close_reason} | P&L: {profit:+.2f}%{conf_str}\n"
                            f"   Entry: {signal.get('entry')}{exit_str}\n"
                            f"   {signal.get('start_time')} → {signal.get('close_time')}\n\n")

            if not all_open and not (os.path.exists(SIM_HISTORY_FILE) and closed):
                rc = self._get_rc_safe()
                if rc:
                    self.sim_trades_textbox.insert("end", f"Balance: {rc.simulation_current_balance:.2f} USDT\n")
                self.sim_trades_textbox.insert("end", "No simulation trades found.\n")

        except Exception as e:
            if hasattr(self, 'sim_trades_textbox'):
                self.sim_trades_textbox.insert("end", f"Error: {e}")
            else:
                print(f"Sim trades refresh error: {e}")

    def _add_live_table_row(self, parent, values: List[str], is_header: bool = False):
        """Adds a table row (8 columns)."""
        row_f = ctk.CTkFrame(parent, fg_color=("#e8e8e8", "#2d2d2d") if is_header else "transparent")
        row_f.pack(fill="x", pady=1)
        widths = [95, 120, 55, 48, 80, 95, 72, 78]
        for i, (val, w) in enumerate(zip(values, widths)):
            row_f.grid_columnconfigure(i, minsize=w)
            lbl = ctk.CTkLabel(row_f, text=str(val)[:20], width=w, anchor="w",
                               font=ctk.CTkFont(size=11, weight="bold" if is_header else "normal"),
                               fg_color=("gray85", "gray25") if is_header else "transparent")
            lbl.grid(row=0, column=i, padx=2, pady=3, sticky="w")

    def _refresh_sim_live_positions(self):
        """Updates live position table (Binance-style)."""
        try:
            if not hasattr(self, 'sim_live_scrollframe'):
                return
            for child in self.sim_live_scrollframe.winfo_children():
                child.destroy()

            if not self.rc.simulation_mode:
                ctk.CTkLabel(self.sim_live_scrollframe, text="Enable simulation mode.",
                            font=ctk.CTkFont(size=13)).pack(pady=20)
                return

            sim = simulation_engine.get_engine()
            stats = sim.get_stats()
            balance_frame = ctk.CTkFrame(self.sim_live_scrollframe, fg_color="transparent")
            balance_frame.pack(fill="x", pady=(0, 10))
            bal_cur = f"{stats['current_balance']:.2f} USDT"
            pnl_col = "#28a745" if stats['balance_pnl'] >= 0 else "#dc3545"
            pnl_txt = f"{stats['balance_pnl']:+.2f} USDT ({stats['balance_pnl_pct']:+.1f}%)"
            ctk.CTkLabel(balance_frame, text="Live balance:",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(balance_frame, text=bal_cur,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 20))
            ctk.CTkLabel(balance_frame, text="Balance P&L:",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(balance_frame, text=pnl_txt, text_color=pnl_col,
                         font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

            all_open = sim.get_open_trades()
            if not all_open:
                ctk.CTkLabel(self.sim_live_scrollframe,
                            text="No open simulation positions.",
                            font=ctk.CTkFont(size=13)).pack(pady=20)
                return

            prices = {}
            if price_cache:
                prices = price_cache.get_all_prices()

            open_ml_map = {}
            if os.path.exists(SIM_HISTORY_FILE):
                try:
                    with open(SIM_HISTORY_FILE, 'r', encoding='utf-8') as f:
                        hist_data = json.load(f)
                        for s in (hist_data.get('signals') or []):
                            if isinstance(s, dict) and s.get('status') == 'OPEN':
                                sid = s.get('signal_id')
                                mc = s.get('ml_confidence')
                                if sid and isinstance(mc, (int, float)):
                                    open_ml_map[sid] = mc
                except Exception:
                    pass

            self._add_live_table_row(self.sim_live_scrollframe,
                ["Symbol", "Time", "ML", "Count", "Total", "Price", "PnL %", "PnL USDT"],
                is_header=True)

            for symbol, trades in sorted(all_open.items()):
                trades_sorted = sorted(trades, key=lambda t: t.get('start_time', ''))
                current_price = prices.get(symbol) if prices else None
                pnl_data = sim.calculate_unrealized_pnl(symbol, current_price or 0) if current_price else {}

                total_notional = sum(t.get('notional_usdt', 0) for t in trades_sorted)
                ml_vals = []
                for t in trades_sorted:
                    tid = t.get('trade_id') or t.get('signal_id')
                    v = open_ml_map.get(tid) if tid else t.get('ml_confidence')
                    if isinstance(v, (int, float)):
                        ml_vals.append(v)
                ml_avg = sum(ml_vals) / len(ml_vals) if ml_vals else None
                st_first = (trades_sorted[0].get('start_time', '') or '')[:16] if trades_sorted else ''

                pnl_pct = pnl_data.get('unrealized_pnl_pct', 0) if pnl_data else 0
                pnl_usdt = pnl_data.get('unrealized_pnl_usdt', 0) if pnl_data else 0
                price_str = f"{current_price:.6f}" if current_price else "--"
                pnl_pct_str = f"{pnl_pct:+.2f}%" if current_price else "--"
                pnl_usdt_str = f"{pnl_usdt:+.2f}" if current_price else "--"
                ml_str = f"{ml_avg:.2f}" if ml_avg is not None else "--"

                self._add_live_table_row(self.sim_live_scrollframe, [
                    symbol, st_first, ml_str, str(len(trades_sorted)),
                    f"{total_notional:.2f}", price_str, pnl_pct_str, pnl_usdt_str
                ], is_header=False)

                for idx, t in enumerate(trades_sorted, 1):
                    entry = t.get("entry", 0)
                    sl, tp1, tp2 = t.get("sl"), t.get("tp1"), t.get("tp2")
                    notional = t.get("notional_usdt", 0)
                    if current_price and entry:
                        pct = (current_price - entry) / entry * 100 if "LONG" in str(t.get("signal", "")) else (entry - current_price) / entry * 100
                        pct_str = f"{pct:+.2f}%"
                    else:
                        pct_str = "--"
                    self._add_live_table_row(self.sim_live_scrollframe, [
                        f"  #{idx}", f"{entry:.6f}", f"{sl}", f"{tp1}", f"{tp2}",
                        pct_str, f"{notional:.2f}", ""
                    ], is_header=False)

            if not prices and self.bot_running:
                tip = ctk.CTkLabel(self.sim_live_scrollframe,
                    text="Prices refresh every ~5s. If the bot is running, wait a moment.",
                    font=ctk.CTkFont(size=10), text_color=("gray50", "gray60"))
                tip.pack(pady=8)
            elif not prices:
                tip = ctk.CTkLabel(self.sim_live_scrollframe,
                    text="Start the bot for live prices.",
                    font=ctk.CTkFont(size=10), text_color=("gray50", "gray60"))
                tip.pack(pady=8)

        except Exception as e:
            if hasattr(self, 'sim_live_scrollframe'):
                ctk.CTkLabel(self.sim_live_scrollframe, text=f"Error: {e}",
                            font=ctk.CTkFont(size=12), text_color="#dc3545").pack(pady=20)

    def _schedule_sim_live_refresh(self):
        """Every 5s refresh live sim positions and balance labels."""
        try:
            if self.rc.simulation_mode:
                if hasattr(self, '_refresh_sim_live_positions'):
                    self._refresh_sim_live_positions()
                self._refresh_sim_balance_display()
        except Exception:
            pass
        self.after(5000, self._schedule_sim_live_refresh)

    def _refresh_sim_balance_display(self):
        """Updates balance labels only."""
        try:
            if not (hasattr(self, 'stats_labels') and 'sim_balance_current' in self.stats_labels):
                return
            sim = simulation_engine.get_engine()
            sim.sync_balance_from_history()
            stats = sim.get_stats()
            self.stats_labels["sim_balance_current"].configure(
                text=f"{stats['current_balance']:.2f} USDT")
            pnl_text = f"{stats['balance_pnl']:+.2f} USDT ({stats['balance_pnl_pct']:+.1f}%)"
            self.stats_labels["sim_balance_pnl"].configure(
                text=pnl_text,
                text_color="#28a745" if stats['balance_pnl'] >= 0 else "#dc3545")
        except Exception:
            pass

    def _get_rc_safe(self):
        try:
            return runtime_config.get_config()
        except Exception:
            return None

    def _update_sim_stats_visibility(self):
        """Toggles simulation stat row visibility."""
        show_sim = bool(self.sim_stats_switch.get()) if hasattr(self, 'sim_stats_switch') else False
        for key in self._sim_stat_keys:
            widget = self.stats_labels.get(key)
            if widget:
                parent = widget.master
                if show_sim:
                    parent.pack(fill="x", padx=20, pady=5)
                else:
                    parent.pack_forget()

    def _save_api_keys(self):
        self.rc.api_key = self.api_key_entry.get()
        self.rc.api_secret = self.api_secret_entry.get()
        self.rc.save_to_file()
        self._log("API settings saved")
        self._refresh_balance()
    
    def _toggle_fixed_trade_amount(self):
        """Enables/disables inputs for fixed-amount mode."""
        self._update_trade_mode_inputs()
    
    def _update_trade_mode_inputs(self):
        """Updates input state for trade mode."""
        use_fixed = self.fixed_trade_switch.get()
        self.trade_pct_entry.configure(state="disabled" if use_fixed else "normal")
        self.fixed_trade_entry.configure(state="normal" if use_fixed else "disabled")
    
    def _save_trade_settings(self):
        try:
            initial = float(self.initial_balance_entry.get() or 0)
            use_fixed = self.fixed_trade_switch.get()
            
            self.rc.initial_balance = initial
            self.rc.use_fixed_trade_amount = use_fixed
            
            if use_fixed:
                fixed_val = float(self.fixed_trade_entry.get() or 10)
                self.rc.fixed_trade_amount_usdt = max(1.0, fixed_val)
                self.rc.save_to_file()
                self._log(f"Settings saved: ${initial}, Sabit: ${self.rc.fixed_trade_amount_usdt:.0f}")
            else:
                pct = float(self.trade_pct_entry.get() or 5) / 100
                self.rc.trade_percent = pct
                self.rc.save_to_file()
                self._log(f"Settings saved: ${initial}, {pct*100:.0f}%")
            
            self._update_balance_display()
        except ValueError:
            self._log("Invalid value")
            
    def _toggle_ml_threshold(self):
        is_active = self.ml_threshold_switch.get()
        self.ml_threshold_entry.configure(state="normal" if is_active else "disabled")
        if not is_active:
             # Revert to default display (0.52); not saved until Save
             pass

    def _save_ml_settings(self):
        try:
            use_custom = self.ml_threshold_switch.get()
            threshold_val = float(self.ml_threshold_entry.get())
            
            # Clamp to [0, 1]
            threshold_val = max(0.0, min(1.0, threshold_val))
            
            self.rc.use_custom_ml_threshold = use_custom
            self.rc.ml_threshold = threshold_val
            self.rc.save_to_file()
            
            status = "ON" if use_custom else "OFF"
            self._log(f"ML settings: {status} ({threshold_val})")
            
            # Normalize entry text to clamped value
            self.ml_threshold_entry.delete(0, "end")
            self.ml_threshold_entry.insert(0, str(threshold_val))
            
        except ValueError:
            self._log("Invalid threshold")
    
    def _save_tpsl_settings(self):
        """Saves TP/SL settings."""
        try:
            sl = float(self.sl_pct_entry.get())
            tp1 = float(self.tp1_pct_entry.get())
            tp2 = float(self.tp2_pct_entry.get())
            
            # Clamp to 0.1% - 50%
            sl = max(0.1, min(50.0, sl))
            tp1 = max(0.1, min(50.0, tp1))
            tp2 = max(0.1, min(50.0, tp2))
            
            self.rc.sl_pct = sl
            self.rc.tp1_pct = tp1
            self.rc.tp2_pct = tp2
            self.rc.save_to_file()
            
            # Refresh entry widgets
            for entry, val in [(self.sl_pct_entry, sl), (self.tp1_pct_entry, tp1), (self.tp2_pct_entry, tp2)]:
                entry.delete(0, "end")
                entry.insert(0, str(val))
            
            self._log(f"✅ TP/SL: SL={sl}% | TP1={tp1}% | TP2={tp2}%")
        except ValueError:
            self._log("Invalid TP/SL")
    
    def _save_multi_trade_settings(self):
        """Saves multi-trade settings."""
        try:
            val = int(self.max_trades_entry.get().strip())
            val = max(1, min(10, val))
            
            self.rc.max_trades_per_coin = val
            self.rc.save_to_file()
            
            self.max_trades_entry.delete(0, "end")
            self.max_trades_entry.insert(0, str(val))
            
            self._log(f"Multi-trade: max per coin = {val}")
        except ValueError:
            self._log("Invalid value (enter integer 1-10)")
    
    def _save_buffer_settings(self):
        """Saves slippage buffer settings."""
        try:
            sl_buf = float(self.sl_buffer_entry.get().replace(",", "."))
            be_buf = float(self.be_buffer_entry.get().replace(",", "."))
            
            # Clamp to 0 - 1.0%
            sl_buf = max(0.0, min(1.0, sl_buf))
            be_buf = max(0.0, min(1.0, be_buf))
            
            self.rc.sl_buffer_pct = sl_buf
            self.rc.be_buffer_pct = be_buf
            self.rc.save_to_file()
            
            # Refresh entry widgets
            for entry, val in [(self.sl_buffer_entry, sl_buf), (self.be_buffer_entry, be_buf)]:
                entry.delete(0, "end")
                entry.insert(0, str(val))
            
            self._log(f"Buffer: initial SL={sl_buf}% | BE={be_buf}%")
        except ValueError:
            self._log("Invalid buffer (enter a number)")
    
    def _refresh_balance(self):
        def fetch():
            try:
                exchange = order_executor.get_exchange()
                balance = order_executor.get_balance(exchange)
                self.rc.current_balance = balance
                self.after(0, self._update_balance_display)
                self._log(f"Balance: {balance:.2f} USDT")
            except Exception as e:
                self._log(f"Balance error: {e}")
        
        threading.Thread(target=fetch, daemon=True).start()
    
    def _update_balance_display(self):
        balance = self.rc.current_balance
        initial = self.rc.initial_balance
        
        if balance > 0:
            self.balance_label.configure(text=f"Current: {balance:.2f} USDT")
        else:
            self.balance_label.configure(text="Current: -- USDT")
        
        pnl, pnl_pct = self.rc.get_pnl()
        if initial > 0 and balance > 0:
            self.pnl_label.configure(text=f"P&L: {pnl:+.2f} USDT ({pnl_pct:+.1f}%)",
                                    text_color="#28a745" if pnl >= 0 else "#dc3545")
        else:
            self.pnl_label.configure(text="P&L: -- USDT (---%)")
        
        trade_amount = self.rc.get_trade_amount()
        if trade_amount > 0:
            self.next_trade_label.configure(text=f"Next trade: {trade_amount:.2f} USDT")
        else:
            self.next_trade_label.configure(text="Next trade: -- USDT")

        if self.rc.simulation_mode and hasattr(self, '_refresh_sim_live_positions'):
            self._refresh_sim_live_positions()

        self.after(30000, self._update_balance_display)
    
    def _update_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        
        # Sync config — reflect Telegram /stop /start state in GUI
        self._sync_switches_from_config()
        
        self.after(100, self._update_logs)
    
    def _sync_switches_from_config(self):
        """
        Syncs allow_new_trades and auto_trade from RuntimeConfig to GUI switches.
        """
        # allow_new_trades sync
        config_val = self.rc.allow_new_trades
        switch_val = bool(self.new_trade_switch.get())
        if config_val != switch_val:
            if config_val:
                self.new_trade_switch.select()
            else:
                self.new_trade_switch.deselect()
        
        # auto_trade sync
        config_auto = self.rc.auto_trade
        switch_auto = bool(self.auto_trade_switch.get())
        if config_auto != switch_auto:
            if config_auto:
                self.auto_trade_switch.select()
            else:
                self.auto_trade_switch.deselect()

        # simulation_mode sync
        config_sim = self.rc.simulation_mode
        switch_sim = bool(self.sim_mode_switch.get()) if hasattr(self, 'sim_mode_switch') else False
        if config_sim != switch_sim:
            if config_sim:
                self.sim_mode_switch.select()
            else:
                self.sim_mode_switch.deselect()

        if config_sim:
            mode_text = "Simulation"
        elif config_auto:
            mode_text = "Live"
        else:
            mode_text = "Test"
        self.trade_mode_label.configure(text=f"Mode: {mode_text}")
    
    def _append_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {text}\n"
        
        if "LIVE BINANCE" in text:
            start_idx = self.log_textbox._textbox.index("end-1c")
            self.log_textbox.insert("end", log_line)
            end_idx = self.log_textbox._textbox.index("end-1c")
            self.log_textbox._textbox.tag_add("binance_real", start_idx, end_idx)
        else:
            self.log_textbox.insert("end", log_line)
        
        self.log_textbox.see("end")
    
    def _log(self, text: str):
        self._append_log(text)
    
    def _clear_logs(self):
        self.log_textbox.delete("1.0", "end")
    
    def _update_time(self):
        self.time_label.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.after(1000, self._update_time)
    
    def _on_closing(self):
        if self.bot_running:
            self._stop_bot()
        self.rc.save_to_file()
        self.destroy()


def main():
    app = AIBotApp()
    app.mainloop()


if __name__ == "__main__":
    main()
