import asyncio
import sys
import os
import subprocess
import pandas as pd
from playwright.sync_api import sync_playwright
import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

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

# 5-MINUTE AUTO-SYNC
st_autorefresh(interval=300 * 1000, key="gmgn_pro_sync")

USER_DATA_DIR = os.path.join(os.getcwd(), "gmgn_session")

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
        
        # This line specifically catches the 0s and changes "Wait.." to "Transfer"
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
    
    # Store both the holders map and the actual token supply
    scraped_data = {
        "holders": {},
        "total_supply": 0 
    }
    
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                USER_DATA_DIR, headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            def handle_response(response):
                # 1. CATCH THE REAL TOTAL SUPPLY
                if f"tokens/sol/{token_addr}" in response.url and response.status == 200:
                    try:
                        json_data = response.json()
                        token_info = json_data.get('data', {}).get('token', {})
                        supply = token_info.get('total_supply')
                        if supply:
                            scraped_data["total_supply"] = float(supply)
                    except: pass

                # 2. CATCH THE HOLDERS
                if ("holders" in response.url or "top_traders" in response.url) and response.status == 200:
                    try:
                        json_data = response.json()
                        raw_list = []
                        res = json_data.get('data', [])
                        if isinstance(res, list): raw_list = res
                        elif isinstance(res, dict): raw_list = res.get('list', [])
                        
                        # Merge data by wallet address
                        for item in raw_list:
                            addr = item.get('address')
                            if addr:
                                if addr not in scraped_data["holders"]:
                                    scraped_data["holders"][addr] = item
                                else:
                                    # Update existing wallet with new fields
                                    scraped_data["holders"][addr].update({k: v for k, v in item.items() if v != 0})
                    except: pass

            page.on("response", handle_response)
            page.goto("https://gmgn.ai/?chain=sol", wait_until="load")
            
            # Popup Removal
            for _ in range(3):
                btn = page.get_by_role("button", name="Next", exact=True).first
                if btn.is_visible(): btn.click(); page.wait_for_timeout(1000)

            # Search
            search = page.locator('input[placeholder*="Search"]').first
            search.fill(token_addr)
            page.wait_for_timeout(2000) 
            page.keyboard.press("Enter")
            
            page.wait_for_timeout(10000)
            if token_addr not in page.url:
                page.goto(f"https://gmgn.ai/solana/token/{token_addr}")

            # Trigger Holders tab and scroll to force data loading
            page.get_by_text("Holders", exact=True).first.click(force=True)
            page.wait_for_timeout(3000)
            page.mouse.wheel(0, 1000) # Scroll down to trigger lazy loading
            page.wait_for_timeout(8000)

            context.close()
            
            # Fallback to 1B just in case the network packet dropped, so the script doesn't crash
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

with st.sidebar:
    st.header("1. Authentication")
    if st.button("🔓 Start Login"):
        cleanup_chrome()
        with sync_playwright() as p:
            try:
                ctx = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False)
                page = ctx.new_page(); page.goto("https://gmgn.ai/")
                for _ in range(600):
                    if ctx.browser is None or not ctx.pages: break
                    page.wait_for_timeout(1000)
                ctx.close()
            except: pass
    
    st.header("2. Search")
    token_input = st.text_input("Token Address", value=st.session_state.get('t_addr', ''))
    st.session_state['t_addr'] = token_input

if token_input:
    with st.spinner("🤖 Deep Scanning Blockchain Data..."):
        data = run_scrape(token_input)
    
    # Notice we now check for data["holders"]
    if data and data["holders"]:
        holders_list = data["holders"]
        actual_supply = data["total_supply"]
        
        html = "<table><tr><th>WALLET ADDRESS</th><th>TOTAL PNL</th><th>UNREALIZED</th><th>BOUGHT / AVG MC</th></tr>"
        # Sort by PNL
        sorted_data = sorted(holders_list, key=lambda x: float(x.get('profit', 0)), reverse=True)
        
        for t in sorted_data:
            addr = t.get('address', 'Unknown')
            pnl_html = format_pnl(t.get('profit', 0), t.get('profit_change', 0))
            unreal_html = format_pnl(t.get('unrealized_profit', 0), t.get('unrealized_pnl', 0))
            
            buy_usd = t.get('buy_volume_cur', 0)
            
            # THE ACTUAL CALCULATION: Real Token Price * Real Token Supply
            raw_avg_cost = t.get('avg_cost')
            avg_cost = float(raw_avg_cost if raw_avg_cost is not None else 0)
            actual_avg_mc = avg_cost * actual_supply
            
            bought_html = format_bought_mc(buy_usd, actual_avg_mc)
            
            html += f"<tr><td><code>{addr}</code></td><td>{pnl_html}</td><td>{unreal_html}</td><td>{bought_html}</td></tr>"
        st.markdown(html + "</table>", unsafe_allow_html=True)
    else:
        st.warning("No data. Make sure you are logged in and 'Holders' tab loaded.")