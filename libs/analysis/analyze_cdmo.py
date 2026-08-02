import os
import sqlite3
import datetime
import time
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Template
from libs.utility import stock_utils

CACHE_DB_PATH = "data/cache/cdmo_cache.db"
SELECTED_DB_PATH = "output/db/SelectedStock.db"
HTML_REPORT_PATH = "output/htmls/CDMO.html"

# Ensure directories exist
os.makedirs("data/cache", exist_ok=True)
os.makedirs("output/db", exist_ok=True)
os.makedirs("output/htmls", exist_ok=True)

# CDMO stocks with their sub-sectors
CDMO_CONSTITUENTS = {
    "DIVISLAB.NS": "Custom Synthesis & API",
    "LAURUSLABS.NS": "Custom Synthesis & API",
    "JUBLPHARMA.NS": "Custom Synthesis & API",
    "CONCORDBIO.NS": "Custom Synthesis & API",
    "SYNGENE.NS": "Biologics & Formulations",
    "GLAND.NS": "Biologics & Formulations",
    "PPLPHARMA.NS": "Biologics & Formulations",
    "SUNPHARMA.NS": "Diversified CDMO & Pharma",
    "DRREDDY.NS": "Diversified CDMO & Pharma",
    "CIPLA.NS": "Diversified CDMO & Pharma",
    "AUROPHARMA.NS": "Diversified CDMO & Pharma",
    "ZYDUSLIFE.NS": "Diversified CDMO & Pharma"
}

