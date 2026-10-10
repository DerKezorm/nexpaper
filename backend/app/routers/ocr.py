"""The operator's settings of the text recognition (Settings, Storage, card "Text recognition"), with the state of the
queue and what this server can do."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from ..deps import DbSession, OperatorAccount
from ..services import ocr, processing, settings_service

logger = logging.getLogger("nexpaper.settings")

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

Language = Literal["deu", "eng", "fra", "nld", "pol", "tur"]


class OcrOut(BaseModel):
    #: The languages the recognition reads, of ``offered``.
    languages: list[str]
    #: Every language this server carries (no other can be added at run time).
    offered: list[str]
    #: Straighten skewed pages and turn pages upright.
    straighten: bool
    #: Blank pages count as separators (acted on by the page tools).
    blank_pages: bool
    #: Pages worked on at once.
    jobs: int
    #: The longest the recognition of one document may take, in seconds.
    max_seconds: int
    #: From this many pages a document waits long for its text (the inbox says so).
    long_document_pages: int
    #: This server has ocrmypdf and Tesseract; without them only the text a PDF carries itself is found.
    available: bool
    #: Documents being read now, and waiting.
    running: int
    waiting: int
    #: Seconds per page over the last documents read; empty until something was read.
    seconds_per_page: float | None


class OcrIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    languages: list[Language] | None = Field(default=None, min_length=1, max_length=len(ocr.LANGUAGES))
    straighten: StrictBool | None = None
    blank_pages: StrictBool | None = None
    jobs: StrictInt | None = Field(default=None, ge=ocr.JOBS_RANGE[0], le=ocr.JOBS_RANGE[1])
    max_seconds: StrictInt | None = Field(default=None, ge=ocr.MAX_SECONDS_RANGE[0], le=ocr.MAX_SECONDS_RANGE[1])


def _view(db: DbSession) -> OcrOut:
    current = ocr.current(db)
    running, waiting = processing.waiting(db)
    return OcrOut(languages=current.languages, offered=list(ocr.LANGUAGES), straighten=current.straighten,
                  blank_pages=current.blank_pages, jobs=current.jobs, max_seconds=current.max_seconds,
                  long_document_pages=ocr.LONG_DOCUMENT_PAGES, available=ocr.available(), running=running,
                  waiting=waiting, seconds_per_page=ocr.seconds_per_page(db))


@router.get("/ocr", response_model=OcrOut, summary="The text recognition: languages, straightening, the queue")
def read(_operator: OperatorAccount, db: DbSession) -> OcrOut:
    return _view(db)


@router.put("/ocr", response_model=OcrOut, summary="Change the settings of the text recognition (from the next file)")
def change(payload: OcrIn, operator: OperatorAccount, db: DbSession) -> OcrOut:
    sent = payload.model_dump(exclude_unset=True, exclude_none=True)
    changes: dict[str, object] = {}
    if "languages" in sent:
        # In the order of the offer, each once.
        changes["ocr_languages"] = [code for code in ocr.LANGUAGES if code in sent["languages"]]
    for key in ("straighten", "blank_pages", "jobs", "max_seconds"):
        if key in sent:
            changes[f"ocr_{key}"] = sent[key]
    if changes:
        settings_service.save(db, changes)
        logger.info("Settings changed keys=%s by=%s", ",".join(sorted(changes)), operator.name)
        if changes.get("ocr_blank_pages") is True:
            from ..services import separators

            # The documents waiting in the inbox are looked at now (page tools, B5).
            separators.queue_missing(db)
    return _view(db)
