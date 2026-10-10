"""The storage card of the settings: what the data folder holds, where it lies, and the check of the files. Operator
only, from the browser (``deps.require_operator``)."""

from __future__ import annotations

import logging
from typing import Any

import anyio
from fastapi import APIRouter

from ..db import SessionLocal
from ..deps import OperatorAccount
from ..errors import error
from ..services import filecheck, space, storage

logger = logging.getLogger("nexpaper.storage")

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


@router.get("", summary="What the data folder holds, where it lies, and how the check of the files stands")
async def overview(_operator: OperatorAccount) -> dict[str, Any]:
    """Sizes of the database (and of it the search index), the documents, the cache, the exports and the backups, the
    free room, and whether the database lies on a network share. Counting a large folder may take a moment, so a count
    is kept for five minutes."""
    numbers = await anyio.to_thread.run_sync(space.overview)

    def files() -> dict[str, Any]:
        with SessionLocal() as db:
            return filecheck.status(db)

    return {**numbers, "files": await anyio.to_thread.run_sync(files)}


@router.post("/files/check", status_code=202, summary="Check the checksums of all files now, in the background")
def check_files(operator: OperatorAccount) -> dict[str, Any]:
    """Starts the check of the files; one that is running goes on. The answer is the state at once."""
    with SessionLocal() as db:
        started = filecheck.start(db)
        status = filecheck.status(db)
    logger.info("Check of the files asked for by=%s started=%s", operator.name, started)
    return {**status, "started": started}


@router.post("/files/documents/{document_id}/check", summary="Look at the files of one document again, now")
async def check_document(document_id: int, operator: OperatorAccount) -> dict[str, str]:
    """For the operator who put a file back: the sign of that one document goes (or stays) at once, without the check of
    all the files. ``files_state`` is empty when the files are all there and the ones noted."""
    try:
        state = await anyio.to_thread.run_sync(filecheck.recheck, document_id)
    except storage.DocumentBusy:
        raise error("try_again", "The files of this document are being worked on. Try again soon.", 409) from None
    if state is None:
        raise error("not_found", "Not found.", 404)
    logger.info("Files of one document looked at again by=%s document_id=%s state=%s", operator.name, document_id,
                state or "ok")
    return {"files_state": state}
