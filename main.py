import os
import io
from typing import Tuple

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "OCR Background Replacer API is running"}


@app.get("/health")
def health():
    return {"status": "ok"}


# Helper to build themed background

def build_background(size: Tuple[int, int], theme: str):
    width, height = size
    theme = (theme or "light").lower()
    if theme == "dark":
        color1 = (18, 18, 22)
        color2 = (32, 32, 38)
        text_color = (245, 245, 245)
    elif theme == "blue":
        color1 = (219, 234, 254)
        color2 = (191, 219, 254)
        text_color = (17, 24, 39)
    elif theme == "brand":
        color1 = (250, 245, 255)
        color2 = (236, 233, 255)
        text_color = (24, 24, 27)
    else:
        color1 = (250, 250, 250)
        color2 = (240, 240, 245)
        text_color = (17, 24, 39)

    bg = Image.new("RGB", (width, height), color1)
    top = Image.new("RGB", (width, height // 2), color1)
    bottom = Image.new("RGB", (width, height - height // 2), color2)
    bg.paste(top, (0, 0))
    bg.paste(bottom, (0, height // 2))
    return bg, text_color


# Fallback font loader

def load_font(pixels: int) -> ImageFont.ImageFont:
    size = max(10, int(pixels))
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except Exception:
        return ImageFont.load_default()


@app.post("/process")
async def process_image(
    file: UploadFile = File(...),
    theme: str = Form("light"),
):
    try:
        contents = await file.read()
        try:
            original = Image.open(io.BytesIO(contents)).convert("RGB")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image data")

        w, h = original.size

        # Build background
        bg_img, text_color = build_background((w, h), theme)

        # Text extraction via threshold mask (no external OCR deps):
        # Works best for dark text on light slips; keeps layout by using pixel mask
        gray = original.convert("L")
        # Auto threshold using Otsu-like heuristic via histogram midpoint
        hist = gray.histogram()
        total = sum(hist)
        cumsum = 0
        thresh = 200
        for i, v in enumerate(hist):
            cumsum += v
            if cumsum >= total * 0.7:  # assume ~70% background bright area
                thresh = max(120, i)
                break
        mask = gray.point(lambda p: 255 if p < thresh else 0).convert("L")

        # Create solid text layer using theme text color
        text_layer = Image.new("RGB", (w, h), text_color)

        # Composite: place text color wherever mask indicates text
        composed = Image.composite(text_layer, bg_img, mask)

        # Optional faint watermark of original for context (very subtle)
        watermark = original.copy().convert("RGBA")
        alpha = Image.new("L", (w, h), 25)  # very low opacity
        watermark.putalpha(alpha)
        composed = composed.convert("RGBA")
        composed.alpha_composite(watermark)
        composed = composed.convert("RGB")

        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        from database import db

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
