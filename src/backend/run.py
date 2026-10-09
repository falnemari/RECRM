from pathlib import Path
import uvicorn
from app.config import settings

APP_DIR = Path(__file__).resolve().parent / "app"

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        reload_dirs=[str(APP_DIR)] if settings.DEBUG else None,
        reload_excludes=[".venv", "src/ui", "*.pyc"] if settings.DEBUG else None,
    )

