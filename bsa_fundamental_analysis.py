import os
import re
import subprocess
import sys

CONFIG_FILE = "config/config_analysis.yml"
ANALYSIS_DIR = "libs/analysis"

def parse_config(config_path):
    """Simple robust YAML parser to avoid external PyYAML dependencies."""
    pipelines = []
    if not os.path.exists(config_path):
        print(f"Error: Configuration file {config_path} not found.")
        return pipelines

    current_pipeline = {}
    with open(config_path, "r") as f:
        for line in f:
            # Strip comments and whitespace
            line = line.split('#')[0].strip()
            if not line:
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
                    # Strip outer quotes if any
                    val = val.strip("\"'")
                    
                current_pipeline[key] = val

    if current_pipeline:
        pipelines.append(current_pipeline)
        
    return pipelines

def main():
    print("=" * 80)
    print("                 STOCK BENCHMARK ORCHESTRATOR PIPELINE")
    print("=" * 80)

    pipelines = parse_config(CONFIG_FILE)
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
        # Set PYTHONPATH so libs.utility is importable
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
        
        res = subprocess.run([sys.executable, script_path], env=env)
        
        print("-" * 50)
        if res.returncode == 0:
            print(f"Result: {name} completed successfully.\n")
        else:
            print(f"Result: {name} failed with exit code {res.returncode}.\n")
            # We continue running other enabled scripts instead of hard failing

    # Run consolidation report
    print("=" * 80)
    print("Running Consolidated High Delivery Report...")
    print("=" * 80)
    
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    res_hd = subprocess.run([sys.executable, "libs/analysis/analyze_high_delivery.py"], env=env)
    if res_hd.returncode == 0:
        print("Pipeline orchestration completed successfully.")
    else:
        print(f"Pipeline finished, but consolidation report failed with code {res_hd.returncode}.")

if __name__ == "__main__":
    main()
