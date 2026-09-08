from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Search(StrictInput):
    query: str = Field(default='', max_length=160)
    genres: list[str] = Field(default_factory=list, max_length=10, description='Music genres, such as punk rock or jazz. Matches any requested genre against source performer tags; never put genres in query.')
    city: str = Field(default='Atlanta', min_length=1, max_length=100)
    date_from: date
    date_to: date
    type: Literal['any', 'concert', 'sports', 'theater'] = 'any'
    limit: int = Field(default=9, ge=1, le=10)

    @model_validator(mode='after')
    def clean_genres(self):
        self.genres=list(dict.fromkeys(g.strip() for g in self.genres if g.strip()))
        if any(len(g)>80 for g in self.genres): raise ValueError('Genre names must be at most 80 characters.')
        return self

    @model_validator(mode='after')
    def dates(self):
        if self.date_to < self.date_from or (self.date_to-self.date_from).days > 366:
            raise ValueError('Choose an ordered date range of at most one year.')
        return self

class Details(StrictInput):
    event_id: int = Field(gt=0)

class Compare(StrictInput):
    event_ids: list[int] = Field(min_length=2, max_length=3)
    @model_validator(mode='after')
    def unique_ids(self):
        if len(set(self.event_ids)) != len(self.event_ids) or any(x <= 0 for x in self.event_ids):
            raise ValueError('Choose two or three distinct positive event IDs.')
        return self

class Plan(Search):
    budget_usd: float | None = Field(default=None, ge=1, le=100000)
    party_size: int = Field(default=2, ge=1, le=10)
    favorite_artists: list[str] = Field(default_factory=list, max_length=20)
    include_related: bool = Field(default=False, description='Also search events by artists Last.fm lists as similar to favorite_artists, and order alternatives by overlap with the favorites\u2019 Last.fm top tags. Requires favorite_artists; suggestions are attributed to Last.fm.')
    exclude_event_ids: list[int] = Field(default_factory=list, max_length=20, description='Event IDs to leave out, e.g. picks the user rejected. Use when replacing a disputed suggestion.')
    venue_query: str = Field(default='', max_length=100)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    shortlist_size: int = Field(default=3, ge=1, le=10)

    @model_validator(mode='after')
    def preferences(self):
        if any(not a.strip() or len(a)>100 for a in self.favorite_artists):
            raise ValueError('Use artist names of 1–100 characters.')
        if any(d<0 or d>6 for d in self.weekdays):
            raise ValueError('Weekdays must be Monday=0 through Sunday=6.')
        if any(x<=0 for x in self.exclude_event_ids):
            raise ValueError('Excluded event IDs must be positive.')
        return self

class Verify(StrictInput):
    text: str = Field(min_length=1, max_length=8000)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)

class Nearby(StrictInput):
    event_id: int = Field(gt=0)
    category: Literal['restaurant','bar','parking','all'] = 'all'
    radius_m: int = Field(default=1200, ge=100, le=5000)

INPUTS = {'search_events': Search, 'event_details': Details, 'compare_events': Compare,
          'plan_night': Plan, 'verify_plan': Verify, 'nearby_places': Nearby}
