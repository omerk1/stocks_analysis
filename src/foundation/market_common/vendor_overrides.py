"""Hand-reviewed tickers whose yfinance history is wrong and Tiingo's isn't.

yfinance's total-return bars mishandle some spin-offs and stock dividends:
usually a fake one-day move on the event date (DHR +45% on the Fortive
spin-off), sometimes a slow drift (T's dividends before its 2022 spin-off).
Found by comparing every S&P 500 / Nasdaq-100 member's yfinance and Tiingo
daily returns, 2010-2021 (backlog: spin-off check), and confirmed per ticker
against Tiingo's raw closes and dividends.

For the modules in `price_basis.MODULES_WITH_FALLBACK`, a ticker listed here
is read from Tiingo on both bases (one vendor per ticker, never spliced),
with Tiingo's splits. Its Tiingo bars must be stored first:
`python -m src.foundation.data_processing.bulk_tiingo_ingest --store-preferred`
(rerun with each bar refresh -- they stop at the fetch date).

Adding a ticker here turns off its yfinance entries in `price_disputes.csv`;
check whether its Tiingo bars need entries of their own.

ticker -> why: the event, its date, and the measured yfinance-vs-Tiingo gap.
"""

PREFER_TIINGO: dict[str, str] = {
    # Before the 2022 WarnerMedia spin-off yfinance mis-scales T's dividends: a
    # slow drift (2010-2021 total return 2.14x vs 1.71x from T's actual dividends,
    # which Tiingo matches), with no single bad day that masking could remove.
    "T": "yfinance total-return drift before the 2022 spin-off (+25% over 2010-2021)",
}
