import asyncio
import sys
import os
import subprocess
import time
import pandas as pd
from playwright.sync_api import sync_playwright
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- DATABASE SETUP ---
from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer
from sqlalchemy.orm import declarative_base, sessionmaker

DB_URL = os.getenv("DATABASE_URL", "sqlite:///whale_data.db")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DB_URL)
Base = declarative_base()

class WalletHistory(Base):
    __tablename__ = 'wallet_history'
    id = Column(Integer, primary_key=True)
    token_address = Column(String)
    wallet_address = Column(String)
    total_pnl = Column(Float)
    unrealized_pnl = Column(Float)
    buy_usd = Column(Float)
    avg_mc = Column(Float)
    scraped_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# --- CONFIGURATION ---
IS_SERVER = os.getenv("RAILWAY_ENVIRONMENT") is not None
# Points to your 5 existing folders: session_1, session_2, etc.
SESSION_DIRS = [os.path.join(os.getcwd(), f"session_{i}") for i in range(1, 6)]

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def cleanup_chrome():
    if sys.platform == 'win32':
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'], capture_output=True)
            subprocess.run(['taskkill', '/F', '/IM', 'chromium.exe', '/T'], capture_output=True)
        except: pass

st.set_page_config(page_title="GMGN Whale Tracker Pro", layout="wide")

# --- UI STYLING (Restored) ---
st.markdown("""
<style>
    .stApp { background-color: #0b0e11; color: #e0e0e0; }
    table { width: 100%; border-collapse: collapse; margin-top: 20px; font-family: 'Inter', sans-serif; }
    th { background-color: #161a1e; color: #888; padding: 12px; text-align: left; border-bottom: 2px solid #333; font-size: 11px; text-transform: uppercase; }
    td { padding: 14px 12px; border-bottom: 1px solid #1f2327; vertical-align: middle; }
    .pos { color: #00ffa3 !important; font-weight: 600; }
    .neg { color: #ff4d4d !important; font-weight: 600; }
    .pct { font-size: 11px; margin-top: 2px; opacity: 0.9; }
    .mc_val { color: #00ffa3; font-size: 11px; opacity: 0.7; }
    code { background: #1c2127; padding: 6px 10px; border-radius: 4px; color: #00ffa3; font-size: 12px; border: 1px solid #2d333b; display: inline-block; }
</style>
""", unsafe_allow_html=True)

def format_pnl(val, pct_val):
    try:
        v, p = float(val), float(pct_val) * 100
        cls, sign = ("pos", "+") if v >= 0 else ("neg", "")
        if abs(v) >= 1000000: disp = f"{sign}${v/1000000:.2f}M"
        elif abs(v) >= 1000: disp = f"{sign}${v/1000:.2f}K"
        else: disp = f"{sign}${v:.2f}"
        return f"<div class='{cls}'>{disp}</div><div class='{cls} pct'>{p:+.2f}%</div>"
    except: return "<div>$0.00</div>"

def format_bought_mc(bought_val, mc_val):
    try:
        b, m = float(bought_val), float(mc_val)
        m_disp = f"${m/1e6:.2f}M" if m >= 1e6 else (f"${m/1e3:.2f}K" if m >= 1e3 else f"${m:.2f}")
        return f"<div class='pos'>${b:,.2f} / <span class='mc_val'>{m_disp}</span></div>"
    except: return "<div class='pos'>$0.00</div>"

