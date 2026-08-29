from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileRequest(StrictModel):
    profile_url: str = Field(min_length=1, max_length=500)


class Experience(StrictModel):
    title: str
    company: str | None = None
    employment_type: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: str | None = None
    description: str | None = None
    skills: list[str] = Field(default_factory=list)


class Education(StrictModel):
    school: str
    degree: str | None = None
    field_of_study: str | None = None
    start_year: str | None = None
    end_year: str | None = None
    grade: str | None = None
    description: str | None = None


class Certification(StrictModel):
    name: str
    issuer: str | None = None
    issue_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    credential_url: str | None = None


class Language(StrictModel):
    name: str
    proficiency: str | None = None


class Profile(StrictModel):
    profile_url: str
    public_identifier: str
    name: str
    headline: str | None = None
    location: str | None = None
    about: str | None = None
    profile_image_url: str | None = None
    background_image_url: str | None = None
    follower_count: int | None = None
    connection_count: int | None = None
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)


class ResponseMeta(StrictModel):
    request_id: str
    scraped_at: datetime
    source: str = "linkedin_voyager_api"
    cached: bool = False
    partial: bool = False
    warnings: list[str] = Field(default_factory=list)


class ProfileResponse(StrictModel):
    data: Profile
    meta: ResponseMeta
