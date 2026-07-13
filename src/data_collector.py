"""Legacy data collector compatibility module.

The old collector was replaced by dedicated SnapTrade and Databento pipelines.
This module exists so stale validation/import checks fail gracefully instead of
raising ModuleNotFoundError.
"""


def update_all_data(*_args, **_kwargs):
    raise RuntimeError(
        "data_collector.py was retired. Use SnapTrade sync and Databento OHLCV "
        "pipelines instead."
    )
