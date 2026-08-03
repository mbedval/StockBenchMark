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
    
    if res_hd.returncode == 0:
        print("Pipeline orchestration completed successfully.")
    else:
        print(f"Pipeline finished, but consolidation report failed with code {res_hd.returncode}.")

if __name__ == "__main__":
    main()
