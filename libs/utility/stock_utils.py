import sqlite3
import datetime
import random
import numpy as np
import pandas as pd
import yfinance as yf

def init_cache_db(cache_db_path):
    """Initialize SQLite cache database tables."""
    conn = sqlite3.connect(cache_db_path)
    cursor = conn.cursor()
    cursor.execute("""
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
    cursor.execute("""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_history (
            ticker TEXT,
            date TEXT,
            delivery_ratio REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.commit()
    conn.close()

def generate_trading_dates(days=35):
    """Generate the last N trading days (excluding weekends)."""
    dates = []
    curr = datetime.date.today()
    while len(dates) < days:
        if curr.weekday() < 5:  # Monday to Friday
            dates.append(curr.isoformat())
        curr -= datetime.timedelta(days=1)
    dates.reverse()
    return dates

def generate_synthetic_data(ticker, sector, s0=None, growth=0.15, volatility=0.30):
    """Generate realistic synthetic EOD stock prices and fundamentals as fallback."""
    if s0 is None:
        s0 = random.uniform(100, 8000)
    days = 252
    dt = 1 / 252
    
    prices = [s0]
    for _ in range(days - 1):
        price = prices[-1] * np.exp((growth - 0.5 * volatility**2) * dt + volatility * np.sqrt(dt) * np.random.normal())
        prices.append(price)
        
    start_date = datetime.date.today() - datetime.timedelta(days=365)
    date_list = [ (start_date + datetime.timedelta(days=i)).isoformat() for i in range(days) ]
    
    history = []
    for i, date in enumerate(date_list):
        history.append({
            'date': date,
            'open': prices[i] * random.uniform(0.98, 1.02),
            'high': prices[i] * random.uniform(1.00, 1.04),
            'low': prices[i] * random.uniform(0.96, 1.00),
            'close': prices[i],
            'volume': int(random.uniform(20000, 1500000))
        })
        
    fundamentals = {
        'stock_name': ticker.split('.')[0] + " Ltd (Synthetic)",
        'sector': sector,
        'market_cap': random.uniform(1e10, 1e12),
        'pe': random.uniform(15.0, 85.0),
        'pb': random.uniform(2.0, 15.0),
        'dividend_yield': random.uniform(0.0, 3.0),
        'pat': random.uniform(1e8, 5e10),
        'roe': random.uniform(8.0, 25.0),
        'debt_to_equity': random.uniform(0.0, 2.5)
    }
    return history, fundamentals

def fetch_and_cache_ticker(cache_db_path, ticker, sector, today_str, spike_chance=0.30):
    """Fetch ticker details from yfinance and save/update inside SQLite cache database."""
    init_cache_db(cache_db_path)
    conn_cache = sqlite3.connect(cache_db_path)
    cursor_cache = conn_cache.cursor()
    
    try:
        cursor_cache.execute("SELECT last_updated FROM raw_fundamentals WHERE ticker = ?", (ticker,))
        row = cursor_cache.fetchone()
        if row and row[0] == today_str:
            conn_cache.close()
            return f"{ticker}: Cache hit"
            
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if hist.empty:
            raise ValueError("No price history")
            
        info = stock.info
        stock_name = info.get('longName', ticker.split('.')[0])
        market_cap = info.get('marketCap') or info.get('enterpriseValue') or 0.0
        pe = info.get('trailingPE') or info.get('forwardPE')
        pb = info.get('priceToBook')
        div_yield = (info.get('dividendYield') or 0.0) * 100.0
        roe = (info.get('returnOnEquity') or 0.0) * 100.0
        debt_equity = (info.get('debtToEquity') or 0.0) / 100.0
        
        pat = None
        try:
            pat = info.get('netIncomeToCommon')
            if pat is None and not stock.financials.empty:
                if 'Net Income' in stock.financials.index:
                    pat = float(stock.financials.loc['Net Income'].iloc[0])
        except Exception:
            pass
            
        if pat is None: pat = 0.0
        if pe is None: pe = 0.0
        if pb is None: pb = 0.0
        
        # Save EOD historical prices
        for idx, r in hist.iterrows():
            date_str = idx.strftime('%Y-%m-%d')
            cursor_cache.execute("""
                INSERT OR REPLACE INTO price_history (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, date_str, r['Open'], r['High'], r['Low'], r['Close'], int(r['Volume'])))
            
        # Save raw fundamentals
        cursor_cache.execute("""
            INSERT OR REPLACE INTO raw_fundamentals (ticker, stock_name, sector, market_cap, pe, pb, dividend_yield, pat, roe, debt_to_equity, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, stock_name, sector, market_cap, pe, pb, div_yield, pat, roe, debt_equity, today_str))
        
        # Generate and cache delivery data
        dates = generate_trading_dates(35)
        base_delivery = random.uniform(0.30, 0.55)
        last_delivery = base_delivery
        for idx, d in enumerate(dates):
            s_chance = spike_chance if idx == len(dates) - 1 else 0.08
            if random.random() < s_chance:
                delivery_ratio = min(0.85, last_delivery * random.uniform(1.5, 1.8))
            else:
                delivery_ratio = max(0.15, min(0.70, base_delivery + random.uniform(-0.08, 0.08)))
            
            cursor_cache.execute("""
                INSERT OR REPLACE INTO delivery_history (ticker, date, delivery_ratio)
                VALUES (?, ?, ?)
            """, (ticker, d, delivery_ratio))
            last_delivery = delivery_ratio

        conn_cache.commit()
        conn_cache.close()
        return f"{ticker}: Successfully downloaded and cached"
        
    except Exception as e:
        hist, fundamentals = generate_synthetic_data(ticker, sector)
        for r in hist:
            cursor_cache.execute("""
                INSERT OR REPLACE INTO price_history (ticker, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ticker, r['date'], r['open'], r['high'], r['low'], r['close'], r['volume']))
            
        cursor_cache.execute("""
            INSERT OR REPLACE INTO raw_fundamentals (ticker, stock_name, sector, market_cap, pe, pb, dividend_yield, pat, roe, debt_to_equity, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ticker, fundamentals['stock_name'], sector, fundamentals['market_cap'], fundamentals['pe'],
              fundamentals['pb'], fundamentals['dividend_yield'], fundamentals['pat'],
              fundamentals['roe'], fundamentals['debt_to_equity'], today_str))
              
        dates = generate_trading_dates(35)
        base_delivery = random.uniform(0.30, 0.55)
        last_delivery = base_delivery
        for idx, d in enumerate(dates):
            s_chance = spike_chance if idx == len(dates) - 1 else 0.08
            if random.random() < s_chance:
                delivery_ratio = min(0.85, last_delivery * random.uniform(1.5, 1.8))
            else:
                delivery_ratio = max(0.15, min(0.70, base_delivery + random.uniform(-0.08, 0.08)))
            
            cursor_cache.execute("""
                INSERT OR REPLACE INTO delivery_history (ticker, date, delivery_ratio)
                VALUES (?, ?, ?)
            """, (ticker, d, delivery_ratio))
            last_delivery = delivery_ratio

        conn_cache.commit()
        conn_cache.close()
        return f"{ticker}: Failed yfinance, synthetic generated"

def rank_and_score_stocks(df):
    """Calculate sector-relative percentile ranks and overall composite score."""
    if df.empty:
        return df
        
    df['pe'] = df['pe'].apply(lambda x: 999.0 if x <= 0 or pd.isna(x) else x)
    df['pb'] = df['pb'].apply(lambda x: 99.0 if x <= 0 or pd.isna(x) else x)
    df['roe'] = df['roe'].fillna(0.0)
    df['debt_to_equity'] = df['debt_to_equity'].fillna(1.5)
    
    # Calculate ranks grouped by sector
    df['pe_rank'] = df.groupby('sector')['pe'].rank(ascending=True, pct=True)
    df['pb_rank'] = df.groupby('sector')['pb'].rank(ascending=True, pct=True)
    df['roe_rank'] = df.groupby('sector')['roe'].rank(ascending=False, pct=True)
    df['de_rank'] = df.groupby('sector')['debt_to_equity'].rank(ascending=True, pct=True)
    df['div_rank'] = df.groupby('sector')['dividend_yield'].rank(ascending=False, pct=True)
    df['pat_rank'] = df.groupby('sector')['pat'].rank(ascending=False, pct=True)
    
    for col in ['pe_rank', 'pb_rank', 'roe_rank', 'de_rank', 'div_rank', 'pat_rank']:
        df[col] = df[col].fillna(0.5)
        
    df['score'] = (
        0.25 * (1 - df['roe_rank']) +
        0.20 * (1 - df['pe_rank']) +
        0.20 * (1 - df['pb_rank']) +
        0.15 * (1 - df['de_rank']) +
        0.10 * (1 - df['pat_rank']) +
        0.10 * (1 - df['div_rank'])
    ) * 100.0
    
    return df
