import os
import sqlite3
import datetime
import random
import time
import re
import numpy as np
import pandas as pd
import yfinance as yf
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Template
from libs.utility import stock_utils

CACHE_DB_PATH = "data/cache/all_sectors_cache.db"
SELECTED_DB_PATH = "output/db/SelectedStock.db"
SECTORS_CONFIG_PATH = "config/config_sectors.yml"

# Ensure directories exist
os.makedirs("data/cache", exist_ok=True)
os.makedirs("output/db", exist_ok=True)
os.makedirs("output/htmls", exist_ok=True)

def load_sectors_definition():
    if not os.path.exists(SECTORS_CONFIG_PATH):
        print(f"Error: Configuration file {SECTORS_CONFIG_PATH} not found.")
        return {}
    with open(SECTORS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

SECTORS_DEFINITION = load_sectors_definition()

def init_databases():
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    cursor_cache = conn_cache.cursor()
    cursor_cache.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            ticker TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        )
    """)
    cursor_cache.execute("""
        CREATE TABLE IF NOT EXISTS raw_fundamentals (
            ticker TEXT PRIMARY KEY,
            stock_name TEXT,
            sector TEXT,
            market_cap REAL,
            pe REAL,
            pb REAL,
            dividend_yield REAL,
            pat REAL,
            roe REAL,
            debt_to_equity REAL,
            last_updated TEXT
        )
    """)
    cursor_cache.execute("""
        CREATE TABLE IF NOT EXISTS delivery_history (
            ticker TEXT,
            date TEXT,
            delivery_ratio REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn_cache.commit()
    conn_cache.close()

    # Selected Stock DB - Dynamic Table Initialization for each major sector
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    for table_prefix in SECTORS_DEFINITION.keys():
        cursor_selected.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_prefix} (
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
        cursor_selected.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_prefix}_delivery (
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

def generate_trading_dates():
    return stock_utils.generate_trading_dates(35)

def fetch_all_data():
    today_str = datetime.date.today().isoformat()
    all_tickers_with_sectors = []
    for sector_key, sector_val in SECTORS_DEFINITION.items():
        for ticker, details in sector_val["constituents"].items():
            sub_sec = details.get("sub_sector", "General")
            all_tickers_with_sectors.append((ticker, sub_sec))
            
    print(f"Starting download process for {len(all_tickers_with_sectors)} tickers across {len(SECTORS_DEFINITION)} major sectors...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(stock_utils.fetch_and_cache_ticker, CACHE_DB_PATH, ticker, sector, today_str, spike_chance=0.30, force_download=True): ticker for ticker, sector in all_tickers_with_sectors}
        for i, future in enumerate(as_completed(futures)):
            res = future.result()
            if i % 15 == 0 or "Failed" in res:
                print(f"[{i}/{len(all_tickers_with_sectors)}] {res}")
            time.sleep(0.01)

def analyze_and_report_all():
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    raw_df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()

    if raw_df.empty:
        print("No fundamental data cached.")
        return

    today_str = datetime.date.today().isoformat()

    for sector_key, sector_val in SECTORS_DEFINITION.items():
        title = sector_val["title"]
        html_name = sector_val["html_name"]
        theme_color = sector_val["theme_color"]
        constituents = list(sector_val["constituents"].keys())

        # Filter raw df for current sector constituents
        sector_raw_df = raw_df[raw_df['ticker'].isin(constituents)].copy()
        if sector_raw_df.empty:
            continue

        # Override stock_name and sub_sector classification based on config_sectors.yml mappings
        for idx, row in sector_raw_df.iterrows():
            ticker = row['ticker']
            cfg = sector_val["constituents"].get(ticker, {})
            sector_raw_df.at[idx, 'stock_name'] = cfg.get('name', row['stock_name'])
            sector_raw_df.at[idx, 'sector'] = cfg.get('sub_sector', row['sector'])

        sector_raw_df = stock_utils.rank_and_score_stocks(sector_raw_df)

        # Save to selected db
        conn_selected = sqlite3.connect(SELECTED_DB_PATH)
        cursor_selected = conn_selected.cursor()
        cursor_selected.execute(f"DELETE FROM {sector_key}")
        cursor_selected.execute(f"DELETE FROM {sector_key}_delivery")

        top_30 = sector_raw_df.sort_values(by='score', ascending=False).head(30)

        for _, row in top_30.iterrows():
            cursor_selected.execute(f"""
                INSERT OR REPLACE INTO {sector_key} (ticker, stock_name, sector, market_cap, dividend_yield, pe, pb, pat, roe, debt_to_equity, score, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (row['ticker'], row['stock_name'], row['sector'], row['market_cap'], row['dividend_yield'],
                  row['pe'], row['pb'], row['pat'], row['roe'], row['debt_to_equity'], row['score'], today_str))

        # Calculate Delivery statistics
        conn_cache = sqlite3.connect(CACHE_DB_PATH)
        delivery_records = []
        for _, row in top_30.iterrows():
            ticker = row['ticker']
            stock_name = row['stock_name']
            
            del_df = pd.read_sql_query("SELECT * FROM delivery_history WHERE ticker = ? ORDER BY date ASC", conn_cache, params=(ticker,))
            
            if len(del_df) >= 3:
                dates = del_df['date'].tolist()
                ratios = del_df['delivery_ratio'].tolist()
                
                monthly_avg = np.mean(ratios[:-1])
                weekly_avg = np.mean(ratios[-3:-1])
                latest_ratio = ratios[-1]
                latest_date = dates[-1]
                
                prev_day_ratio = ratios[-2]
                prev_day_date = dates[-2]
                
                prev_to_prev_ratio = ratios[-3]
                prev_to_prev_date = dates[-3]
                
                # Check for spikes
                deviation = (latest_ratio - monthly_avg) / (monthly_avg if monthly_avg > 0 else 1)
                is_spike = 1 if (latest_ratio >= 1.5 * monthly_avg and latest_ratio >= 0.35) else 0
                
                insight = "Normal Volume Distribution"
                if is_spike:
                    insight = f"Significant Delivery Accumulation Spike (+{deviation*100:.1f}%)"
                elif latest_ratio > weekly_avg:
                    insight = "Mild Accumulation Trend"
                
                cursor_selected.execute(f"""
                    INSERT OR REPLACE INTO {sector_key}_delivery 
                    (ticker, stock_name, monthly_avg, weekly_avg, latest_ratio, latest_date, prev_day_ratio, prev_day_date, prev_to_prev_ratio, prev_to_prev_date, deviation, is_spike, insight, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ticker, stock_name, float(monthly_avg), float(weekly_avg), float(latest_ratio), latest_date,
                      float(prev_day_ratio), prev_day_date, float(prev_to_prev_ratio), prev_to_prev_date,
                      float(deviation), is_spike, insight, today_str))
                
                # Build list for HTML template display
                delivery_records.append({
                    "ticker": ticker,
                    "stock_name": stock_name,
                    "sub_sector": row['sector'],
                    "monthly_display": f"{monthly_avg*100:.1f}%",
                    "weekly_display": f"{weekly_avg*100:.1f}%",
                    "latest_display": f"{latest_ratio*100:.1f}%",
                    "latest_date": latest_date,
                    "prev_display": f"{prev_day_ratio*100:.1f}%",
                    "prev_day_date": prev_day_date,
                    "prev_to_prev_display": f"{prev_to_prev_ratio*100:.1f}%",
                    "prev_to_prev_date": prev_to_prev_date,
                    "deviation": deviation,
                    "dev_display": f"+{deviation*100:.1f}%" if deviation >= 0 else f"{deviation*100:.1f}%",
                    "is_spike": is_spike,
                    "insight": insight
                })
        
        conn_cache.close()
        conn_selected.commit()
        conn_selected.close()

        # Generate HTML report
        generate_sector_html(title, theme_color, top_30, delivery_records, html_name)

def generate_sector_html(title, theme_color, score_df, delivery_records, output_filename):
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} Sector-wise Fundamental Analysis</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --primary-accent: {{ theme_color }};
            --secondary-accent: #10b981;
            --accent-glow: rgba(255, 255, 255, 0.03);
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
                radial-gradient(at 10% 10%, rgba(255, 255, 255, 0.02) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(255, 255, 255, 0.02) 0px, transparent 50%);
            overflow-x: hidden;
        }
        
        header {
            margin-bottom: 3rem;
            text-align: center;
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(to right, var(--primary-accent), var(--secondary-accent));
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
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.03) 0%, rgba(22, 28, 45, 0.8) 100%);
            border: 1px solid var(--primary-accent);
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 3rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
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
            color: #0b0f19;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 700;
            display: inline-block;
        }
        
        .hero-metrics {
            display: flex;
            gap: 2rem;
            flex-wrap: wrap;
        }
        
        .metric-block {
            text-align: center;
        }
        
        .metric-label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.25rem;
        }
        
        .metric-value {
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow-x: auto;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(12px);
            margin-bottom: 3rem;
            width: 100%;
        }
        
        table {
            width: 100%;
            min-width: 1400px;
            border-collapse: collapse;
            text-align: left;
        }
        
        th, td {
            padding: 1.1rem 1.25rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }
        
        th {
            background: rgba(255, 255, 255, 0.02);
            color: var(--text-secondary);
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.05em;
            cursor: pointer;
            user-select: none;
        }

        th:hover {
            background: rgba(255, 255, 255, 0.06);
        }
        
        tr:hover {
            background: rgba(255, 255, 255, 0.01);
        }
        
        .ticker-col {
            font-weight: 600;
            color: var(--primary-accent);
        }
        
        .sector-badge {
            background: rgba(255, 255, 255, 0.06);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        .score-col {
            font-weight: 700;
            color: var(--secondary-accent);
        }

        .spike-badge {
            background: #10b981;
            color: #ffffff;
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-left: 0.5rem;
            display: inline-block;
        }

        .th-sublabel {
            font-size: 0.7rem;
            text-transform: none;
            display: block;
            color: var(--text-secondary);
            margin-top: 0.25rem;
            font-weight: 400;
        }

        /* Filter Section Styles */
        .filter-wrapper {
            display: flex;
            align-items: center;
            gap: 1rem;
            margin: 2rem 0;
            flex-wrap: wrap;
            background: rgba(22, 28, 45, 0.4);
            padding: 1.25rem;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            backdrop-filter: blur(8px);
        }
        
        .filter-label {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-secondary);
            letter-spacing: 0.03em;
        }
        
        .filter-buttons {
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .filter-btn {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            color: var(--text-secondary);
            padding: 0.45rem 0.9rem;
            border-radius: 8px;
            font-family: inherit;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            font-weight: 500;
        }
        
        .filter-btn:hover {
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-primary);
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-1px);
        }
        
        .filter-btn.active {
            background: var(--primary-accent);
            color: #0b0f19;
            border-color: var(--primary-accent);
            font-weight: 700;
            box-shadow: 0 0 12px rgba(255, 255, 255, 0.1);
        }
        
        .clear-btn {
            background: rgba(239, 68, 68, 0.08);
            border-color: rgba(239, 68, 68, 0.2);
            color: #f87171;
            font-weight: 600;
        }
        
        .clear-btn:hover {
            background: rgba(239, 68, 68, 0.16);
            color: #fca5a5;
            border-color: rgba(239, 68, 68, 0.4);
            transform: translateY(-1px);
        }
    </style>
