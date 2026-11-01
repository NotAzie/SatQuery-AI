"""Validated STAC Item Search request contract."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class StacConnectorSettings(BaseModel):
    """Configuration for one STAC API catalog instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_url: AnyHttpUrl
    connector_id: str = Field(default="stac-catalog", min_length=1)
    collection_ids: tuple[str, ...] = ()
    authentication_required: bool = False

    @model_validator(mode="after")
    def validate_catalog_endpoint(self) -> "StacConnectorSettings":
        url = self.catalog_url
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(
                "catalog_url must not contain credentials, a query, or a fragment"
            )
        if len(self.collection_ids) != len(set(self.collection_ids)):
            raise ValueError("collection_ids must be unique")
        if any(not collection_id.strip() for collection_id in self.collection_ids):
            raise ValueError("collection_ids must not contain empty values")
        return self


class StacSearchRequest(BaseModel):
    """Provider-neutral subset of the STAC API Item Search request body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    collections: Optional[tuple[str, ...]] = None
    ids: Optional[tuple[str, ...]] = None
    bbox: Optional[tuple[float, ...]] = Field(default=None, min_length=4, max_length=6)
    intersects: Optional[dict[str, Any]] = None
    datetime: Optional[str] = None
    limit: Optional[int] = Field(default=None, ge=1)
    token: Optional[str] = None
    query: Optional[dict[str, Any]] = None
    filter: Optional[Any] = None
    filter_lang: Optional[str] = None
    sortby: Optional[tuple[dict[str, Any], ...]] = None

    @model_validator(mode="after")
    def validate_spatial_query(self) -> "StacSearchRequest":
        if self.bbox is not None:
            if len(self.bbox) not in {4, 6}:
                raise ValueError("bbox must contain four or six coordinates")
            if len(self.bbox) == 4:
                west, south, east, north = self.bbox
            else:
                west, south, min_elevation, east, north, max_elevation = self.bbox
                if min_elevation > max_elevation:
                    raise ValueError(
                        "bbox minimum elevation must not exceed maximum elevation"
                    )
            if not -180 <= west <= 180 or not -180 <= east <= 180:
                raise ValueError("bbox longitude coordinates must be between -180 and 180")
            if not -90 <= south <= 90 or not -90 <= north <= 90:
                raise ValueError("bbox latitude coordinates must be between -90 and 90")
            if south > north:
                raise ValueError("bbox south latitude must not exceed north latitude")
        if self.bbox is not None and self.intersects is not None:
            raise ValueError("bbox and intersects are mutually exclusive")
        if self.intersects is not None:
            geometry_type = self.intersects.get("type")
            if not isinstance(geometry_type, str) or geometry_type not in {
                "Point",
                "MultiPoint",
                "LineString",
                "MultiLineString",
                "Polygon",
                "MultiPolygon",
                "GeometryCollection",
            }:
                raise ValueError("intersects must contain a GeoJSON geometry")
            coordinate_field = (
                "geometries" if geometry_type == "GeometryCollection" else "coordinates"
            )
            if not isinstance(self.intersects.get(coordinate_field), list):
                raise ValueError(
                    f"intersects {geometry_type} must contain {coordinate_field}"
                )
        if self.collections is not None and not self.collections:
            raise ValueError("collections must not be empty when provided")
        if self.collections is not None and any(
            not collection_id.strip() for collection_id in self.collections
        ):
            raise ValueError("collection IDs must not be empty")
        if self.ids is not None and not self.ids:
            raise ValueError("ids must not be empty when provided")
        if self.ids is not None and any(not item_id.strip() for item_id in self.ids):
            raise ValueError("item IDs must not be empty")
        if self.datetime is not None and not self.datetime.strip():
            raise ValueError("datetime must not be empty")
        if self.sortby is not None:
            for item in self.sortby:
                field = item.get("field")
                direction = item.get("direction", "asc")
                if not isinstance(field, str) or not field.strip():
                    raise ValueError("sortby entries require a non-empty field")
                if direction not in {"asc", "desc"}:
                    raise ValueError("sortby direction must be 'asc' or 'desc'")
        return self
