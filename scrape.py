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

# Uses Postgres on Railway, or local SQLite if running on your machine
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
# ----------------------

# 1. WINDOWS PROCESS CLEANUP
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

def cleanup_chrome():
    if sys.platform == 'win32':
        try:
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'], capture_output=True)
            subprocess.run(['taskkill', '/F', '/IM', 'chromium.exe', '/T'], capture_output=True)
        except: pass

st.set_page_config(page_title="GMGN Whale Tracker Pro", layout="wide")

# 2. UI STYLING
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

USER_DATA_DIR = os.path.join(os.getcwd(), "gmgn_session")
# Check if deployed on Railway
IS_SERVER = os.getenv("RAILWAY_ENVIRONMENT") is not None

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
        if m == 0: 
            return f"<div class='pos'>${b:,.2f} / <span style='color:#888;'>$0.00 (Transfer)</span></div>"
        if m >= 1000000: m_disp = f"${m/1000000:.2f}M"
        elif m >= 1000: m_disp = f"${m/1000:.2f}K"
        else: m_disp = f"${m:.2f}"
        return f"<div class='pos'>${b:,.2f} / <span class='mc_val'>{m_disp}</span></div>"
    except: 
        return "<div class='pos'>$0.00</div>"

def run_scrape(token_addr):
    cleanup_chrome()
    scraped_data = { "holders": {}, "total_supply": 0 }
    
    with sync_playwright() as p:
        try:
            # Force headless=True if on Railway, else False for local debugging
            context = p.chromium.launch_persistent_context(
                USER_DATA_DIR, headless=IS_SERVER,
                ignore_default_args=["--enable-automation"], # Removes the "controlled by automated software" banner
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
                        raw_list = []
                        res = json_data.get('data', [])
                        if isinstance(res, list): raw_list = res
                        elif isinstance(res, dict): raw_list = res.get('list', [])
                        
                        for item in raw_list:
                            addr = item.get('address')
                            if addr:
                                if addr not in scraped_data["holders"]:
                                    scraped_data["holders"][addr] = item
                                else:
                                    scraped_data["holders"][addr].update({k: v for k, v in item.items() if v != 0})
                    except: pass

            page.on("response", handle_response)
            page.goto("https://gmgn.ai/?chain=sol", wait_until="load")
            
            # --- AGGRESSIVE POPUP REMOVAL ---
            page.wait_for_timeout(3000)
            
            for _ in range(4): 
                try:
                    clicked = False
                    for text in ["Next", "Got it", "I got it", "Skip", "Get Started", "Close"]:
                        btn = page.locator(f"text='{text}'").first
                        if btn.is_visible():
                            btn.click(force=True)
                            page.wait_for_timeout(1000)
                            clicked = True
                            break 
                    
                    if not clicked:
                        break 
                except:
                    break
            # ---------------------------------

            search = page.locator('input[placeholder*="Search"]').first
            search.fill(token_addr)
            page.wait_for_timeout(2000) 
            page.keyboard.press("Enter")
            
            page.wait_for_timeout(10000)
            if token_addr not in page.url:
                page.goto(f"https://gmgn.ai/solana/token/{token_addr}")

            page.get_by_text("Holders", exact=True).first.click(force=True)
            page.wait_for_timeout(3000)
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(8000)

            context.close()
            
            if scraped_data["total_supply"] == 0:
                scraped_data["total_supply"] = 1_000_000_000
                
            return {
                "holders": list(scraped_data["holders"].values()), 
                "total_supply": scraped_data["total_supply"]
            }
        except Exception as e:
            st.error(f"Error: {e}"); return None

# --- UI ---
st.title("🦅 GMGN Whale Intelligence Dashboard")

# Initialize tabs
tab1, tab2 = st.tabs(["🔴 Live Scraper", "🗄️ Database History"])

with st.sidebar:
    st.header("1. Authentication")
    if st.button("🔓 Start Login (Local Only)"):
        if IS_SERVER:
            st.error("Login must be done locally. Copy your 'gmgn_session' folder to Railway.")
        else:
            cleanup_chrome()
            with sync_playwright() as p:
                try:
                    ctx = p.chromium.launch_persistent_context(
                        USER_DATA_DIR, 
                        headless=False,
                        ignore_default_args=["--enable-automation"],
                        args=["--disable-blink-features=AutomationControlled"]
                    )
                    page = ctx.new_page(); page.goto("https://gmgn.ai/")
                    for _ in range(600):
                        if ctx.browser is None or not ctx.pages: break
                        page.wait_for_timeout(1000)
                    ctx.close()
                except: pass
    
    st.header("2. Search & Control")
    token_input = st.text_input("Token Address", value=st.session_state.get('t_addr', ''))
    
    # Button to scan just once
    start_scan = st.button("🔍 Run Manual Scan")

    st.write("---")
    st.write("**Background Auto-Tracker**")
    
    # Initialize auto-scan state if it doesn't exist
    if 'auto_scan' not in st.session_state:
        st.session_state['auto_scan'] = False

    # Start and Stop Buttons layout
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Start Auto"):
            st.session_state['auto_scan'] = True
    with col2:
        if st.button("⏹️ Stop Auto"):
            st.session_state['auto_scan'] = False

    # Logic to trigger the timer
    refresh_count = 0
    if st.session_state['auto_scan']:
        st.success("🟢 Tracking: Every 5 Mins")
        refresh_count = st_autorefresh(interval=300 * 1000, key="gmgn_pro_sync")
    else:
        st.info("🔴 Tracker Paused")

# --- TAB 1: LIVE SCRAPER ---
with tab1:
    
    # --- AUTO-REFRESH DETECTOR ---
    is_auto_refresh = False
    if 'last_count' not in st.session_state:
        st.session_state['last_count'] = 0
        
    # Only detect a refresh if auto_scan is actually active
    if st.session_state['auto_scan'] and refresh_count > st.session_state['last_count']:
        is_auto_refresh = True
        st.session_state['last_count'] = refresh_count
    # -----------------------------

    # Run if the user clicks manual scan OR if the 5-minute timer hits
    if (start_scan or is_auto_refresh) and token_input:
        st.session_state['t_addr'] = token_input
        
        with st.spinner("🤖 Deep Scanning Blockchain Data..."):
            
            # --- RETRY LOGIC ---
            data = None
            max_retries = 2
            
            for attempt in range(max_retries):
                data = run_scrape(token_input)
                
                if data and data["holders"]:
                    break
                
                elif attempt < max_retries - 1:
                    st.toast(f"⚠️ Website didn't load details. Retrying (Attempt {attempt + 2}/{max_retries})...", icon="🔄")
                    time.sleep(2)
            # -------------------
        
        if data and data["holders"]:
            holders_list = data["holders"]
            actual_supply = data["total_supply"]
            
            db_session = SessionLocal()
            html = "<table><tr><th>WALLET ADDRESS</th><th>TOTAL PNL</th><th>UNREALIZED</th><th>BOUGHT / AVG MC</th></tr>"
            sorted_data = sorted(holders_list, key=lambda x: float(x.get('profit', 0)), reverse=True)
            
            for t in sorted_data:
                addr = t.get('address', 'Unknown')
                
                pnl = float(t.get('profit', 0))
                unreal = float(t.get('unrealized_profit', 0))
                buy_usd = float(t.get('buy_volume_cur', 0))
                
                raw_avg_cost = t.get('avg_cost')
                avg_cost = float(raw_avg_cost if raw_avg_cost is not None else 0)
                actual_avg_mc = avg_cost * actual_supply

                # SAVE TO DATABASE
                new_record = WalletHistory(
                    token_address=token_input,
                    wallet_address=addr,
                    total_pnl=pnl,
                    unrealized_pnl=unreal,
                    buy_usd=buy_usd,
                    avg_mc=actual_avg_mc
                )
                db_session.add(new_record)
                
                # HTML Formatting
                pnl_html = format_pnl(pnl, t.get('profit_change', 0))
                unreal_html = format_pnl(unreal, t.get('unrealized_pnl', 0))
                bought_html = format_bought_mc(buy_usd, actual_avg_mc)
                
                html += f"<tr><td><code>{addr}</code></td><td>{pnl_html}</td><td>{unreal_html}</td><td>{bought_html}</td></tr>"
            
            db_session.commit()
            db_session.close()

            # SAVE THE HTML TO MEMORY
            st.session_state['scraped_html'] = html + "</table>"
            st.success("✅ Data successfully saved to the database.")
        else:
            st.error("❌ Failed to fetch data. The website might be blocking the request or loading too slowly.")

    # Always display the table from memory if it exists
    if 'scraped_html' in st.session_state:
        st.markdown(st.session_state['scraped_html'], unsafe_allow_html=True)

# --- TAB 2: DATABASE HISTORY ---
with tab2:
    st.subheader("Filter Saved Wallet History")
    
    db_session = SessionLocal()
    
    unique_tokens = [r[0] for r in db_session.query(WalletHistory.token_address).distinct().all() if r[0]]
    unique_wallets = [r[0] for r in db_session.query(WalletHistory.wallet_address).distinct().all() if r[0]]
    
    col1, col2 = st.columns(2)
    with col1:
        filter_wallet = st.selectbox("Filter by Wallet Address", ["All"] + unique_wallets)
    with col2:
        filter_token = st.selectbox("Filter by Token Address", ["All"] + unique_tokens)

    query = db_session.query(WalletHistory)
    
    if filter_wallet != "All":
        query = query.filter(WalletHistory.wallet_address == filter_wallet)
    if filter_token != "All":
        query = query.filter(WalletHistory.token_address == filter_token)
        
    results = query.order_by(WalletHistory.scraped_at.desc()).limit(100).all()
    
    if results:
        history_data = [{
            "Scraped At": r.scraped_at.strftime("%Y-%m-%d %H:%M:%S"),
            "Token": r.token_address,
            "Wallet": r.wallet_address,
            "Total PNL ($)": round(r.total_pnl, 2),
            "Unrealized ($)": round(r.unrealized_pnl, 2),
            "Bought ($)": round(r.buy_usd, 2),
            "Avg MC ($)": round(r.avg_mc, 2)
        } for r in results]
        
        st.dataframe(pd.DataFrame(history_data), use_container_width=True)
    else:
        st.info("No historical data found for these filters.")
        
    db_session.close()