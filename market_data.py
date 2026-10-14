"""Acquire and cache adjusted market prices used by the final notebook.

This is deliberately separate from analysis_support.py: the notebook reads the
local cache and never downloads market data during execution.
"""
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'data/final_analysis'


def download_prices():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    series = []
    for ticker in ['META', 'AMZN', 'SPY']:
        frame = yf.Ticker(ticker).history(
            start='2023-01-01', end='2025-03-01',
            auto_adjust=True, actions=False
        )
        if frame.empty:
            raise RuntimeError(f'No prices returned for {ticker}')
        close = frame['Close'].copy()
        close.index = close.index.tz_localize(None).normalize()
        series.append(close.rename(ticker))

    prices = pd.concat(series, axis=1).dropna()
    prices.to_csv(OUTPUT / 'adjusted_daily_prices.csv', index_label='date')
    pd.DataFrame([{
        'provider': 'Yahoo Finance via yfinance',
        'auto_adjust': True,
        'downloaded_utc': pd.Timestamp.now(tz='UTC').isoformat(),
        'start': '2023-01-01',
        'end_exclusive': '2025-03-01',
    }]).to_csv(OUTPUT / 'price_provenance.csv', index=False)
    print(f'Wrote {len(prices):,} rows to {OUTPUT / "adjusted_daily_prices.csv"}')


if __name__ == '__main__':
    download_prices()
