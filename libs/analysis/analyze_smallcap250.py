import os
import sqlite3
import datetime
import time
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Template
from libs.utility import stock_utils

CACHE_DB_PATH = "data/cache/smallcap_cache.db"
SELECTED_DB_PATH = "output/db/SelectedStock.db"
HTML_REPORT_PATH = "output/htmls/Smallcap250.html"

# Ensure directories exist
os.makedirs("data/cache", exist_ok=True)
os.makedirs("output/db", exist_ok=True)
os.makedirs("output/htmls", exist_ok=True)

def init_databases():
    stock_utils.init_cache_db(CACHE_DB_PATH)
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    cursor_selected.execute("""
        CREATE TABLE IF NOT EXISTS smallcap250 (
            ticker TEXT PRIMARY KEY,
            stock_name TEXT,
            sector TEXT,
            market_cap REAL,
            dividend_yield REAL,
            pe REAL,
            pb REAL,
            pat REAL,
            roe REAL,
            debt_to_equity REAL,
            score REAL,
            last_updated TEXT
        )
    """)
    conn_selected.commit()
    conn_selected.close()

def get_smallcap_constituents():
    """Retrieve Nifty Smallcap 250 constituents and their sector mapping."""
    try:
        url = "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"
        df = pd.read_csv(url)
        mapping = {}
        for _, row in df.iterrows():
            sym = row['Symbol']
            ind = row['Industry']
            if pd.notna(sym) and pd.notna(ind):
                mapping[f"{sym.strip()}.NS"] = ind.strip()
        return mapping
    except Exception as e:
        print(f"Error fetching Smallcap 250 list from NSE: {e}. Using fallback mapping.")
        fallback = [
            ("AARTIIND.NS", "Chemicals"), ("AAVAS.NS", "Financial Services"), 
            ("ACE.NS", "Capital Goods"), ("ALOKINDS.NS", "Textiles"), 
            ("AMARAJABAT.NS", "Automobile and Auto Components"), ("ANGELONE.NS", "Financial Services"), 
            ("ASTEC.NS", "Chemicals"), ("AVANTIFEED.NS", "Fast Moving Consumer Goods"), 
            ("BAJAJELEC.NS", "Consumer Durables"), ("BALAMINES.NS", "Chemicals")
        ]
        return {t: s for t, s in fallback}