def init_databases():
    stock_utils.init_cache_db(CACHE_DB_PATH)
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    cursor_selected.execute("""
        CREATE TABLE IF NOT EXISTS cdmo (
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
    cursor_selected.execute("""
        CREATE TABLE IF NOT EXISTS cdmo_delivery (
            ticker TEXT PRIMARY KEY,
            stock_name TEXT,
            monthly_avg REAL,
            weekly_avg REAL,
            latest_ratio REAL,
            latest_date TEXT,
            prev_day_ratio REAL,
            prev_day_date TEXT,
            prev_to_prev_ratio REAL,
            prev_to_prev_date TEXT,
            deviation REAL,
            is_spike INTEGER,
            insight TEXT,
            last_updated TEXT
        )
    """)
    conn_selected.commit()
    conn_selected.close()

def fetch_all_data():
    today_str = datetime.date.today().isoformat()
    print(f"Starting download process for {len(CDMO_CONSTITUENTS)} CDMO tickers...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(stock_utils.fetch_and_cache_ticker, CACHE_DB_PATH, ticker, sector, today_str, spike_chance=0.30): ticker for ticker, sector in CDMO_CONSTITUENTS.items()}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if i % 5 == 0 or "Failed" in res:
                print(f"[{i}/{len(CDMO_CONSTITUENTS)}] {res}")
            time.sleep(0.02)

def rank_and_select_cdmo_by_sector():
    """Rank CDMO stocks relative to their sub-sectors and select top 20 overall (all of them)."""
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()
    
    if df.empty:
        print("No fundamental data for analysis.")
        return
        
    df = stock_utils.rank_and_score_stocks(df)
    
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    cursor_selected.execute("DELETE FROM cdmo")
    cursor_selected.execute("DELETE FROM cdmo_delivery")
    
    today_str = datetime.date.today().isoformat()
    
    # Selected top 20 overall
    top_20 = df.sort_values(by='score', ascending=False).head(20)
    
    for _, row in top_20.iterrows():
        cursor_selected.execute("""
            INSERT OR REPLACE INTO cdmo (ticker, stock_name, sector, market_cap, dividend_yield, pe, pb, pat, roe, debt_to_equity, score, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (row['ticker'], row['stock_name'], row['sector'], row['market_cap'], row['dividend_yield'],
              row['pe'], row['pb'], row['pat'], row['roe'], row['debt_to_equity'], row['score'], today_str))
              
    # Calculate Delivery statistics
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    for _, row in top_20.iterrows():
        ticker = row['ticker']
        stock_name = row['stock_name']
        
        del_df = pd.read_sql_query("SELECT * FROM delivery_history WHERE ticker = ? ORDER BY date ASC", conn_cache, params=(ticker,))
        
        if len(del_df) >= 3:
            dates = del_df['date'].tolist()
            ratios = del_df['delivery_ratio'].tolist()
            
            latest_date = dates[-1]
            latest_ratio = ratios[-1]
            
            prev_date = dates[-2]
            prev_ratio = ratios[-2]
            
            prev_to_prev_date = dates[-3]
            prev_to_prev_ratio = ratios[-3]
            
            month_avg = np.mean(ratios[-20:])
            week_avg = np.mean(ratios[-5:])
            
            deviation = latest_ratio - month_avg
            is_spike = 1 if latest_ratio >= 1.5 * prev_ratio else 0
            
            # Construct validation insights
            if is_spike:
                multiplier = latest_ratio / prev_ratio
                insight = f"SPIKE: Delivery surged to {latest_ratio*100:.1f}% on {latest_date} from {prev_ratio*100:.1f}% on {prev_date} ({multiplier:.1f}x spike)."
            else:
                insight = f"Normal: Delivery is {latest_ratio*100:.1f}% on {latest_date} vs {prev_ratio*100:.1f}% on {prev_date}."
            
            cursor_selected.execute("""
                INSERT OR REPLACE INTO cdmo_delivery (ticker, stock_name, monthly_avg, weekly_avg, latest_ratio, latest_date, prev_day_ratio, prev_day_date, prev_to_prev_ratio, prev_to_prev_date, deviation, is_spike, insight, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ticker, stock_name, float(month_avg), float(week_avg), float(latest_ratio), latest_date, float(prev_ratio), prev_date, float(prev_to_prev_ratio), prev_to_prev_date, float(deviation), int(is_spike), insight, today_str))
            
    conn_cache.close()
    conn_selected.commit()
    conn_selected.close()
    print("Successfully screened top CDMO stocks and calculated delivery statistics.")

def compile_html_report():
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    selected_df = pd.read_sql_query("SELECT * FROM cdmo ORDER BY sector ASC, score DESC", conn_selected)
    delivery_df = pd.read_sql_query("SELECT * FROM cdmo_delivery ORDER BY deviation DESC", conn_selected)
    conn_selected.close()
    
    if selected_df.empty:
        print("No CDMO records to compile.")
        return
        
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    raw_df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()

    raw_df['pe_clean'] = raw_df['pe'].apply(lambda x: np.nan if x <= 0 or x >= 999 else x)
    raw_df['pb_clean'] = raw_df['pb'].apply(lambda x: np.nan if x <= 0 or x >= 99 else x)
    raw_df['roe_clean'] = raw_df['roe'].apply(lambda x: np.nan if x == 0.0 else x)

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

    sectors_data = {}
    for s in stocks:
        sec = s['sector']
        if sec not in sectors_data:
            sectors_data[sec] = {
                'stocks': [],
                'stats': sector_stats.get(sec, {'pe_range': 'N/A', 'pb_range': 'N/A', 'roe_range': 'N/A'})
            }
        sectors_data[sec]['stocks'].append(s)

    deliveries = delivery_df.to_dict(orient='records')
    for d in deliveries:
        d['monthly_display'] = f"{d['monthly_avg']*100:.1f}%"
        d['weekly_display'] = f"{d['weekly_avg']*100:.1f}%"
        d['latest_display'] = f"{d['latest_ratio']*100:.1f}%"
        d['prev_display'] = f"{d['prev_day_ratio']*100:.1f}%"
        d['prev_to_prev_display'] = f"{d['prev_to_prev_ratio']*100:.1f}%"
        d['dev_display'] = f"+{d['deviation']*100:.1f}%" if d['deviation'] >= 0 else f"{d['deviation']*100:.1f}%"
        
    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CDMO Sector Peer-wise Benchmarking</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --primary-accent: #3b82f6; /* Blue theme for CDMO */
            --secondary-accent: #f59e0b; /* Amber */
            --accent-glow: rgba(59, 130, 246, 0.15);
            --warning-glow: rgba(16, 185, 129, 0.2);
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

        .section-header-title {
            font-size: 1.8rem;
            font-weight: 600;
            margin: 3rem 0 1.5rem 0;
            color: var(--text-primary);
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 0.5rem;
        }

        /* Hero Stock Card */
        .best-stock-hero {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(22, 28, 45, 0.8) 100%);
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

        /* Spike Highlights */
        .spike-highlight {
            background: var(--warning-glow) !important;
            border: 1px solid var(--primary-accent);
        }

        .spike-text {
            color: var(--primary-accent) !important;
            font-weight: 700 !important;
        }

        .spike-badge {
            background: var(--primary-accent);
            color: #0b0f19;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-left: 0.5rem;
            display: inline-block;
        }

        .insight-col {
            font-size: 0.85rem;
            max-width: 250px;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>

    <header>
        <h1>CDMO Sector Peer-wise Benchmarking</h1>
        <p class="subtitle">Contract Development & Manufacturing Companies Evaluated Against Sub-Sector Fundamentals</p>
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

    <!-- Fundamental Screen Section -->
    <h2 class="section-header-title">Sector Peer Fundamentals</h2>
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

    <!-- Delivery to Trade Section -->
    <h2 class="section-header-title">Delivery to Trade Analysis</h2>
    <div class="table-container" style="margin-top: 1.5rem;">
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Stock Name</th>
                    <th>Monthly Avg</th>
                    <th>Weekly Avg</th>
                    <th>Prev-to-Prev Day</th>
                    <th>Previous Day</th>
                    <th>Latest Ratio</th>
                    <th>Deviation</th>
                    <th>Insight</th>
                </tr>
            </thead>
            <tbody>
                {% for d in deliveries %}
                <tr class="{% if d.is_spike == 1 %}spike-highlight{% endif %}">
                    <td class="ticker-col {% if d.is_spike == 1 %}spike-text{% endif %}">
                        {{ d.ticker }}
                        {% if d.is_spike == 1 %}
                        <span class="spike-badge">⚡ 1.5x SPIKE</span>
                        {% endif %}
                    </td>
                    <td class="{% if d.is_spike == 1 %}spike-text{% endif %}">{{ d.stock_name }}</td>
                    <td>{{ d.monthly_display }}</td>
                    <td>{{ d.weekly_display }}</td>
                    <td>
                        {{ d.prev_to_prev_display }}
                        <span class="th-sublabel" style="display:inline; font-size:0.7rem;">({{ d.prev_to_prev_date }})</span>
                    </td>
                    <td>
                        {{ d.prev_display }}
                        <span class="th-sublabel" style="display:inline; font-size:0.7rem;">({{ d.prev_day_date }})</span>
                    </td>
                    <td>
                        {{ d.latest_display }}
                        <span class="th-sublabel" style="display:inline; font-size:0.7rem;">({{ d.latest_date }})</span>
                    </td>
                    <td style="font-weight: 600; color: {% if d.deviation >= 0 %}#10b981{% else %}#ef4444{% endif %};">
                        {{ d.dev_display }}
                    </td>
                    <td class="insight-col {% if d.is_spike == 1 %}spike-text{% endif %}">{{ d.insight }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

</body>
</html>
    """
    
    template = Template(html_template)
    rendered_html = template.render(best_stock=best_stock, sectors_data=sectors_data, deliveries=deliveries)
    
    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
        
    print(f"Successfully generated HTML report at {HTML_REPORT_PATH}")

if __name__ == "__main__":
    init_databases()
    fetch_all_data()
    rank_and_select_cdmo_by_sector()
    compile_html_report()
