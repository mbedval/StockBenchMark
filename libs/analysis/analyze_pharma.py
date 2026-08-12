import os
import sqlite3
import datetime
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Template
from libs.utility import stock_utils

# Tickers to analyze
TICKERS = [
    "SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "TORNTPHARM.NS",
    "LUPIN.NS", "AUROPHARMA.NS", "ZYDUSLIFE.NS", "BIOCON.NS", "ALKEM.NS",
    "IPCALAB.NS", "GLENMARK.NS", "LAURUSLABS.NS", "GRANULES.NS", "NATCOPHARM.NS",
    "PFIZER.NS", "ABBOTINDIA.NS", "ERIS.NS", "SANOFIS.NS", "JBCHEPHARM.NS",
    "SYNGENE.NS", "GLAND.NS", "APLLTD.NS", "WOCKHARDT.NS", "ASTRAZEN.NS",
    "FDC.NS", "SUPRIYA.NS", "HIKAL.NS", "MARKSANS.NS", "JAGSNPHARM.NS"
]

CACHE_DB_PATH = "data/cache/pharma_cache.db"
SELECTED_DB_PATH = "output/db/SelectedStock.db"
HTML_REPORT_PATH = "output/htmls/Pharma.html"

# Ensure directories exist
os.makedirs("data/cache", exist_ok=True)
os.makedirs("output/db", exist_ok=True)
os.makedirs("output/htmls", exist_ok=True)

def init_databases():
    stock_utils.init_cache_db(CACHE_DB_PATH)
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    cursor_selected.execute("""
        CREATE TABLE IF NOT EXISTS pharma (
            ticker TEXT PRIMARY KEY,
            stock_name TEXT,
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

def fetch_and_cache_data():
    today_str = datetime.date.today().isoformat()
    for ticker in TICKERS:
        res = stock_utils.fetch_and_cache_ticker(CACHE_DB_PATH, ticker, "Pharmaceuticals", today_str, spike_chance=0.0)
        print(res)

def rank_and_select_pharma():
    """Perform statistical fundamental scoring and select the top 20 stocks."""
    conn_cache = sqlite3.connect(CACHE_DB_PATH)
    df = pd.read_sql_query("SELECT * FROM raw_fundamentals", conn_cache)
    conn_cache.close()
    
    if df.empty:
        print("No fundamental data available for analysis.")
        return
        
    df['sector'] = "Pharmaceuticals"
    df = stock_utils.rank_and_score_stocks(df)
    
    top_20 = df.sort_values(by='score', ascending=False).head(20)
    
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    cursor_selected = conn_selected.cursor()
    today_str = datetime.date.today().isoformat()
    
    for _, row in top_20.iterrows():
        cursor_selected.execute("""
            INSERT OR REPLACE INTO pharma (ticker, stock_name, market_cap, dividend_yield, pe, pb, pat, roe, debt_to_equity, score, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (row['ticker'], row['stock_name'], row['market_cap'], row['dividend_yield'],
              row['pe'], row['pb'], row['pat'], row['roe'], row['debt_to_equity'], row['score'], today_str))
              
    conn_selected.commit()
    conn_selected.close()
    print("Successfully analyzed and saved top 20 pharma stocks.")

def compile_html_report():
    conn_selected = sqlite3.connect(SELECTED_DB_PATH)
    df = pd.read_sql_query("SELECT * FROM pharma ORDER BY score DESC", conn_selected)
    conn_selected.close()
    
    if df.empty:
        print("No selected stocks in database to compile report.")
        return
        
    # The first stock is the "best stock"
    best_stock = df.iloc[0].to_dict()
    stocks = df.to_dict(orient='records')
    
    # Simple formatting functions for template
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

    # Premium HTML/CSS Template using glassmorphism and modern colors
    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pharma Sector Fundamental Analysis</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --primary-accent: #10b981; /* Emerald green */
            --secondary-accent: #3b82f6; /* Blue */
            --accent-glow: rgba(16, 185, 129, 0.15);
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
                radial-gradient(at 10% 10%, rgba(16, 185, 129, 0.05) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(59, 130, 246, 0.05) 0px, transparent 50%);
        }
        
        header {
            margin-bottom: 3rem;
            text-align: center;
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(to right, #10b981, #3b82f6);
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
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(22, 28, 45, 0.8) 100%);
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
            color: var(--bg-color);
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

        /* Controls Section */
        .controls-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }
        
        .search-box {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.75rem 1.25rem;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 1rem;
            min-width: 300px;
            outline: none;
            transition: all 0.3s ease;
        }
        
        .search-box:focus {
            border-color: var(--primary-accent);
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);
        }
        
        .filter-group {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .filter-select {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.95rem;
            outline: none;
            cursor: pointer;
        }

        /* Table Design */
        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2);
            backdrop-filter: blur(12px);
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        
        th, td {
            padding: 1.25rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }
        
        th {
            background: rgba(255, 255, 255, 0.02);
            color: var(--text-secondary);
            font-weight: 600;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            cursor: pointer;
            user-select: none;
            transition: color 0.2s ease;
        }
        
        th:hover {
            color: var(--text-primary);
        }
        
        tr:last-child td {
            border-bottom: none;
        }
        
        tr {
            transition: background-color 0.2s ease;
        }
        
        tr:hover {
            background-color: rgba(255, 255, 255, 0.02);
        }
        
        .ticker-col {
            font-weight: 600;
            color: var(--secondary-accent);
        }
        
        .score-col {
            font-weight: 700;
            color: var(--primary-accent);
        }

        /* Animations & Responsive */
        @media (max-width: 768px) {
            .best-stock-hero {
                flex-direction: column;
                align-items: stretch;
            }
            .hero-metrics {
                grid-template-columns: repeat(2, 1fr);
            }
            .controls-container {
                flex-direction: column;
                align-items: stretch;
            }
            .search-box {
                width: 100%;
            }
        }
    </style>
