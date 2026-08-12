import os
import re
import subprocess
import sys

CONFIG_FILE = "config/config_analysis.yml"
ANALYSIS_DIR = "libs/analysis"

def parse_config(config_path):
    """Simple robust YAML parser to avoid external PyYAML dependencies."""
    pipelines = []
    globals_dict = {}
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        return pipelines, globals_dict

    current_pipeline = {}
    in_pipelines = False
    
    with open(config_path, "r") as f:
        for line in f:
            # Strip comments and whitespace
            line = line.split('#')[0].strip()
            if not line:
                continue
            
            if line.startswith("pipelines:"):
                in_pipelines = True
                continue
                
            if not in_pipelines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    globals_dict[key] = val
                continue
            
            # Start of a list item
            if line.startswith("-"):
                if current_pipeline:
                    pipelines.append(current_pipeline)
                    current_pipeline = {}
                line = line.lstrip("- ").strip()
                
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                
                # Parse values
                if val.lower() == "true":
                    val = True
                elif val.lower() == "false":
                    val = False
                else:
                    val = val.strip("\"'")
                    
                current_pipeline[key] = val

    if current_pipeline:
        pipelines.append(current_pipeline)
        
    return pipelines, globals_dict

def generate_watchlist(watchlist_path):
    """Generates the fundamental watchlist based on SelectedStock.db records."""
    import sqlite3
    import pandas as pd
    
    print(f"Generating watchlist for spiked stocks (deviation >= 5%)...")
    selected_db = "output/db/SelectedStock.db"
    if not os.path.exists(selected_db):
        print("Selected Stock DB not found, skipping watchlist generation.")
        return
        
    conn = sqlite3.connect(selected_db)
    
    # Retrieve all sector mapping tables dynamically from SelectedStock.db
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall()]
    
    # Identify sector-delivery table pairs
    sector_tables = [t for t in tables if not t.endswith('_delivery') and f"{t}_delivery" in tables]
    unique_tickers = set()
    
    for sector_key in sector_tables:
        delivery_table = f"{sector_key}_delivery"
        
        try:
            del_df = pd.read_sql_query(f"""
                SELECT ticker, deviation 
                FROM {delivery_table} 
                WHERE is_spike = 1 AND deviation >= 0.05
            """, conn)
            
            if del_df.empty:
                continue
                
            fund_df = pd.read_sql_query(f"SELECT ticker, score FROM {sector_key}", conn)
            
            merged = pd.merge(del_df, fund_df, on='ticker', how='inner')
            if merged.empty:
                continue
                
            top_5 = merged.sort_values(by='score', ascending=False).head(5)
            for ticker in top_5['ticker']:
                unique_tickers.add(ticker)
        except Exception as e:
            print(f"Error compiling watchlist for sector {sector_key}: {e}")
            
    conn.close()
    
    if not unique_tickers:
        print("No spiked stocks matching criteria found. Watchlist not created.")
        return
        
    sorted_tickers = sorted(list(unique_tickers))
    
    # Ensure parent directory exists
    parent_dir = os.path.dirname(watchlist_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
        
    with open(watchlist_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(sorted_tickers))
        
    print(f"Watchlist successfully generated at {watchlist_path}")

def main():
    print("=" * 80)
    print("                 STOCK BENCHMARK ORCHESTRATOR PIPELINE")
    print("=" * 80)

    pipelines, globals_dict = parse_config(CONFIG_FILE)
    if not pipelines:
        print("No pipelines found in configuration or config file missing.")
        sys.exit(1)

    print(f"Loaded {len(pipelines)} pipelines from {CONFIG_FILE}.\n")
    
    # Run each enabled analysis script
    for idx, pipe in enumerate(pipelines):
        name = pipe.get("name")
        enabled = pipe.get("enabled", False)
        
        if not name:
            continue
            
        if not enabled:
            print(f"[{idx+1}/{len(pipelines)}] Skipping {name} (Disabled)")
            continue
            
        script_path = os.path.join(ANALYSIS_DIR, name)
        if not os.path.exists(script_path):
            print(f"[{idx+1}/{len(pipelines)}] Error: Script {script_path} does not exist!")
            continue

        print(f"[{idx+1}/{len(pipelines)}] Running {name}...")
        print("-" * 50)
        
        # Run script in a separate process
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
        
        res = subprocess.run([sys.executable, script_path], env=env)
        
        print("-" * 50)
        if res.returncode == 0:
            print(f"Result: {name} completed successfully.\n")
        else:
            print(f"Result: {name} failed with exit code {res.returncode}.\n")

    # Run consolidation report
    print("=" * 80)
    print("Running Consolidated High Delivery Report...")
    print("=" * 80)
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    res_hd = subprocess.run([sys.executable, "libs/analysis/analyze_high_delivery.py"], env=env)
    
    # Generate Watchlist
    watchlist_path = None
    if os.path.exists("config/config.yml"):
        try:
            _, main_globals = parse_config("config/config.yml")
            watchlist_path = main_globals.get("watchlistpath")
        except Exception as e:
            print(f"Warning: Could not parse config/config.yml: {e}")
            
    if not watchlist_path:
        watchlist_path = globals_dict.get("watchlistpath", "watchlist_fundamental.txt")

    print("=" * 80)
    generate_watchlist(watchlist_path)
    print("=" * 80)

    # Generate Index Hub HTML
    generate_index_html()
    print("=" * 80)
    
    if res_hd.returncode == 0:
        print("Pipeline orchestration completed successfully.")
    else:
        print(f"Pipeline finished, but consolidation report failed with code {res_hd.returncode}.")

def generate_index_html():
    """Generates a central directory index.html hub connecting all reports."""
    import glob
    from jinja2 import Template
    
    htmls_dir = "output/htmls"
    index_path = os.path.join(htmls_dir, "index.html")
    
    print("Generating directory index HTML hub...")
    
    # Find all html files in output/htmls/
    html_files = glob.glob(os.path.join(htmls_dir, "*.html"))
    
    sectors = []
    high_delivery = None
    
    for fpath in html_files:
        basename = os.path.basename(fpath)
        if basename == "index.html":
            continue
        elif basename == "highDelivery.html":
            high_delivery = {
                "name": "High Delivery Spikes",
                "filename": basename,
                "description": "Consolidated dashboard of stocks with spikes in delivery-to-trade volume ratio (>= 1.5x deviation)."
            }
        else:
            name_no_ext = os.path.splitext(basename)[0]
            # Split CamelCase to spaced titles
            spaced_name = re.sub(r'(?<!^)(?=[A-Z])', ' ', name_no_ext)
            sectors.append({
                "name": spaced_name,
                "filename": basename
            })
            
    sectors.sort(key=lambda x: x["name"])

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Benchmark Analytics Hub</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --primary-accent: #3b82f6;
            --secondary-accent: #ec4899;
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
            padding: 3rem 2rem;
            background-image: 
                radial-gradient(at 10% 10%, rgba(59, 130, 246, 0.05) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(236, 72, 153, 0.05) 0px, transparent 50%);
        }
        
        header {
            text-align: center;
            margin-bottom: 4rem;
        }
        
        h1 {
            font-size: 2.8rem;
            font-weight: 700;
            background: linear-gradient(to right, #3b82f6, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.2rem;
        }
        
        .section-container {
            max-width: 1100px;
            margin: 0 auto 4rem auto;
        }
        
        .section-title {
            font-size: 1.6rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            border-left: 4px solid var(--primary-accent);
            padding-left: 0.75rem;
            color: var(--text-primary);
        }
        
        .grid-layout {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1.5rem;
        }
        
        .hub-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            text-decoration: none;
            color: inherit;
            transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s ease, box-shadow 0.2s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(10px);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            height: 100%;
        }
        
        .hub-card:hover {
            transform: translateY(-4px);
            border-color: var(--primary-accent);
            box-shadow: 0 8px 24px rgba(59, 130, 246, 0.2);
        }
        
        .delivery-card:hover {
            border-color: var(--secondary-accent);
            box-shadow: 0 8px 24px rgba(236, 72, 153, 0.2);
        }
        
        .card-name {
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
        }
        
        .card-desc {
            font-size: 0.9rem;
            color: var(--text-secondary);
            line-height: 1.4;
        }
        
        .card-link-text {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--primary-accent);
            margin-top: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .delivery-card .card-link-text {
            color: var(--secondary-accent);
        }
        
        .card-link-text::after {
            content: '→';
            transition: transform 0.2s ease;
        }
        
        .hub-card:hover .card-link-text::after {
            transform: translateX(4px);
        }
    </style>
