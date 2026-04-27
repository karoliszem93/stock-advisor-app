"""News sentiment module.

Three-source approach, in priority order:
  1. Use Finnhub's pre-computed news-sentiment score when available
     (their model gives a -1..+1 sentiment per ticker, weighted by recency).
  2. Fall back to a lightweight finance-keyword polarity scorer over the
     headlines themselves.
  3. The LLM analyst layer (Phase 3) gets the raw headlines and can read
     them in context — that's the deeper read.

This module's score is bounded at ±0.30 to avoid noisy signals over-
weighting the synthesis.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)

# Finance-tuned positive / negative keyword lists. Not a substitute for a
# real ML model but adequate as a fallback signal.
_POS = {
    "beat", "beats", "outperform", "upgrade", "upgraded", "raise", "raises", "raised",
    "record", "rally", "surge", "soar", "soars", "growth", "expansion", "buyback",
    "dividend", "guidance", "approves", "approval", "exceeds", "stronger",
    "exceeded", "tops", "boosts", "expanding", "robust",
}
_NEG = {
    "miss", "missed", "downgrade", "downgraded", "cut", "cuts", "cutting", "warning",
    "lawsuit", "settle", "settles", "fraud", "investigation", "probe", "fine",
    "decline", "drop", "plunge", "plunges", "tumble", "tumbles", "weak", "weakens",
    "loss", "losses", "halts", "halted", "recall", "delay", "delays", "bankruptcy",
    "shrink", "slump", "slumps",
}


class NewsSentimentModule(BaseAnalysisModule):
    name = "news_sentiment"
    description = "Recent headline sentiment via Finnhub's score + keyword fallback."

    HORIZON_WEIGHTS = {
        "1w": 0.85, "2w": 0.80, "1m": 0.65,
        "3m": 0.40, "6m": 0.20, "1y": 0.10, "3y": 0.05,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        news = ctx.news or []
        finnhub_sentiment = (ctx.metadata or {}).get("finnhub_sentiment")
        # The pipeline can stash Finnhub's per-ticker sentiment under
        # ctx.metadata["finnhub_sentiment"] — it's a one-shot per ticker call.

        if not news and finnhub_sentiment is None:
            r = no_data(self.name, "no news headlines and no Finnhub sentiment")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        # ---- Headline polarity via lexicon ----
        scored = []
        for h in news:
            t = (h.get("title") or h.get("headline") or "")
            if not t:
                continue
            polarity = _polarity(t)
            scored.append({
                "title": t[:140],
                "polarity": polarity,
                "ts": h.get("datetime") or h.get("publishedAt"),
                "source": h.get("source") or h.get("source", {}).get("name") if isinstance(h.get("source"), dict) else h.get("source"),
            })
        mean_polarity = (sum(x["polarity"] for x in scored) / len(scored)) if scored else 0.0
        n_headlines = len(scored)

        # ---- Combine with Finnhub if present ----
        components = []
        if finnhub_sentiment is not None:
            try:
                fh = float(finnhub_sentiment)
                components.append(fh)
            except (TypeError, ValueError):
                pass
        if scored:
            components.append(mean_polarity)
        combined = sum(components) / len(components) if components else 0.0

        score = clamp(combined * 0.5, -0.30, 0.30)
        notes: list[str] = []
        if n_headlines >= 5:
            notes.append(f"Headline polarity over last {n_headlines} articles: {mean_polarity:+.2f}.")
        if finnhub_sentiment is not None:
            notes.append(f"Finnhub aggregate sentiment: {finnhub_sentiment:+.2f}.")

        confidence = 0.4
        if n_headlines >= 10:
            confidence += 0.20
        if finnhub_sentiment is not None:
            confidence += 0.20
        confidence = clamp(confidence, 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "headline_count": n_headlines,
                "mean_polarity": round(mean_polarity, 3),
                "finnhub_sentiment": finnhub_sentiment,
                "headlines_sample": scored[:10],
            },
            notes=notes,
            data_quality="full" if (n_headlines >= 5 or finnhub_sentiment is not None) else "partial",
        )


def _polarity(text: str) -> float:
    """Crude finance-keyword polarity in [-1, +1]."""
    words = {w.strip(".,!?:;()'\"").lower() for w in text.split()}
    pos = len(words & _POS)
    neg = len(words & _NEG)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)
