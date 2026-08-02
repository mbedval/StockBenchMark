import os
import sqlite3
import pandas as pd
from jinja2 import Template

SELECTED_DB_PATH = "output/db/SelectedStock.db"
HTML_REPORT_PATH = "output/htmls/highDelivery.html"

DELIVERY_TABLES = {
    "delivery_to_trade": "Financial Services",
    "defence_delivery": "Defence",
    "ems_delivery": "EMS",
    "cdmo_delivery": "CDMO",
    "online_services_delivery": "Online Services",
    "telecom_equip_delivery": "Telecom Equipments",
    "datacenter_delivery": "Data Center",
    "oil_gas_logistics_delivery": "Oil & Gas Storage and Transport",
    "diversified_financials_delivery": "Diversified Financials",
    "asset_management_delivery": "Asset Management",
    "specialized_finance_delivery": "Specialized Finance",
    "tech_hardware_delivery": "Technology Hardware"
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
    
    for r in records:
        r['monthly_display'] = f"{r['monthly_avg']*100:.1f}%"
        r['weekly_display'] = f"{r['weekly_avg']*100:.1f}%"
        r['latest_display'] = f"{r['latest_ratio']*100:.1f}%"
        r['prev_display'] = f"{r['prev_day_ratio']*100:.1f}%"
        r['prev_to_prev_display'] = f"{r['prev_to_prev_ratio']*100:.1f}%"
        r['dev_display'] = f"+{r['deviation']*100:.1f}%" if r['deviation'] >= 0 else f"{r['deviation']*100:.1f}%"

    html_template = """
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
            overflow: hidden;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.1);
            backdrop-filter: blur(12px);
            margin: 2rem auto;
            max-width: 1200px;
        }
        
        table {
            width: 100%;
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
    </style>
</head>
<body>

    <header>
        <h1>High Delivery to Trade Spikes</h1>
        <p class="subtitle">Real-time Delivery Ratio Spikes of 1.5x or More Across Screened Sectors</p>
    </header>

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
                            let clean = val.replace(/[₹%Cr,\s]/g, '').trim();
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
</html>
    """

    template = Template(html_template)
    rendered_html = template.render(records=records)

    with open(HTML_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(rendered_html)

    print(f"Successfully generated HTML report at {HTML_REPORT_PATH}")

if __name__ == "__main__":
    generate_report()