</head>
<body>
    <header>
        <h1>Stock Benchmark Hub</h1>
        <p class="subtitle">Comprehensive Sectoral Fundamentals & Volumetric Spike Reports</p>
    </header>

    {% if high_delivery %}
    <div class="section-container">
        <h2 class="section-title" style="border-left-color: var(--secondary-accent);">Consolidated Volumetric Analytics</h2>
        <div style="max-width: 500px;">
            <a href="{{ high_delivery.filename }}" class="hub-card delivery-card">
                <div>
                    <div class="card-name">{{ high_delivery.name }}</div>
                    <div class="card-desc">{{ high_delivery.description }}</div>
                </div>
                <div class="card-link-text">Open Spikes Dashboard</div>
            </a>
        </div>
    </div>
    {% endif %}

    <div class="section-container">
        <h2 class="section-title">Sectoral Fundamental Analysis</h2>
        <div class="grid-layout">
            {% for s in sectors %}
            <a href="{{ s.filename }}" class="hub-card">
                <div>
                    <div class="card-name">{{ s.name }}</div>
                    <div class="card-desc">Detailed EOD fundamental scores, growth parameters, and valuation metric comparisons.</div>
                </div>
                <div class="card-link-text">Open Sector Report</div>
            </a>
            {% endfor %}
        </div>
    </div>
</body>
</html>"""

    t = Template(html_template)
    rendered = t.render(sectors=sectors, high_delivery=high_delivery)
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Directory index successfully compiled at {index_path}")

if __name__ == "__main__":
    main()