def run_scrape(token_addr, session_path):
    cleanup_chrome()
    scraped_data = { "holders": {}, "total_supply": 0 }
    
    with sync_playwright() as p:
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=session_path,
                headless=True,  # YEH SAB SE ZAROORI HAI!
                args=[
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--disable-blink-features=AutomationControlled'
    ]
)
            page = context.new_page()
            
            def handle_response(response):
                if f"tokens/sol/{token_addr}" in response.url and response.status == 200:
                    try:
                        json_data = response.json()
                        supply = json_data.get('data', {}).get('token', {}).get('total_supply')
                        if supply: scraped_data["total_supply"] = float(supply)
                    except: pass
                if ("holders" in response.url or "top_traders" in response.url) and response.status == 200:
                    try:
                        json_data = response.json()
                        res = json_data.get('data', [])
                        raw_list = res if isinstance(res, list) else res.get('list', [])
                        for item in raw_list:
                            addr = item.get('address')
                            if addr:
                                if addr not in scraped_data["holders"]:
                                    scraped_data["holders"][addr] = item
                                else:
                                    scraped_data["holders"][addr].update({k: v for k, v in item.items() if v != 0})
                    except: pass

            page.on("response", handle_response)
            page.goto(f"https://gmgn.ai/solana/token/{token_addr}", wait_until="load")
            
            page.wait_for_timeout(3000)
            # Dismiss Popups
            for _ in range(3):
                for text in ["Next", "Got it", "I got it", "Skip", "Close"]:
                    try:
                        btn = page.locator(f"text='{text}'").first
                        if btn.is_visible(): btn.click(force=True); page.wait_for_timeout(800)
                    except: pass

            # Ensure on Holders tab
            try:
                page.get_by_text("Holders", exact=True).first.click(force=True)
                page.wait_for_timeout(2000)
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(8000)
            except: pass

            context.close()
            if scraped_data["total_supply"] == 0: scraped_data["total_supply"] = 1_000_000_000
            return {"holders": list(scraped_data["holders"].values()), "total_supply": scraped_data["total_supply"]}
        except Exception as e:
            st.error(f"Error: {e}"); return None

# --- MAIN UI ---
if 'session_idx' not in st.session_state: st.session_state['session_idx'] = 0

tab1, tab2 = st.tabs(["🔴 Live Scraper", "🗄️ Database History"])

with st.sidebar:
    st.header("Search & Control")
    token_input = st.text_input("Token Address", value=st.session_state.get('t_addr', ''))
    start_scan = st.button("🔍 Run Manual Scan")
    
    if 'auto_scan' not in st.session_state: st.session_state['auto_scan'] = False
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Start 1m"): st.session_state['auto_scan'] = True
    with col2:
        if st.button("⏹️ Stop"): st.session_state['auto_scan'] = False

    refresh_count = 0
    if st.session_state['auto_scan']:
        st.success(f"🟢 Tracking: session_{st.session_state['session_idx'] + 1}")
        refresh_count = st_autorefresh(interval=60 * 1000, key="gmgn_sync")

with tab1:
    is_triggered = (st.session_state['auto_scan'] and refresh_count > st.session_state.get('last_count', 0))
    
    if (start_scan or is_triggered) and token_input:
        st.session_state['last_count'] = refresh_count
        st.session_state['t_addr'] = token_input
        
        # Select folder path
        curr_session_path = SESSION_DIRS[st.session_state['session_idx']]
        
        with st.spinner(f"Scanning via session_{st.session_state['session_idx']+1}..."):
            data = run_scrape(token_input, curr_session_path)
            # Cycle to next folder for next minute
            st.session_state['session_idx'] = (st.session_state['session_idx'] + 1) % 5
        
        if data and data["holders"]:
            db_session = SessionLocal()
            html = "<table><tr><th>WALLET ADDRESS</th><th>TOTAL PNL</th><th>UNREALIZED</th><th>BOUGHT / AVG MC</th></tr>"
            
            for t in sorted(data["holders"], key=lambda x: float(x.get('profit', 0)), reverse=True):
                addr = t.get('address', 'Unknown')
                pnl, unreal = float(t.get('profit', 0)), float(t.get('unrealized_profit', 0))
                buy_usd = float(t.get('buy_volume_cur', 0))
                avg_mc = float(t.get('avg_cost', 0)) * data["total_supply"]

                db_session.add(WalletHistory(token_address=token_input, wallet_address=addr, total_pnl=pnl, unrealized_pnl=unreal, buy_usd=buy_usd, avg_mc=avg_mc))
                
                html += f"<tr><td><code>{addr}</code></td>"
                html += f"<td>{format_pnl(pnl, t.get('profit_change', 0))}</td>"
                html += f"<td>{format_pnl(unreal, t.get('unrealized_pnl', 0))}</td>"
                html += f"<td>{format_bought_mc(buy_usd, avg_mc)}</td></tr>"
            
            db_session.commit(); db_session.close()
            st.session_state['scraped_html'] = html + "</table>"

    if 'scraped_html' in st.session_state:
        st.markdown(st.session_state['scraped_html'], unsafe_allow_html=True)
