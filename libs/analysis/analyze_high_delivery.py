import os
import sqlite3
import pandas as pd
from jinja2 import Template

SELECTED_DB_PATH = "output/db/SelectedStock.db"
HTML_REPORT_PATH = "output/htmls/highDelivery.html"

DELIVERY_TABLES = {
    "financials_delivery": "Financial Services",
    "technology_delivery": "Technology & Digital",
    "healthcare_delivery": "Healthcare",
    "chemicals_delivery": "Chemicals",
    "industrials_delivery": "Industrials",
    "defence_delivery": "Defence & Aerospace",
    "infrastructure_delivery": "Infrastructure",
    "power_delivery": "Power & Energy",
    "oil_gas_delivery": "Oil & Gas",
    "automobiles_delivery": "Automobiles",
    "metals_mining_delivery": "Metals & Mining",
    "construction_materials_delivery": "Construction Materials",
    "consumer_delivery": "Consumer Goods",
    "real_estate_delivery": "Real Estate"
}

def generate_report():
    if not os.path.exists(SELECTED_DB_PATH):
        print(f"Database {SELECTED_DB_PATH} not found.")
        return

    conn = sqlite3.connect(SELECTED_DB_PATH)
    all_spikes = []

    for table_name, sector_label in DELIVERY_TABLES.items():
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
        if not cursor.fetchone():
            continue
            
        df = pd.read_sql_query(f"SELECT * FROM {table_name} WHERE is_spike = 1", conn)
        if not df.empty:
            df['sector'] = sector_label
            all_spikes.append(df)

    conn.close()

    if not all_spikes:
        print("No delivery spikes (1.5x or more) found across any sector.")
        combined_df = pd.DataFrame()
    else:
        combined_df = pd.concat(all_spikes, ignore_index=True)
        combined_df = combined_df.sort_values(by='deviation', ascending=False)

    records = combined_df.to_dict(orient='records') if not combined_df.empty else []
    
    conn_cache = sqlite3.connect("data/cache/all_sectors_cache.db")
    for r in records:
        r['monthly_display'] = f"{r['monthly_avg']*100:.1f}%"
        r['weekly_display'] = f"{r['weekly_avg']*100:.1f}%"
        r['latest_display'] = f"{r['latest_ratio']*100:.1f}%"
        r['prev_display'] = f"{r['prev_day_ratio']*100:.1f}%"
        r['prev_to_prev_display'] = f"{r['prev_to_prev_ratio']*100:.1f}%"
        r['dev_display'] = f"+{r['deviation']*100:.1f}%" if r['deviation'] >= 0 else f"{r['deviation']*100:.1f}%"

        # Query volume history
        ticker = r['ticker']
        vol_df = pd.read_sql_query(
            "SELECT date, volume FROM price_history WHERE ticker = ? ORDER BY date DESC LIMIT 3", 
            conn_cache, params=(ticker,)
        )
        if len(vol_df) >= 3:
            vol_today = vol_df.iloc[0]['volume']
            vol_t1 = vol_df.iloc[1]['volume']
            vol_t2 = vol_df.iloc[2]['volume']
            
            avg_last_2 = (vol_t1 + vol_t2) / 2
            ratio = (vol_today / avg_last_2 * 100) if avg_last_2 > 0 else 0.0
            
            r['avg_vol_2d'] = f"{avg_last_2:,.0f}"
            r['today_vol_pct'] = f"{ratio:.1f}%"
        else:
            r['avg_vol_2d'] = "N/A"
            r['today_vol_pct'] = "N/A"
            
    conn_cache.close()

    sector_summary = []
    if not combined_df.empty:
        summary_df = combined_df.groupby('sector').agg(
            avg_deviation=('deviation', 'mean'),
            spike_count=('deviation', 'count')
        ).reset_index()
        summary_df = summary_df.sort_values(by='avg_deviation', ascending=False)
        for _, row in summary_df.iterrows():
            avg_dev = row['avg_deviation']
            color_weight = min(0.65, max(0.12, float(avg_dev) * 1.5))
            border_weight = min(0.85, max(0.25, float(avg_dev) * 2.0))
            sector_summary.append({
                'sector': row['sector'],
                'avg_deviation': avg_dev,
                'spike_count': int(row['spike_count']),
                'dev_display': f"+{avg_dev*100:.1f}%" if avg_dev >= 0 else f"{avg_dev*100:.1f}%",
                'color_weight': f"{color_weight:.2f}",
                'border_weight': f"{border_weight:.2f}"
            })

    html_template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>High Delivery to Trade Spikes (>= 1.5x)</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: rgba(22, 28, 45, 0.7);
            --border-color: rgba(255, 255, 255, 0.08);
            --text-primary: #f3f4f6;
            --text-secondary: #9ca3af;
            --primary-accent: #ec4899; /* Pink theme from AssetManagement */
            --secondary-accent: #10b981; /* Emerald */
            --accent-glow: rgba(236, 72, 153, 0.15);
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
                radial-gradient(at 10% 10%, rgba(236, 72, 153, 0.05) 0px, transparent 50%),
                radial-gradient(at 90% 90%, rgba(16, 185, 129, 0.05) 0px, transparent 50%);
            overflow-x: hidden;
        }
        
        header {
            margin-bottom: 3rem;
            text-align: center;
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(to right, #ec4899, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.1rem;
        }

        /* Table Design */
        .table-container {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow-x: auto;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(12px);
            margin: 2rem auto;
            width: 100%;
            max-width: 1200px;
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
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        tr:last-child td {
            border-bottom: none;
        }

        tr {
            transition: all 0.2s ease;
        }
        
        tr:hover {
            background-color: rgba(255, 255, 255, 0.02);
        }
        
        .ticker-col {
            font-weight: 700;
            color: var(--primary-accent);
        }

        .sector-badge {
            background: rgba(236, 72, 153, 0.15);
            color: #f472b6;
            border: 1px solid rgba(236, 72, 153, 0.3);
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            display: inline-block;
        }

        .spike-badge {
            background: var(--primary-accent);
            color: #ffffff;
            padding: 0.15rem 0.5rem;
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

        .insight-col {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .no-data {
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
            font-size: 1.1rem;
        }
    
        th {
            cursor: pointer;
            user-select: none;
        }
        th:hover {
            background: rgba(255, 255, 255, 0.08) !important;
        }

        /* Heatmap CSS */
        .section-title {
            max-width: 1200px;
            margin: 2.5rem auto 1rem auto;
            font-size: 1.3rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .heatmap-container {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
            gap: 0.6rem;
            max-width: 1200px;
            margin: 0 auto 2rem auto;
        }
        
        .heatmap-card {
            border-radius: 8px;
            padding: 0.5rem 0.65rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.12);
            transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s ease, box-shadow 0.2s ease;
            backdrop-filter: blur(8px);
            cursor: pointer;
            user-select: none;
        }
        
        .heatmap-card:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
        }

        .heatmap-card.active {
            border-color: #ec4899 !important;
            box-shadow: 0 0 12px rgba(236, 72, 153, 0.4);
            transform: scale(1.02) translateY(-1px);
        }
        
        .heatmap-sector-name {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.3rem;
            line-height: 1.2;
        }
        
        .heatmap-stats {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.72rem;
        }
        
        .heatmap-count {
            background: rgba(255, 255, 255, 0.08);
            padding: 0.1rem 0.25rem;
            border-radius: 4px;
            color: var(--text-secondary);
        }
        
        .heatmap-dev {
            font-weight: 700;
            color: #10b981;
        }
    </style>
</head>
<body>

    <header>
        <h1>High Delivery to Trade Spikes</h1>
        <p class="subtitle">Real-time Delivery Ratio Spikes of 1.5x or More Across Screened Sectors</p>
    </header>

    {% if sector_summary %}
    <h2 class="section-title">Sector Activity Heatmap (Avg Spike Deviation)</h2>
    <div class="heatmap-container">
        {% for sec in sector_summary %}
        <div class="heatmap-card" style="background: rgba(16, 185, 129, {{ sec.color_weight }}); border: 1px solid rgba(16, 185, 129, {{ sec.border_weight }});">
            <div class="heatmap-sector-name">{{ sec.sector }}</div>
            <div class="heatmap-stats">
                <span class="heatmap-count">{{ sec.spike_count }} Spikes</span>
                <span class="heatmap-dev">{{ sec.dev_display }}</span>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <div class="table-container">
        {% if records %}
        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Stock Name</th>
                    <th>Sector</th>
                    <th>Monthly Avg</th>
                    <th>Weekly Avg</th>
                    <th>Prev-to-Prev Day</th>
                    <th>Previous Day</th>
                    <th>Latest Ratio</th>
                    <th>Deviation</th>
                    <th>Avg Vol (2D)</th>
                    <th>Today Vol %</th>
                    <th>Validation Insight</th>
                </tr>
            </thead>
            <tbody>
                {% for d in records %}
                <tr>
                    <td class="ticker-col">
                        {{ d.ticker }}
                        <span class="spike-badge">⚡ SPIKE</span>
                    </td>
                    <td>{{ d.stock_name }}</td>
                    <td><span class="sector-badge">{{ d.sector }}</span></td>
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
                    <td style="font-weight: 700; color: #10b981;">
                        {{ d.dev_display }}
                    </td>
                    <td>{{ d.avg_vol_2d }}</td>
                    <td style="font-weight: 600; color: #3b82f6;">{{ d.today_vol_pct }}</td>
                    <td class="insight-col">{{ d.insight }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="no-data">No delivery spikes (1.5x or more) detected across any of the analyzed sectors.</div>
        {% endif %}
    </div>


    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const cards = document.querySelectorAll('.heatmap-card');
            const rows = Array.from(document.querySelectorAll('tbody tr'));
            let activeFilter = null;

            cards.forEach(card => {
                card.addEventListener('click', () => {
                    const sector = card.querySelector('.heatmap-sector-name').textContent.trim();
                    
                    if (activeFilter === sector) {
                        // Clicked same card, reset filter
                        activeFilter = null;
                        card.classList.remove('active');
                        rows.forEach(row => row.style.display = '');
                    } else {
                        // Reset all active classes
                        cards.forEach(c => c.classList.remove('active'));
                        
                        // Set current card active
                        card.classList.add('active');
                        activeFilter = sector;

                        // Filter rows
                        rows.forEach(row => {
                            const rowSector = row.querySelector('.sector-badge').textContent.trim();
                            if (rowSector === sector) {
                                row.style.display = '';
                            } else {
                                row.style.display = 'none';
                            }
                        });
                    }
                });
            });

            document.querySelectorAll('th').forEach(th => {
                th.addEventListener('click', () => {
                    const table = th.closest('table');
                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;
                    const visibleRows = Array.from(tbody.querySelectorAll('tr'));
                    const index = Array.from(th.parentNode.children).indexOf(th);
                    const asc = th.dataset.asc === 'true';
                    th.dataset.asc = !asc;
                    
                    visibleRows.sort((rowA, rowB) => {
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
                    
                    visibleRows.forEach(row => tbody.appendChild(row));
                });
            });
        });
    </script>
</body>
</html>
    """

    template = Template(html_template)
    rendered_html = template.render(records=records, sector_summary=sector_summary)

    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(rendered_html)

    print(f"Successfully generated HTML report at {HTML_REPORT_PATH}")

if __name__ == "__main__":
    generate_report()
