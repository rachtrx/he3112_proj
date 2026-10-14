"""Reusable analysis functions for the final HE3112 notebook.

Data extraction is handled by depreciation_notes.py. This module reads prepared
workbook data and provides model, counterfactual and event-study functions.
All dollar values in analysis tables are USD billions.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'data/final_analysis'
URLS = {
    'META_2021': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680122000018/fb-20211231.htm',
    'META_2022': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680123000013/meta-20221231.htm',
    'META_2023': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680124000012/meta-20231231.htm',
    'META_2024': 'https://www.sec.gov/Archives/edgar/data/1326801/000132680125000017/meta-20241231.htm',
    'META_2025': 'https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm',
    'AMZN_2025': 'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm',
    'AMZN_2024': 'https://www.sec.gov/Archives/edgar/data/1018724/000101872425000004/amzn-20241231.htm',
    'META_release': 'https://investor.atmeta.com/files/doc_financials/2024/q4/Meta-12-31-2024-Exhibit-99-1-FINAL.pdf',
    'AMZN_release': 'https://s2.q4cdn.com/299287126/files/doc_financials/2024/q4/AMZN-Q4-2024-Earnings-Release.pdf',
    'AMZN_2024_release': 'https://ir.aboutamazon.com/news-release/news-release-details/2024/Amazon-com-Announces-Fourth-Quarter-Results/default.aspx',
    'IAS16': 'https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2022/issued/part-a/ias-16-property-plant-and-equipment.pdf',
    'ASC250': 'https://storage.fasb.org/PCC%20SBAC-Topic%205-20240625.pdf',
    'MLPerf': 'https://mlcommons.org/2024/11/new-mlperf-training-v4-1-benchmarks-highlight-industrys-focus-on-new-systems-and-generative-ai-applications/',
}


def load_server_disclosures(workbook=None):
    """Load the prepared server-note sheet; no HTML parsing or network access.

    The sheet is built by ``depreciation_notes.py`` from the local 10-K HTML
    files. Keeping this reader separate makes the final notebook a consumer of
    prepared data rather than a data-extraction script.
    """
    path = Path(workbook) if workbook else ROOT / 'data/depreciation_analysis.xlsx'
    frame = pd.read_excel(path, sheet_name='server_disclosures')
    required = {'ticker', 'fiscal_year', 'server_gross_bn', 'ppe_gross_bn',
                'ppe_net_bn', 'accumulated_dep_bn', 'server_share_gross_pct'}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f'{path} server_disclosures is missing columns: {sorted(missing)}')
    assert np.allclose(frame.ppe_gross_bn - frame.accumulated_dep_bn, frame.ppe_net_bn)
    return frame.sort_values(['ticker', 'fiscal_year']).reset_index(drop=True)


def disclosed_changes():
    return pd.DataFrame([
        dict(ticker='AMZN', fiscal_year=2024, change='Servers: 5 → 6 years', dep_effect_bn=-3.2,
             ni_effect_bn=2.5, source=URLS['AMZN_2024'], scope='2023 year-end assets + 2024 acquisitions'),
        dict(ticker='META', fiscal_year=2025, change='Most servers/network: extended to 5.5 years', dep_effect_bn=-2.92,
             ni_effect_bn=2.59, source=URLS['META_2025'], scope='Assets in service at 2024 year-end'),
        dict(ticker='AMZN', fiscal_year=2025, change='Subset servers/network: 6 → 5 years', dep_effect_bn=1.4,
             ni_effect_bn=-1., source=URLS['AMZN_2025'], scope='2024 year-end assets + 2025 acquisitions'),
    ])


def no_change_counterfactual(numbers):
    cf = disclosed_changes().merge(numbers, on=['ticker', 'fiscal_year'], validate='one_to_one')
    cf['dep_no_change_bn'] = cf.depreciation_bn - cf.dep_effect_bn
    cf['op_no_change_bn'] = cf.operating_income_bn + cf.dep_effect_bn
    cf['ni_no_change_bn'] = cf.net_income_bn - cf.ni_effect_bn
    cf['op_margin_effect_pp'] = -100 * cf.dep_effect_bn / cf.revenue_bn
    cf['ni_margin_effect_pp'] = 100 * cf.ni_effect_bn / cf.revenue_bn
    cf['ni_effect_pct_reported'] = 100 * cf.ni_effect_bn / cf.net_income_bn
    assert np.allclose(cf.op_no_change_bn + cf.dep_no_change_bn,
                       cf.operating_income_bn + cf.depreciation_bn)
    assert (cf.loc[cf.dep_effect_bn < 0, 'op_no_change_bn'] < cf.loc[cf.dep_effect_bn < 0, 'operating_income_bn']).all()
    return cf


def depreciation_weights(method, life):
    """Zero residual, half-year convention. All schedules allocate exactly 100%."""
    if method == 'Straight-line': weights = np.repeat(1/life, life)
    elif method == 'Sum-of-years-digits': weights = np.arange(life, 0, -1) / (life*(life+1)/2)
    elif method == 'Double-declining':
        book, charges = 1., []
        for age in range(life):
            charge = min(book, max(2/life*book, book/(life-age)))
            charges.append(charge)
            book -= charge
        weights = np.array(charges)
    else: raise ValueError(method)
    half_year = np.convolve(weights, [.5, .5])
    assert np.isclose(half_year.sum(), 1) and (half_year >= 0).all()
    return half_year


def expansion_model(servers, numbers, life=5, replacement=0., tax=.21, start=2021, end=2025):
    """Method sensitivity for Meta additions since start; opening assets unchanged.

    Gross additions inferred from net stock growth plus assumed removals. Removals
    are restricted to the opening fully-depreciated stock in the sensitivity; no
    modelled post-start cohort is retired. This is a hypothetical transition, not
    an estimated complete fleet or a fitted economic depreciation function.
    """
    stock = servers[servers.ticker.eq('META')].set_index('fiscal_year').server_gross_bn
    years = np.arange(start, end+1)
    opening = stock.loc[start-1]
    additions, removed = [], 0.
    for year in years:
        disposal = replacement * stock.loc[year-1]
        removed += disposal
        assert removed <= opening + 1e-9, 'Assumed removals exceed opening stock; reduce replacement rate.'
        addition = stock.loc[year] - stock.loc[year-1] + disposal
        assert addition >= 0, 'Negative inferred additions require a different stock model.'
        additions.append(addition)
    sl = np.convolve(additions, depreciation_weights('Straight-line', life))[:len(years)]
    reported = numbers[numbers.ticker.eq('META')].set_index('fiscal_year')
    rows = []
    for method in ['Straight-line', 'Sum-of-years-digits', 'Double-declining']:
        dep = np.convolve(additions, depreciation_weights(method, life))[:len(years)]
        cumulative = 0.
        for i, year in enumerate(years):
            r = reported.loc[year]
            delta = dep[i]-sl[i]
            cumulative += delta
            observed_server = servers[(servers.ticker=='META') & (servers.fiscal_year==year)].server_dep_bn.iloc[0]
            rows.append(dict(fiscal_year=year, method=method, life=life, replacement=replacement, tax=tax,
                             inferred_additions_bn=additions[i], cohort_dep_bn=dep[i], model_sl_bn=sl[i],
                             reported_server_dep_bn=observed_server, unmodelled_server_residual_bn=observed_server-sl[i],
                             delta_dep_bn=delta, cumulative_delta_bn=cumulative,
                             op_effect_bn=-delta, ni_effect_bn=-delta*(1-tax),
                             op_margin_effect_pp=-100*delta/r.revenue_bn,
                             ni_margin_effect_pp=-100*delta*(1-tax)/r.revenue_bn,
                             adjusted_op_bn=r.operating_income_bn-delta,
                             adjusted_ni_bn=r.net_income_bn-delta*(1-tax),
                             adjusted_total_dep_bn=r.depreciation_bn+delta,
                             adjusted_ppe_net_bn=r.ppe_net_bn-cumulative,
                             revenue_bn=r.revenue_bn))
    return pd.DataFrame(rows)


def load_prices():
    """Load the prepared local adjusted-price file used by the notebook."""
    path = OUTPUT / 'adjusted_daily_prices.csv'
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    raise FileNotFoundError(f'{path} is missing. Run market_data.py first, then rerun the notebook.')


def market_events():
    return pd.DataFrame([
        dict(label='Amazon: extension', ticker='AMZN', announcement='2024-02-01', day0='2024-02-02',
             source=URLS['AMZN_2024_release'], context='Q4 results, AWS growth, Q1 earnings guidance'),
        dict(label='Meta: extension', ticker='META', announcement='2025-01-29', day0='2025-01-30',
             source=URLS['META_release'], context='Q4 results, 2025 expense/capex guidance'),
        dict(label='Amazon: shortening', ticker='AMZN', announcement='2025-02-06', day0='2025-02-07',
             source=URLS['AMZN_release'], context='Q4 results/call and next-day 10-K; Q1 guidance, AI spending'),
    ])


def event_study(px):
    returns = px.pct_change(fill_method=None).dropna()
    windows, summaries = [], []
    for e in market_events().itertuples():
        loc = returns.index.get_loc(pd.Timestamp(e.day0))
        estimate = returns.iloc[loc-250:loc-30]
        assert len(estimate) == 220
        X = np.column_stack([np.ones(len(estimate)), estimate.SPY])
        coef = np.linalg.lstsq(X, estimate[e.ticker], rcond=None)[0]
        window = returns.iloc[loc-10:loc+11].copy()
        assert len(window)==21
        window['event_day'] = np.arange(-10,11)
        window['ar_market_model'] = window[e.ticker] - (coef[0] + coef[1]*window.SPY)
        window['ar_market_adjusted'] = window[e.ticker] - window.SPY
        window['label'] = e.label
        window['car'] = window.ar_market_model.cumsum()
        window['car'] -= window.loc[window.event_day.eq(-1),'car'].iloc[0]
        windows.append(window.reset_index(names='date'))
        for lo, hi in [(-1,1),(0,1),(0,5)]:
            w = window[window.event_day.between(lo,hi)]
            summaries.append(dict(event=e.label, day0=e.day0, window=f'[{lo},+{hi}]', observations=len(w),
                                  market_model_car_pct=100*w.ar_market_model.sum(),
                                  market_adjusted_car_pct=100*w.ar_market_adjusted.sum(), beta=coef[1],
                                  estimation_observations=len(estimate)))
    return pd.concat(windows, ignore_index=True), pd.DataFrame(summaries)
