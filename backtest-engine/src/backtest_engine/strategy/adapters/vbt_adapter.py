"""VectorBT adapter for Phase 1: fast vectorized discovery.

Portability note (plan section 3):
  - Signal functions stay pandas-only. The adapter passes them to vectorbt only
    via standard from_signals() entry/exit boolean columns.
  - Cost model is delegated to engine.awaiting CostModel (M3); for discovery
    we use a flat symmetric per-bar fee schedule (defaults ahead of M3).
  - Fill assumption: next-bar open via init_cash + upon_op settings. This is
    the documented look-ahead-defense knob for vectorized backtests.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd

from backtest_engine.strategy.result import BacktestResult


def _import_vbt():
    import vectorbt as vbt  # noqa: PLC0415

    return vbt


class VBTAdapter:
    name = "vectorbt"

    def __init__(self, annualize_factor: int = 252) -> None:
        self._af = annualize_factor
        self._vbt = None  # lazy loaded

    # --- single run --------------------------------------------------------

    def run(
        self,
        signals: pd.DataFrame,
        ohlc: pd.DataFrame,
        *,
        capital: float,
        cost_model: str,
        strategy_name: str,
        universe_ref: str,
        params: dict[str, Any],
        run_id: str | None = None,
    ) -> BacktestResult:
        """Execute a single backtest from pre-computed entry/exit signals.

        `signals` must have either `entry` and `exit` boolean columns aligned
        with `ohlc`'s index, or a single `signals`/`positions` signed column.
        """
        vbt = self._vbt or _import_vbt()
        self._vbt = vbt

        close = ohlc["close"]
        open_price = ohlc["open"]
        # VBT expects signals indexed the same as price.
        # from_signals executes on the supplied price at the signal's bar, so
        # shift observations one bar and use that bar's open for execution.
        entries = signals["entry"].shift(1, fill_value=False).to_numpy()
        exits = (
            signals["exit"].shift(1, fill_value=False).to_numpy()
            if "exit" in signals.columns
            else None
        )

        # `freq` controls time-based metrics; it does not shift fills. The
        # explicit signal shift above is therefore part of the fill policy.
        from backtest_engine.execution.costs import (  # noqa: PLC0415 - lazy
            build_cost_funcs,
        )

        fill_commission, fill_slippage = build_cost_funcs(cost_model)

        pf = vbt.Portfolio.from_signals(
            close,
            entries,
            exits,
            price=open_price,
            init_cash=capital,
            freq="1D",
            upon_opposite_entry="Reverse",
            fees=fill_commission,  # fraction of trade notional charged
            slippage=fill_slippage,
            cash_sharing=True,
        )

        # Extract equity + returns as aligned daily Series.
        equity = _align_series(pf.value())
        returns = _align_series(pf.returns())

        trades: list = []
        try:
            tr = pf.trades.records_readable
            for _, row in tr.iterrows():
                trades.append(_trade_record(row, ohlc, signals.index))
        except Exception:  # noqa: BLE001 - no trades is fine; vbt may return empty df
            trades = []

        return BacktestResult(
            run_id=run_id or f"vbt-{uuid.uuid4().hex[:8]}",
            strategy_name=strategy_name,
            engine=self.name,
            params=dict(params),
            capital=capital,
            cost_model=cost_model,
            universe_ref=universe_ref,
            equity=equity,
            returns=returns,
            trades=trades,
            raw_metrics={
                "total_return_pct": float(pf.total_return() * 100),
                "sharpe": float(pf.sharpe_ratio()),
                "max_drawdown_pct": float(pf.max_drawdown() * 100),
            },
        )

    # --- parameter sweep ---------------------------------------------------

    def sweep(
        self,
        signal_factory,
        ohlc: pd.DataFrame,
        *,
        param_grid: dict[str, list[Any]],
        capital: float,
        cost_model: str,
        strategy_name: str,
        universe_ref: str,
    ) -> list[BacktestResult]:
        """Evaluate the cartesian product of `param_grid` and return one result per combo.

        Phase 1 is *not* using VBT's broadcasted grid sweep — we want each combo
        to live in its own BacktestResult for the validation layer to reason
        about. The toolkit fallback (run from a serialized signal per combo) is
        vectorized already because the underlying vbt.Portfolio is array-aware.
        """
        results: list[BacktestResult] = []
        param_names = list(param_grid.keys())
        # cartesian product of all param values
        grids = pd.DataFrame(_cartesian(param_grid)).rename(columns=dict(enumerate(param_names)))
        for _, row in grids.iterrows():
            params = {k: row[k] for k in param_names}
            signals = signal_factory(ohlc, params)
            res = self.run(
                signals,
                ohlc,
                capital=capital,
                cost_model=cost_model,
                strategy_name=strategy_name,
                universe_ref=universe_ref,
                params=params,
            )
            results.append(res)
        return results


# --- helpers --------------------------------------------------------------


def _cartesian(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Return a list of dicts enumerating the cartesian product of `grid` values."""
    import itertools

    keys = list(grid.keys())
    return [
        dict(zip(keys, combo, strict=False))
        for combo in itertools.product(*[grid[k] for k in keys])
    ]


def _align_series(arr) -> pd.Series:
    """Convert vbt's index to tz-aware UTC if needed."""
    if isinstance(arr, pd.Series):
        s = arr.astype("float64").copy()
        if s.index.tz is None:  # type: ignore[attr-defined]
            s.index = s.index.tz_localize("UTC")  # type: ignore[attr-defined]
        return s
    # ndarray fallback
    return pd.Series(arr, dtype="float64")


def _trade_record(row: pd.Series, ohlc: pd.DataFrame, idx: pd.Index):
    from backtest_engine.strategy.result import TradeRecord  # noqa: PLC0415 - lazy

    # row.entries/exits records_readable has fields like Avg Entry Price etc.
    # We extract the fields we depend on defensively; vbt's fields changed historically.
    def _get(*names: str) -> float | None:
        for nm in names:
            val = row.get(nm)
            if val is not None and not pd.isna(val):
                return float(val)
        return None

    entry_ts = row.get("Entry Timestamp")
    ts = pd.Timestamp(entry_ts) if entry_ts is not None and not pd.isna(entry_ts) else idx[0]
    sym = ohlc.attrs.get("symbol", "UNKNOWN")
    fill = _get("Avg Entry Price", "Entry Price") or 0.0
    qty = _get("Size") or 0.0
    exit_ts = row.get("Exit Timestamp")
    exit_timestamp = pd.Timestamp(exit_ts) if exit_ts is not None and not pd.isna(exit_ts) else None
    return TradeRecord(
        timestamp=pd.Timestamp(ts),
        symbol=sym,
        side="LONG",  # vbt OSS doesn't separately expose short without columns
        quantity=qty,
        fill_price=fill,
        commission=0.0,
        slippage_cost=0.0,
        exit_timestamp=exit_timestamp,
        exit_price=_get("Avg Exit Price", "Exit Price"),
    )
