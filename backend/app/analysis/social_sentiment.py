"""Social sentiment module — Reddit mention velocity & sentiment.

Reads ctx.social (Reddit posts mentioning the ticker over the last week).
Reports zero signal when Reddit credentials aren't configured (the user
has skipped Reddit for v1) — `data_quality="missing"`.

Components:
  - Mention count vs trailing baseline (velocity)
  - Mean post score (Reddit upvote score)
  - Lexicon polarity over post titles + selftext
"""

from __future__ import annotations

from app.analysis.base import (
    AnalysisContext,
    BaseAnalysisModule,
    ModuleResult,
    clamp,
    direction_from_score,
    no_data,
)
from app.analysis.news_sentiment import _polarity


class SocialSentimentModule(BaseAnalysisModule):
    name = "social_sentiment"
    description = "Reddit mention velocity & sentiment (skipped when Reddit creds absent)."

    HORIZON_WEIGHTS = {
        "1w": 0.70, "2w": 0.55, "1m": 0.35,
        "3m": 0.20, "6m": 0.10, "1y": 0.05, "3y": 0.0,
    }

    def analyze(self, ctx: AnalysisContext) -> ModuleResult:
        posts = ctx.social or []
        if not posts:
            r = no_data(self.name, "no social data (Reddit not configured or no mentions)")
            r.horizon_weights = self.HORIZON_WEIGHTS
            return r

        n = len(posts)
        avg_score = sum((p.get("score") or 0) for p in posts) / n if n else 0.0
        avg_comments = sum((p.get("num_comments") or 0) for p in posts) / n if n else 0.0

        polarities = []
        for p in posts:
            text = " ".join(filter(None, [p.get("title", ""), p.get("selftext", "")[:500]]))
            polarities.append(_polarity(text))
        mean_polarity = (sum(polarities) / len(polarities)) if polarities else 0.0

        # Crude velocity heuristic — high mention count is bullish IF posts are
        # also positive on average. High mentions with negative sentiment is
        # bearish (e.g. controversy / pile-on).
        s = 0.0
        notes: list[str] = []

        if n >= 25 and mean_polarity > 0.1:
            s += 0.15
            notes.append(f"{n} Reddit posts last week, polarity {mean_polarity:+.2f} — retail tailwind.")
        elif n >= 25 and mean_polarity < -0.1:
            s -= 0.15
            notes.append(f"{n} Reddit posts, polarity {mean_polarity:+.2f} — retail headwind.")
        elif n >= 10:
            s += clamp(mean_polarity * 0.10, -0.10, 0.10)

        score = clamp(s, -0.20, 0.20)  # cap social sentiment influence
        confidence = clamp(0.30 + (0.05 if n >= 25 else 0), 0.0, 1.0)

        return ModuleResult(
            module=self.name,
            score=score,
            direction=direction_from_score(score, threshold=0.05),
            confidence=confidence,
            horizon_weights=self.HORIZON_WEIGHTS,
            raw={
                "post_count_7d": n,
                "mean_post_score": round(avg_score, 1),
                "mean_comments": round(avg_comments, 1),
                "mean_polarity": round(mean_polarity, 3),
            },
            notes=notes,
            data_quality="full" if n >= 25 else ("partial" if n >= 5 else "missing"),
        )