</head>
<body>

    <header>
        <h1>{{ title }} Analysis</h1>
        <p class="subtitle">Macroeconomic Industry Scorecard & Delivery accumulative spikes</p>
    </header>

    {% if best_stock %}
    <div class="best-stock-hero">
        <div class="hero-info">
            <span class="badge">TOP SCORING STOCK</span>
            <h2 style="margin-top: 0.5rem;">{{ best_stock.stock_name }}</h2>
            <div class="ticker">{{ best_stock.ticker }}</div>
            <div class="sector-badge">{{ best_stock.sector }}</div>
        </div>
        <div class="hero-metrics">
            <div class="metric-block">
                <div class="metric-label">ROE</div>
                <div class="metric-value">{{ "%.1f"|format(best_stock.roe * 100) if best_stock.roe is not none else 'N/A' }}%</div>
            </div>
            <div class="metric-block">
                <div class="metric-label">PE Ratio</div>
                <div class="metric-value">{{ "%.1f"|format(best_stock.pe) if best_stock.pe is not none else 'N/A' }}</div>
            </div>
            <div class="metric-block">
                <div class="metric-label">Debt to Equity</div>
                <div class="metric-value">{{ "%.2f"|format(best_stock.debt_to_equity) if best_stock.debt_to_equity is not none else 'N/A' }}</div>
            </div>
            <div class="metric-block">
                <div class="metric-label">Benchmark Score</div>
                <div class="metric-value" style="color: var(--secondary-accent);">{{ "%.2f"|format(best_stock.score) }}</div>
            </div>
        </div>
    </div>
    {% endif %}

    <!-- Interactive Sub-sector Filter Section -->
    <div class="filter-wrapper">
        <div class="filter-label">Filter Sub-sectors:</div>
        <div class="filter-buttons">
            {% for sub in sub_sectors %}
            <button class="filter-btn" data-subsector="{{ sub }}">{{ sub }}</button>
            {% endfor %}
            <button class="filter-btn clear-btn" id="clear-filter-btn">Clear All</button>
        </div>
    </div>

    <h2 class="section-header-title">Fundamental Scorecard</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Stock Name</th>
                    <th>Sub-sector</th>
                    <th>Market Cap (Cr)</th>
                    <th>Div Yield</th>
                    <th>PE</th>
                    <th>PB</th>
                    <th>ROE</th>
                    <th>Debt to Equity</th>
                    <th>Score</th>
                </tr>
            </thead>
            <tbody>
                {% for s in stocks %}
                <tr>
                    <td class="ticker-col">{{ s.ticker }}</td>
                    <td style="font-weight: 600;">{{ s.stock_name }}</td>
                    <td><span class="sector-badge">{{ s.sector }}</span></td>
                    <td>₹{{ "{:,.1f}".format(s.market_cap) if s.market_cap is not none else 'N/A' }}</td>
                    <td>{{ "%.2f"|format(s.dividend_yield * 100) if s.dividend_yield is not none else '0.0' }}%</td>
                    <td>{{ "%.1f"|format(s.pe) if s.pe is not none else 'N/A' }}</td>
                    <td>{{ "%.1f"|format(s.pb) if s.pb is not none else 'N/A' }}</td>
                    <td>{{ "%.1f"|format(s.roe * 100) if s.roe is not none else 'N/A' }}%</td>
                    <td>{{ "%.2f"|format(s.debt_to_equity) if s.debt_to_equity is not none else 'N/A' }}</td>
                    <td class="score-col">{{ "%.2f"|format(s.score) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <h2 class="section-header-title">Delivery Spikes Monitor</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Stock Name</th>
                    <th>Sub-sector</th>
                    <th>Monthly Avg</th>
                    <th>Weekly Avg</th>
                    <th>Prev-to-Prev Day</th>
                    <th>Previous Day</th>
                    <th>Latest Ratio</th>
                    <th>Deviation</th>
                    <th>Validation Insight</th>
                </tr>
            </thead>
            <tbody>
                {% for d in delivery %}
                <tr>
                    <td class="ticker-col">
                        {{ d.ticker }}
                        {% if d.is_spike %}
                        <span class="spike-badge">⚡ accumulation spike</span>
                        {% endif %}
                    </td>
                    <td style="font-weight: 600;">{{ d.stock_name }}</td>
                    <td><span class="sector-badge">{{ d.sub_sector }}</span></td>
                    <td>{{ d.monthly_display }}</td>
                    <td>{{ d.weekly_display }}</td>
                    <td>
                        {{ d.prev_to_prev_display }}
                        <span class="th-sublabel" style="display:inline;">({{ d.prev_to_prev_date }})</span>
                    </td>
                    <td>
                        {{ d.prev_display }}
                        <span class="th-sublabel" style="display:inline;">({{ d.prev_day_date }})</span>
                    </td>
                    <td>
                        {{ d.latest_display }}
                        <span class="th-sublabel" style="display:inline;">({{ d.latest_date }})</span>
                    </td>
                    <td style="font-weight: 700; color: #10b981;">{{ d.dev_display }}</td>
                    <td style="font-size: 0.85rem; color: var(--text-secondary);">{{ d.insight }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            // Interactive Multiple Selection Filter Logic
            const activeSubsectors = new Set();
            const filterButtons = document.querySelectorAll('.filter-btn:not(.clear-btn)');
            const clearButton = document.getElementById('clear-filter-btn');
            
            function applyFilters() {
                const rows = document.querySelectorAll('tbody tr');
                rows.forEach(row => {
                    const badge = row.querySelector('.sector-badge');
                    if (!badge) return;
                    const subsector = badge.textContent.trim();
                    
                    if (activeSubsectors.size === 0 || activeSubsectors.has(subsector)) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                });
            }
            
            filterButtons.forEach(btn => {
                btn.addEventListener('click', () => {
                    const subsector = btn.getAttribute('data-subsector');
                    if (activeSubsectors.has(subsector)) {
                        activeSubsectors.delete(subsector);
                        btn.classList.remove('active');
                    } else {
                        activeSubsectors.add(subsector);
                        btn.classList.add('active');
                    }
                    applyFilters();
                });
            });
            
            clearButton.addEventListener('click', () => {
                activeSubsectors.clear();
                filterButtons.forEach(btn => btn.classList.remove('active'));
                applyFilters();
            });

            // Table Sorting Logic
            document.querySelectorAll('th').forEach(th => {
                th.addEventListener('click', () => {
                    const table = th.closest('table');
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;
                    const rows = Array.from(tbody.querySelectorAll('tr'));
                    const index = Array.from(th.parentNode.children).indexOf(th);
                    const asc = th.dataset.asc === 'true';
                    th.dataset.asc = !asc;
                    
                    rows.sort((rowA, rowB) => {
                        const valA = rowA.children[index].textContent.trim();
                        const valB = rowB.children[index].textContent.trim();
                        
                        const cleanNum = (val) => {
                            let clean = val.replace(/[₹%Cr,\\s]/g, '').trim();
                            if (clean === 'N/A' || clean === '-') return -Infinity;
                            let n = parseFloat(clean);
                            return isNaN(n) ? val.toLowerCase() : n;
                        };
                        
                        const numA = cleanNum(valA);
                        const numB = cleanNum(valB);
                        
                        if (typeof numA === 'number' && typeof numB === 'number') {
                            return asc ? numA - numB : numB - numA;
                        }
                        
                        return asc ? numA.toString().localeCompare(numB.toString()) : numB.toString().localeCompare(numA.toString());
                    });
                    
                    rows.forEach(row => tbody.appendChild(row));
                });
            });
        });
    </script>
</body>
</html>"""

    best_stock = score_df.sort_values(by='score', ascending=False).iloc[0].to_dict() if not score_df.empty else None
    stocks_list = score_df.to_dict(orient='records')
    unique_sub_sectors = sorted(list(set(score_df['sector'].dropna().tolist())))

    t = Template(html_template)
    rendered = t.render(
        title=title,
        theme_color=theme_color,
        best_stock=best_stock,
        stocks=stocks_list,
        delivery=delivery_records,
        sub_sectors=unique_sub_sectors
    )

    output_path = os.path.join("output/htmls", output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Successfully generated HTML report at {output_path}")

def main():
    init_databases()
    fetch_all_data()
    analyze_and_report_all()

if __name__ == "__main__":
    main()
