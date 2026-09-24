from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .services.pipeline import analyze_image

BASE_DIR = Path(__file__).resolve().parent
HOME_PAGE = BASE_DIR / "static" / "index.html"

app = FastAPI(
    title="API Nhận Diện Chứng Chỉ Chất Lượng",
    version="0.3.0",
    description=(
        "Hệ thống kết hợp YOLO, OCR ngữ cảnh, OCR toàn trang, so khớp đặc trưng hình ảnh "
        "và bộ quy tắc Run 7D để nhận diện loại chứng chỉ/logo và trích xuất ngày liên quan."
    ),
)


@app.get("/", include_in_schema=False)
def trang_chu():
    return FileResponse(HOME_PAGE, media_type="text/html; charset=utf-8")


@app.get("/health", summary="Kiểm tra trạng thái hệ thống")
def health():
    return {"status": "ok", "version": "0.3.0"}


@app.post("/v1/analyze", summary="Phân tích ảnh chứng chỉ / logo")
async def analyze(
    file: UploadFile = File(..., description="Ảnh cần phân tích"),
    detector_confidence: float = Query(0.40, ge=0.01, le=0.99, description="Ngưỡng confidence của YOLO"),
    imgsz: int = Query(960, ge=320, le=1920, description="Kích thước ảnh đầu vào cho YOLO"),
    include_ocr: bool = Query(False, description="Có trả kèm toàn bộ văn bản OCR hay không"),
):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Chỉ hỗ trợ file ảnh.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File rỗng.")
    try:
        result = analyze_image(content, detector_confidence, imgsz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline lỗi: {e}") from e

    if not include_ocr:
        result.pop("document_ocr_text", None)
    result["filename"] = file.filename
    return JSONResponse(result)
