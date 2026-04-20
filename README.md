# 🦅 GMGN Whale Intelligence Dashboard

An automated, anti-bot web scraper and intelligence dashboard built to track Solana whale wallets on GMGN.ai. It intercepts hidden network data, calculates real-time metrics, and archives historical whale movements into a permanent database.

## ⚠️ CRITICAL SECURITY NOTICE
**DO NOT MAKE THIS REPOSITORY PUBLIC.** This project relies on a local browser profile (`gmgn_session`) to bypass Cloudflare and anti-bot protections. This folder contains your active session cookies and connected wallet states. If this repository is made public, your accounts will be compromised. 

---

## ⚡ Key Features

* **Anti-Bot Stealth Engine:** Uses Playwright with custom arguments to bypass Cloudflare and the "Chrome is being controlled by automated software" flags.
* **Network Interception:** Doesn't scrape visual DOM text. Instead, it wiretaps the raw JSON packets from GMGN's servers for instant, accurate token supplies and holder data.
* **Smart Retry & Popup Killer:** Automatically destroys React-based popups and features an intelligent retry loop if the network drops a packet.
* **Background Auto-Tracker:** Includes a built-in daemon that silently spins up a headless browser every 5 minutes to scrape and archive data without user input.
* **Historical Vault:** Uses SQLAlchemy to save every single scan into a local SQLite (or cloud PostgreSQL) database, allowing you to filter and track whale behavior over time.
* **Memory-Safe UI:** Built with Streamlit, utilizing session state memory so the dashboard doesn't wipe your data when switching tabs.

---

## 🛠️ Tech Stack

* **Frontend/Dashboard:** Streamlit, Pandas
* **Scraper Engine:** Playwright (Chromium)
* **Database:** SQLAlchemy, PostgreSQL (Cloud), SQLite (Local)
* **Deployment:** Docker, Railway.app

---

## 💻 Local Setup & Installation

**1. Clone the repository:**
```bash
git clone [https://github.com/msaad732/GMGN-Scrapper.git](https://github.com/msaad732/GMGN-Scrapper.git)
cd GMGN-Scrapper
```

**2. Install dependencies:**
```bash
pip install -r requirements.txt
playwright install chromium
```

**3. Generate the Authentication Session:**
Before the scraper can run autonomously, it needs your login cookies.
* Run the app locally: `streamlit run app.py`
* Click the **"🔓 Start Login (Local Only)"** button in the sidebar.
* A visible Chrome window will open. Log into GMGN.ai and connect your wallet/Twitter.
* Close the browser. You will now see a `gmgn_session` folder in your project directory. 
* *(Optional but recommended: Delete the `Cache` and `Code Cache` folders inside `gmgn_session/Default` to save space).*

**4. Run the Tracker:**
Type a token address into the search bar and click **Run Manual Scan**.

---

## ☁️ Cloud Deployment (Railway)

This application is containerized with Docker to easily handle system-level Playwright browser dependencies.

1. Push your code (including the `gmgn_session` folder) to your **Private** GitHub repository.
2. Link the repository to [Railway](https://railway.app/).
3. Add a **PostgreSQL** database service in Railway.
4. Set the following Environment Variables in your Streamlit App service:
   * `DATABASE_URL`: Add a reference to your Railway Postgres database URL.
   * `RAILWAY_ENVIRONMENT`: Set to `production` (This forces the scraper to run headlessly/invisibly).
5. Deploy and start tracking!

---

## 🔄 Session Maintenance
GMGN session cookies expire periodically. If your cloud scraper starts failing to fetch data:
1. Pull your code locally.
2. Run the "Start Login" process again to refresh the cookies.
3. Commit the updated `gmgn_session` folder and push to GitHub. Railway will automatically redeploy with the fresh session.
```