def fetch_all_data():
    mapping = get_smallcap_constituents()
    today_str = datetime.date.today().isoformat()
    
    print(f"Starting download process for {len(mapping)} Smallcap 250 tickers...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(stock_utils.fetch_and_cache_ticker, CACHE_DB_PATH, ticker, sector, today_str, spike_chance=0.0): ticker for ticker, sector in mapping.items()}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if i % 20 == 0 or "Failed" in res:
                print(f"[{i}/{len(mapping)}] {res}")
            time.sleep(0.02)

def rank_and_select_smallcap_by_sector():
    """Rank smallcap stocks relative to their sectors and select top 3 of each sector."""
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()
    
    if df.empty:
        print("No fundamental data for analysis.")
        return
        
    df = stock_utils.rank_and_score_stocks(df)
    
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    cursor_selected.execute("DELETE FROM smallcap250")
    
    today_str = datetime.date.today().isoformat()
    
    grouped = df.groupby('sector')
    for sector, group in grouped:
        top_3 = group.sort_values(by='score', ascending=False).head(3)
        for _, row in top_3.iterrows():
            cursor_selected.execute("""
                INSERT OR REPLACE INTO smallcap250 (ticker, stock_name, sector, market_cap, dividend_yield, pe, pb, pat, roe, debt_to_equity, score, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (row['ticker'], row['stock_name'], row['sector'], row['market_cap'], row['dividend_yield'],
                  row['pe'], row['pb'], row['pat'], row['roe'], row['debt_to_equity'], row['score'], today_str))
                  
    conn_selected.commit()
    conn_selected.close()
    print("Successfully screened top 3 stocks per sector.")

def compile_html_report():
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    selected_df = pd.read_sql_query("SELECT * FROM smallcap250 ORDER BY sector ASC, score DESC", conn_selected)
    conn_selected.close()
    
    if selected_df.empty:
        print("No small cap records to compile.")
        return
        
    # Load all cached raw fundamentals to calculate sector averages and max values
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    raw_df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()

    # Pre-process raw data to ignore placeholder values for calculations
    raw_df['pe_clean'] = raw_df['pe'].apply(lambda x: np.nan if x <= 0 or x >= 999 else x)
    raw_df['pb_clean'] = raw_df['pb'].apply(lambda x: np.nan if x <= 0 or x >= 99 else x)
    raw_df['roe_clean'] = raw_df['roe'].apply(lambda x: np.nan if x == 0.0 else x)

    # Compute stats per sector
    sector_stats = {}
    grouped_stats = raw_df.groupby('sector')
    for sector, group in grouped_stats:
        avg_pe = group['pe_clean'].mean()
        max_pe = group['pe_clean'].max()
        avg_pb = group['pb_clean'].mean()
        max_pb = group['pb_clean'].max()
        avg_roe = group['roe_clean'].mean()
        max_roe = group['roe_clean'].max()

        sector_stats[sector] = {
            'pe_range': f"{avg_pe:.1f} - {max_pe:.1f}" if not pd.isna(avg_pe) else "N/A",
            'pb_range': f"{avg_pb:.1f} - {max_pb:.1f}" if not pd.isna(avg_pb) else "N/A",
            'roe_range': f"{avg_roe:.1f}% - {max_roe:.1f}%" if not pd.isna(avg_roe) else "N/A"
        }

    # Find absolute best stock (highest sector-relative score)
    best_stock = selected_df.sort_values(by='score', ascending=False).iloc[0].to_dict()
    
    stocks = selected_df.to_dict(orient='records')
    for s in stocks:
        s['formatted_cap'] = f"₹{s['market_cap']/1e7:.2f} Cr" if s['market_cap'] > 0 else "N/A"
        s['formatted_pat'] = f"₹{s['pat']/1e7:.2f} Cr" if s['pat'] > 0 else "N/A"
        s['pe_display'] = f"{s['pe']:.2f}" if s['pe'] < 999 else "N/A"
        s['pb_display'] = f"{s['pb']:.2f}" if s['pb'] < 99 else "N/A"
        s['div_display'] = f"{s['dividend_yield']:.2f}%"
        s['roe_display'] = f"{s['roe']:.2f}%"
        s['de_display'] = f"{s['debt_to_equity']:.2f}"
        s['score_display'] = f"{s['score']:.1f}"

    best_stock['formatted_cap'] = f"₹{best_stock['market_cap']/1e7:.2f} Cr" if best_stock['market_cap'] > 0 else "N/A"
    best_stock['formatted_pat'] = f"₹{best_stock['pat']/1e7:.2f} Cr" if best_stock['pat'] > 0 else "N/A"
    best_stock['pe_display'] = f"{best_stock['pe']:.2f}" if best_stock['pe'] < 999 else "N/A"
    best_stock['pb_display'] = f"{best_stock['pb']:.2f}" if best_stock['pb'] < 99 else "N/A"
    best_stock['div_display'] = f"{best_stock['dividend_yield']:.2f}%"
    best_stock['roe_display'] = f"{best_stock['roe']:.2f}%"
    best_stock['de_display'] = f"{best_stock['debt_to_equity']:.2f}"
    best_stock['score_display'] = f"{best_stock['score']:.1f}"

    # Group by sector in python for rendering
    sectors_data = {}
    for s in stocks:
        sec = s['sector']
        if sec not in sectors_data:
            sectors_data[sec] = {
                'stocks': [],
                'stats': sector_stats.get(sec, {'pe_range': 'N/A', 'pb_range': 'N/A', 'roe_range': 'N/A'})
            }
        sectors_data[sec]['stocks'].append(s)

    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nifty Smallcap 250 Sector-wise Fundamental Analysis</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #080b11;
            --card-bg: rgba(17, 24, 39, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f9fafb;
            --text-secondary: #9ca3af;
            --primary-accent: #3b82f6; /* Blue for Smallcap */
            --secondary-accent: #f59e0b; /* Amber */
            --accent-glow: rgba(59, 130, 246, 0.15);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 2rem;
            background-image: 
                radial-gradient(at 10% 10%, rgba(59, 130, 246, 0.05) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(245, 158, 11, 0.05) 0px, transparent 50%);
        }
        
        header {
            margin-bottom: 3rem;
            text-align: center;
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(to right, #3b82f6, #f59e0b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.1rem;
        }

        /* Hero Stock Card */
        .best-stock-hero {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(17, 24, 39, 0.8) 100%);
            border: 1px solid var(--primary-accent);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 3rem;
            box-shadow: 0 8px 32px var(--accent-glow);
            backdrop-filter: blur(12px);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 2rem;
        }
        
        .hero-info h2 {
            font-size: 2rem;
            color: var(--primary-accent);
            margin-bottom: 0.25rem;
        }
        
        .hero-info .ticker {
            font-weight: 600;
            color: var(--text-secondary);
            font-size: 1.2rem;
            letter-spacing: 0.05em;
            margin-bottom: 1rem;
        }
        
        .badge {
            background: var(--primary-accent);
            color: #ffffff;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 700;
            display: inline-block;
            margin-bottom: 1rem;
        }

        .hero-score {
            text-align: center;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            min-width: 150px;
        }
        
        .hero-score-val {
            font-size: 3rem;
            font-weight: 700;
            color: var(--primary-accent);
        }
        
        .hero-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 1.5rem;
            width: 100%;
            max-width: 600px;
        }
        
        .metric-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }
        
        .metric-value {
            font-size: 1.15rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        /* Sector Groups */
        .sector-section {
            margin-bottom: 3rem;
        }
        
        .sector-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            margin-bottom: 1rem;
            border-left: 4px solid var(--secondary-accent);
            padding-left: 0.75rem;
        }

        .sector-title {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--secondary-accent);
        }

        /* Table Design */
        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(12px);
            margin-bottom: 2rem;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        
        th, td {
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }
        
        th {
            background: rgba(255, 255, 255, 0.02);
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            line-height: 1.3;
        }

        .th-sublabel {
            font-size: 0.75rem;
            text-transform: none;
            display: block;
            color: var(--text-secondary);
            margin-top: 0.25rem;
            font-weight: 400;
        }
        
        tr:last-child td {
            border-bottom: none;
        }
        
        tr:hover {
            background-color: rgba(255, 255, 255, 0.01);
        }
        
        .ticker-col {
            font-weight: 600;
            color: var(--primary-accent);
        }
        
        .score-col {
            font-weight: 700;
            color: var(--secondary-accent);
        }
    </style>
</head>
<body>

    <header>
        <h1>Nifty Smallcap 250 Sector-wise Benchmarking</h1>
        <p class="subtitle">Top 3 Stocks Per Sector Evaluated Against Peer Group Fundamentals</p>
    </header>

    <!-- Best Stock Hero Section -->
    <div class="best-stock-hero">
        <div class="hero-info">
            <span class="badge">🏆 Best Sector-Relative Performer</span>
            <h2>{{ best_stock.stock_name }}</h2>
            <div class="ticker">{{ best_stock.ticker }} ({{ best_stock.sector }})</div>
            
            <div class="hero-metrics">
                <div class="metric-card">
                    <div class="metric-label">PE Ratio</div>
                    <div class="metric-value">{{ best_stock.pe_display }}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">PB Ratio</div>
                    <div class="metric-value">{{ best_stock.pb_display }}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Return on Equity</div>
                    <div class="metric-value">{{ best_stock.roe_display }}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Debt to Equity</div>
                    <div class="metric-value">{{ best_stock.de_display }}</div>
                </div>
            </div>
        </div>
        
        <div class="hero-score">
            <div class="metric-label" style="text-transform: uppercase; letter-spacing: 0.1em;">Relative Score</div>
            <div class="hero-score-val">{{ best_stock.score_display }}</div>
            <div class="metric-label" style="margin-top: 0.5rem;">Rank #1 / Sector</div>
        </div>
    </div>

    <!-- Sector Groups -->
    {% for sector, s_data in sectors_data.items() %}
    <div class="sector-section">
        <div class="sector-header">
            <h2 class="sector-title">{{ sector }}</h2>
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Stock Name</th>
                        <th>Market Cap</th>
                        <th>
                            PE
                            <span class="th-sublabel">({{ s_data.stats.pe_range }})</span>
                        </th>
                        <th>
                            PB
                            <span class="th-sublabel">({{ s_data.stats.pb_range }})</span>
                        </th>
                        <th>Div Yield</th>
                        <th>
                            ROE
                            <span class="th-sublabel">({{ s_data.stats.roe_range }})</span>
                        </th>
                        <th>D/E</th>
                        <th>Score</th>
                    </tr>
                </thead>
                <tbody>
                    {% for stock in s_data.stocks %}
                    <tr>
                        <td class="ticker-col">{{ stock.ticker }}</td>
                        <td>{{ stock.stock_name }}</td>
                        <td>{{ stock.formatted_cap }}</td>
                        <td>{{ stock.pe_display }}</td>
                        <td>{{ stock.pb_display }}</td>
                        <td>{{ stock.div_display }}</td>
                        <td>{{ stock.roe_display }}</td>
                        <td>{{ stock.de_display }}</td>
                        <td class="score-col">{{ stock.score_display }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endfor %}

</body>
</html>
    """
    
    template = Template(html_template)
    rendered_html = template.render(best_stock=best_stock, sectors_data=sectors_data)
    
    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
        
    print(f"Successfully generated HTML report at {HTML_REPORT_PATH}")

if __name__ == "__main__":
    init_databases()
    fetch_all_data()
    rank_and_select_smallcap_by_sector()
    compile_html_report()