</head>
<body>

    <header>
        <h1>Pharma Sector Fundamental Benchmarking</h1>
        <p class="subtitle">1-Year Stock Pricing Analysis & Theoretical Fundamental Screen</p>
    </header>

    <!-- Best Stock Hero Section -->
    <div class="best-stock-hero">
        <div class="hero-info">
            <span class="badge">🔥 Best Fundamental Pick</span>
            <h2>{{ best_stock.stock_name }}</h2>
            <div class="ticker">{{ best_stock.ticker }}</div>
            
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
            <div class="metric-label" style="text-transform: uppercase; letter-spacing: 0.1em;">Fundamental Score</div>
            <div class="hero-score-val">{{ best_stock.score_display }}</div>
            <div class="metric-label" style="margin-top: 0.5rem;">Rank #1 / 20</div>
        </div>
    </div>

    <!-- Controls -->
    <div class="controls-container">
        <input type="text" id="searchInput" class="search-box" placeholder="Search by stock name or ticker..." onkeyup="filterTable()">
        <div class="filter-group">
            <select id="peFilter" class="filter-select" onchange="filterTable()">
                <option value="all">All PEs</option>
                <option value="low">Low PE (&lt; 25)</option>
                <option value="mid">Mid PE (25 - 50)</option>
                <option value="high">High PE (&gt; 50)</option>
            </select>
            <select id="capFilter" class="filter-select" onchange="filterTable()">
                <option value="all">All Caps</option>
                <option value="large">Large Cap (&gt; ₹20k Cr)</option>
                <option value="mid">Mid/Small Cap (&lt; ₹20k Cr)</option>
            </select>
        </div>
    </div>

    <!-- Table -->
    <div class="table-container">
        <table id="pharmaTable">
            <thead>
                <tr>
                    <th onclick="sortTable(0)">Ticker</th>
                    <th onclick="sortTable(1)">Stock Name</th>
                    <th onclick="sortTable(2, true)">Market Cap</th>
                    <th onclick="sortTable(3, true)">PE</th>
                    <th onclick="sortTable(4, true)">PB</th>
                    <th onclick="sortTable(5, true)">Div Yield</th>
                    <th onclick="sortTable(6, true)">ROE</th>
                    <th onclick="sortTable(7, true)">D/E</th>
                    <th onclick="sortTable(8, true)">Score</th>
                </tr>
            </thead>
            <tbody>
                {% for stock in stocks %}
                <tr data-pe="{{ stock.pe }}" data-cap="{{ stock.market_cap }}">
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

    <script>
        function filterTable() {
            const input = document.getElementById("searchInput").value.toUpperCase();
            const peFilter = document.getElementById("peFilter").value;
            const capFilter = document.getElementById("capFilter").value;
            const table = document.getElementById("pharmaTable");
            const tr = table.getElementsByTagName("tr");

            for (let i = 1; i < tr.length; i++) {
                const tdTicker = tr[i].getElementsByTagName("td")[0];
                const tdName = tr[i].getElementsByTagName("td")[1];
                
                if (tdTicker && tdName) {
                    const textValue = (tdTicker.textContent || tdTicker.innerText) + " " + (tdName.textContent || tdName.innerText);
                    const matchSearch = textValue.toUpperCase().indexOf(input) > -1;
                    
                    const pe = parseFloat(tr[i].getAttribute("data-pe")) || 0;
                    const cap = parseFloat(tr[i].getAttribute("data-cap")) || 0;
                    
                    let matchPE = true;
                    if (peFilter === "low") matchPE = (pe > 0 && pe < 25);
                    else if (peFilter === "mid") matchPE = (pe >= 25 && pe <= 50);
                    else if (peFilter === "high") matchPE = (pe > 50 || pe === 0);
                    
                    let matchCap = true;
                    if (capFilter === "large") matchCap = (cap >= 2e11); // ₹20,000 Cr in INR (2e11 = 200,000,000,000)
                    else if (capFilter === "mid") matchCap = (cap < 2e11);
                    
                    if (matchSearch && matchPE && matchCap) {
                        tr[i].style.display = "";
                    } else {
                        tr[i].style.display = "none";
                    }
                }
            }
        }

        let sortDirections = {};
        function sortTable(colIndex, isNumeric = false) {
            const table = document.getElementById("pharmaTable");
            let switching = true;
            let dir = sortDirections[colIndex] === "asc" ? "desc" : "asc";
            sortDirections[colIndex] = dir;
            
            while (switching) {
                switching = false;
                const rows = table.rows;
                for (let i = 1; i < (rows.length - 1); i++) {
                    let shouldSwitch = false;
                    const x = rows[i].getElementsByTagName("TD")[colIndex];
                    const y = rows[i + 1].getElementsByTagName("TD")[colIndex];
                    
                    let xVal = x.textContent || x.innerText;
                    let yVal = y.textContent || y.innerText;
                    
                    if (isNumeric) {
                        // Strip currency, percentage signs, and Cr label
                        xVal = parseFloat(xVal.replace(/[^\\d.-]/g, '')) || 0;
                        yVal = parseFloat(yVal.replace(/[^\\d.-]/g, '')) || 0;
                    } else {
                        xVal = xVal.toLowerCase();
                        yVal = yVal.toLowerCase();
                    }
                    
                    if (dir === "asc") {
                        if (xVal > yVal) {
                            shouldSwitch = true;
                            break;
                        }
                    } else if (dir === "desc") {
                        if (xVal < yVal) {
                            shouldSwitch = true;
                            break;
                        }
                    }
                }
                if (shouldSwitch) {
                    rows[switching ? 0 : 1].parentNode.insertBefore(rows[switching ? 0 : 1 + 1], rows[switching ? 0 : 1]);
                    // Actually swap rows[i] and rows[i+1]
                    rows[0].parentNode.insertBefore(rows[switching ? 0 : 0], rows[switching ? 0 : 0]);
                    switching = true;
                }
            }
            
            // Standard bubble sort implementation for safety in simple DOM
            const tbody = table.tBodies[0];
            const arr = Array.from(tbody.values ? tbody.values() : tbody.rows);
            arr.sort((a, b) => {
                let aVal = a.cells[colIndex].textContent.trim();
                let bVal = b.cells[colIndex].textContent.trim();
                if (isNumeric) {
                    aVal = parseFloat(aVal.replace(/[^\\d.-]/g, '')) || 0;
                    bVal = parseFloat(bVal.replace(/[^\\d.-]/g, '')) || 0;
                    return dir === "asc" ? aVal - bVal : bVal - aVal;
                }
                return dir === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
            });
            arr.forEach(row => tbody.appendChild(row));
        }
    </script>
</body>
</html>
    """
    
    template = Template(html_template)
    rendered_html = template.render(best_stock=best_stock, stocks=stocks)
    
    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
        
    print(f"Successfully generated HTML report at {HTML_REPORT_PATH}")

if __name__ == "__main__":
    init_databases()
    fetch_and_cache_data()
    rank_and_select_pharma()
    compile_html_report()
