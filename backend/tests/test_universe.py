"""Universe resolution combines watchlist + curated ETFs."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, WatchlistItem
from app.services.universe import resolve_universe


def _mk_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_resolve_universe_includes_curated_etfs():
    db = _mk_session()
    universe = resolve_universe(db)
    tickers = {e.ticker for e in universe}
    # A few staples we expect to always be present:
    assert "VWRL.L" in tickers
    assert "IWDA.L" in tickers
    assert "CSPX.L" in tickers


def test_resolve_universe_includes_watchlist():
    db = _mk_session()
    db.add(WatchlistItem(ticker="AAPL", note="favourite"))
    db.add(WatchlistItem(ticker="MSFT"))
    db.commit()
    universe = resolve_universe(db)
    aapl = next(e for e in universe if e.ticker == "AAPL")
    assert aapl.source == "watchlist"
    assert aapl.note == "favourite"


def test_watchlist_etf_overlap_keeps_watchlist_source():
    db = _mk_session()
    db.add(WatchlistItem(ticker="VWRL.L", note="my world tracker"))
    db.commit()
    universe = resolve_universe(db)
    vwrl = next(e for e in universe if e.ticker == "VWRL.L")
    assert vwrl.source == "watchlist"
    # but metadata from curated list should be merged in
    assert vwrl.asset_type == "etf"
    assert vwrl.metadata is not None
    assert vwrl.metadata.get("domicile") == "IE"
