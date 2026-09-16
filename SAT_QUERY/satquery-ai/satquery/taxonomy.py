"""Remote-sensing label vocabulary.

Zero-shot CLIP classification is only as good as the label set it scores
against, so this module is where a large share of the system's real accuracy
lives. Two decisions shape it:

* Labels are written as natural phrases, not dataset class codes.
  "dense residential neighbourhood" scores far better than "denseresidential"
  because CLIP's text encoder saw prose, not underscore-joined class names.
* Every scene label carries a land-use group, so the system can answer at
  whichever granularity the question implies - "it is farmland" or "it is a
  centre-pivot irrigated field".

Grounding needs the opposite construct: a contrast set of plausible
alternatives, so that a window's score for "ship" is a *relative* judgement
against "open water" and "dock" rather than an absolute similarity that would
fire everywhere.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

# ---------------------------------------------------------------------------
# Scene / land-use taxonomy
# ---------------------------------------------------------------------------

#: label -> land-use group
SCENE_TAXONOMY: Dict[str, str] = {
    # Built environment
    "a dense residential neighbourhood with closely packed houses": "urban",
    "a sparse suburban area with detached houses and gardens": "urban",
    "a medium density residential area with regular street blocks": "urban",
    "a commercial district with large buildings and parking": "urban",
    "an industrial area with warehouses and factory roofs": "industrial",
    "a large parking lot filled with vehicles": "transport",
    "a shopping centre with a large flat roof and car park": "urban",
    "an informal settlement with irregular small rooftops": "urban",
    "a construction site with cleared ground and machinery": "industrial",
    "a storage tank farm with circular tanks": "industrial",
    "a power substation or solar power plant": "industrial",
    "a stadium or large sports arena": "urban",
    "a school or university campus": "urban",
    "a church, temple, or large civic building": "urban",
    "a cemetery with regular rows of plots": "urban",
    # Transport
    "an airport runway and taxiways with aircraft": "transport",
    "a seaport with docks, cranes, and ships": "transport",
    "a railway yard with parallel tracks": "transport",
    "a highway interchange with curving ramps": "transport",
    "a bridge crossing a river or bay": "transport",
    "a harbour or marina with moored boats": "transport",
    # Agriculture
    "rectangular agricultural fields with crop rows": "agriculture",
    "circular centre pivot irrigated fields": "agriculture",
    "terraced farmland on sloping ground": "agriculture",
    "an orchard or plantation with regularly spaced trees": "agriculture",
    "paddy fields flooded with water": "agriculture",
    "a greenhouse complex with bright reflective roofs": "agriculture",
    "fallow or recently harvested farmland": "agriculture",
    # Natural vegetation
    "dense forest canopy": "vegetation",
    "sparse shrubland and scrub vegetation": "vegetation",
    "grassland or open meadow": "vegetation",
    "a mangrove or wetland vegetation area": "wetland",
    "a park or golf course with managed lawns": "vegetation",
    # Water
    "open sea or ocean water": "water",
    "a river channel with visible banks": "water",
    "a lake or reservoir": "water",
    "a coastline where land meets water": "water",
    "a river delta with braided channels": "water",
    "flooded land with standing water over fields": "water",
    # Bare and natural terrain
    "bare soil or exposed earth": "barren",
    "desert sand dunes": "barren",
    "rocky mountainous terrain": "barren",
    "a quarry or open pit mine": "industrial",
    "a beach with sand along the shoreline": "barren",
    "snow or ice covered ground": "barren",
    "a cloud covered scene with little visible ground": "obscured",
}

SCENE_LABELS: Tuple[str, ...] = tuple(SCENE_TAXONOMY.keys())

GROUP_DESCRIPTIONS: Dict[str, str] = {
    "urban": "built-up residential or commercial land",
    "industrial": "industrial or extractive land use",
    "transport": "transport infrastructure",
    "agriculture": "cultivated agricultural land",
    "vegetation": "natural or managed vegetation",
    "wetland": "wetland or mangrove",
    "water": "open water",
    "barren": "bare or naturally unvegetated ground",
    "obscured": "obscured by cloud",
}


# ---------------------------------------------------------------------------
# Grounding targets
# ---------------------------------------------------------------------------

#: Canonical target phrasings for common grounding requests. A user asking to
#: "locate buildings" gets a better response map from "a building rooftop seen
#: from above" than from the bare word "buildings".
TARGET_PHRASES: Dict[str, str] = {
    "building": "building rooftops seen from directly above",
    "house": "residential house rooftops seen from above",
    "rooftop": "building rooftops seen from directly above",
    "vehicle": "cars and vehicles parked or on a road, seen from above",
    "car": "cars parked in rows, seen from above",
    "truck": "large trucks and lorries seen from above",
    "bus": "buses seen from above",
    "ship": "ships and vessels on water, seen from above",
    "boat": "small boats on water, seen from above",
    "aircraft": "aircraft parked on tarmac, seen from above",
    "airplane": "aircraft parked on tarmac, seen from above",
    "road": "paved roads and streets seen from above",
    "highway": "a wide highway with multiple lanes, seen from above",
    "runway": "an airport runway strip seen from above",
    "bridge": "a bridge spanning water, seen from above",
    "railway": "railway tracks running in parallel, seen from above",
    "tree": "tree canopy and woodland, seen from above",
    "forest": "dense forest canopy seen from above",
    "farmland": "cultivated agricultural fields seen from above",
    "crop": "cultivated crop fields seen from above",
    "field": "agricultural field parcels seen from above",
    "water": "a body of water seen from above",
    "river": "a river channel seen from above",
    "lake": "a lake or reservoir seen from above",
    "pool": "a swimming pool seen from above",
    "solar panel": "solar panel arrays seen from above",
    "wind turbine": "wind turbines seen from above",
    "storage tank": "circular storage tanks seen from above",
    "parking lot": "a parking lot with marked bays, seen from above",
    "stadium": "a stadium seen from above",
    "port": "port docks and quays seen from above",
    "harbour": "a harbour with moored vessels, seen from above",
    "damage": "collapsed or damaged structures seen from above",
    "flood": "flood water covering land, seen from above",
    "smoke": "smoke plumes seen from above",
    "fire": "active fire and burn scars seen from above",
    "cloud": "cloud cover obscuring the ground",
    "shadow": "dark shadows cast by tall structures",
}

#: Generic alternatives every grounding run scores against. Without a contrast
#: set, CLIP similarity is an unanchored number; with one, each window gets a
#: softmax over "is this the target, or one of these other things", which is a
#: far more stable signal.
CONTRAST_PHRASES: Tuple[str, ...] = (
    "empty ground with nothing notable",
    "open water with no objects",
    "bare soil and dirt",
    "grass and vegetation",
    "a plain paved surface",
    "dense tree canopy",
    "building rooftops",
    "a road surface",
    "cloud cover",
    "a uniform textureless area",
)


def phrase_for_target(target: str) -> str:
    """Expand a bare target noun into a descriptive overhead phrasing."""
    key = target.strip().lower()
    if not key:
        return "the object of interest seen from above"
    if key in TARGET_PHRASES:
        return TARGET_PHRASES[key]

    singular = key[:-1] if key.endswith("s") and len(key) > 3 else key
    if singular in TARGET_PHRASES:
        return TARGET_PHRASES[singular]

    for name, phrase in TARGET_PHRASES.items():
        if name in key or key in name:
            return phrase
    return f"{key} seen from directly above in a satellite image"


def contrast_set(target_phrase: str) -> List[str]:
    """Contrast alternatives, excluding anything too close to the target."""
    target_words = set(target_phrase.lower().split())
    alternatives: List[str] = []
    for phrase in CONTRAST_PHRASES:
        overlap = target_words & set(phrase.lower().split())
        meaningful = {word for word in overlap if len(word) > 4}
        if meaningful:
            continue
        alternatives.append(phrase)
    if not alternatives:
        alternatives = list(CONTRAST_PHRASES[:4])
    return alternatives


#: Caption conditioning prefixes, ensembled for richer descriptions.
CAPTION_PROMPTS_OPTICAL: Tuple[str, ...] = (
    "",
    "an aerial view of",
    "a satellite image showing",
    "this overhead image contains",
    "the land cover in this aerial photo is",
)

CAPTION_PROMPTS_SAR: Tuple[str, ...] = (
    "",
    "a grayscale radar image showing",
    "this overhead radar image contains",
    "the terrain in this radar image is",
)


def caption_prompts(modality: str) -> Sequence[str]:
    return CAPTION_PROMPTS_SAR if str(modality).upper() == "SAR" else CAPTION_PROMPTS_OPTICAL
