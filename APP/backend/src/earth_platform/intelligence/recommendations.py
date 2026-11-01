from earth_platform.intelligence.models import RankedMemoryRecord, Recommendation


class RecommendationEngine:
    """Makes references to existing workspace records; it never recommends scientific outcomes."""

    def recommend(self, records: list[RankedMemoryRecord]) -> list[Recommendation]:
        recommendations: list[Recommendation] = []
        seen: set[tuple[str, str]] = set()
        kind_map = {
            "investigation": "related_investigation",
            "asset": "recent_asset",
            "bookmark": "related_bookmark",
            "conversation": "related_conversation",
        }
        descriptions = {
            "related_investigation": (
                "A previously recorded Engine investigation is related to this workspace context."
            ),
            "recent_asset": "A previously uploaded image asset is related to this request.",
            "related_bookmark": (
                "A saved Earth bookmark is near or textually related to this workspace context."
            ),
            "related_conversation": "A previous Platform conversation is related to this request.",
            "timeline_overlap": (
                "The current timeline overlaps a previously recorded workspace interval."
            ),
        }
        for result in records:
            if result.record.time_range is not None:
                recommendation = Recommendation(
                    kind="timeline_overlap",
                    title=result.record.title,
                    detail=descriptions["timeline_overlap"],
                    session_id=result.record.session_id,
                    reference_id=result.record.id,
                )
                timeline_key = recommendation.kind, result.record.id
                if timeline_key not in seen:
                    seen.add(timeline_key)
                    recommendations.append(recommendation)
            recommendation_kind = kind_map.get(result.record.kind)
            if recommendation_kind is None:
                continue
            recommendation_key = recommendation_kind, result.record.id
            if recommendation_key in seen:
                continue
            seen.add(recommendation_key)
            recommendations.append(
                Recommendation(
                    kind=recommendation_kind,
                    title=result.record.title,
                    detail=descriptions[recommendation_kind],
                    session_id=result.record.session_id,
                    reference_id=result.record.id,
                )
            )
        return recommendations
