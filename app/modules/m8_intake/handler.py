import json

from fastapi import APIRouter, Request

from app.config import MAX_SOURCE_BYTES
from app.errors import BusinessError
from app.modules.m8_intake import service
from app.quality import token

router = APIRouter(prefix="/api/batches", tags=["批次接收"])


def batch_token(batch):
    try:
        return token(batch)
    except ValueError as error:
        raise BusinessError("BAD_BATCH", "批次编号无效") from error


@router.post("/{batch}/intakes")
async def submit(request: Request, batch: str):
    batch = batch_token(batch)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_SOURCE_BYTES:
            raise BusinessError("SOURCE_TOO_LARGE", "数据超过 512 KiB", 413)
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise BusinessError("BAD_JSON", "请输入有效的 UTF-8 JSON") from error
    return service.receive(request.app.state.ledger, batch, payload)


@router.get("/{batch}/ledger")
def ledger(request: Request, batch: str):
    return service.view(request.app.state.ledger, batch_token(batch))


@router.get("/{batch}/publication")
def published(request: Request, batch: str):
    snapshot = request.app.state.ledger.publication(batch_token(batch))
    if snapshot is None:
        raise BusinessError("PUBLICATION_NOT_FOUND", "批次尚未发布", 404)
    return snapshot


@router.post("/{batch}/publish")
def switch(request: Request, batch: str):
    return service.publish(request.app.state.ledger, batch_token(batch))
