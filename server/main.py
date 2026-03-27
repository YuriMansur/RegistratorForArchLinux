import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, Base
from routers import records, tags, usb
from protocol_backend.server_manager import ServerManager
import usb_monitor
import usb_exporter

Base.metadata.create_all(bind=engine)

_server_manager: ServerManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _server_manager
    _server_manager = ServerManager()
    _server_manager.start()
    usb_monitor.on_inserted = usb_exporter.export_on_insert
    usb_monitor.on_removed = lambda _: usb_exporter._set_status("idle")
    usb_monitor.start()
    yield
    usb_monitor.stop()
    if _server_manager:
        _server_manager.stop()


app = FastAPI(title="Registrator API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(records.router)
app.include_router(tags.router)
app.include_router(usb.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
