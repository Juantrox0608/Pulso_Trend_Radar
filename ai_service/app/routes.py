from fastapi import APIRouter, Depends, Request

from .analysis import analyze
from .schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse

router = APIRouter()


def get_provider(request: Request):
    return request.app.state.provider


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalyzeResponse, responses={
    status: {"model": ErrorResponse} for status in (413, 422, 502, 503, 504)
})
async def analyze_videos(body: AnalyzeRequest, provider=Depends(get_provider)):
    return await analyze(body, provider)
