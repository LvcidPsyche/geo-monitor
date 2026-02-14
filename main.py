import hashlib
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Request, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="GEO Monitor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DEMO_API_KEY = "demo-key-2024"

# In-memory store for monitors
monitors_db: dict = {}

SUPPORTED_LOCATIONS = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
    "London", "Manchester", "Birmingham", "Leeds", "Glasgow",
    "Toronto", "Vancouver", "Montreal", "Calgary", "Ottawa",
    "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
    "Tokyo", "Osaka", "Yokohama", "Nagoya", "Sapporo",
    "Berlin", "Munich", "Hamburg", "Frankfurt", "Cologne",
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice",
    "Mumbai", "Delhi", "Bangalore", "Chennai", "Kolkata",
    "Sao Paulo", "Rio de Janeiro", "Brasilia", "Salvador", "Fortaleza",
]


def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != DEMO_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key


def seed_random(domain: str, keyword: str, location: str, day_offset: int = 0):
    seed_str = f"{domain}:{keyword}:{location}:{day_offset}"
    seed_val = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return random.Random(seed_val)


def generate_ranking(domain: str, keyword: str, location: str, day_offset: int = 0):
    rng = seed_random(domain, keyword, location, day_offset)
    position = rng.randint(1, 100)
    base_traffic = max(10, 5000 - (position * 45) + rng.randint(-200, 200))
    trends = ["up", "down", "stable"]
    trend_weights = [0.4, 0.3, 0.3]
    trend = rng.choices(trends, weights=trend_weights, k=1)[0]
    change = rng.randint(1, 8) if trend != "stable" else 0
    return {
        "location": location,
        "position": position,
        "estimated_traffic": base_traffic,
        "trend": trend,
        "change": change,
    }


# ── Request / Response models ──


class CheckRankingRequest(BaseModel):
    domain: str
    keyword: str
    locations: List[str]


class MonitorRequest(BaseModel):
    domain: str
    keywords: List[str]
    locations: List[str]


# ── Routes ──


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/check-ranking")
async def check_ranking(body: CheckRankingRequest, api_key: str = Depends(verify_api_key)):
    results = []
    for loc in body.locations:
        if loc not in SUPPORTED_LOCATIONS:
            results.append({"location": loc, "error": "Unsupported location"})
            continue
        results.append(generate_ranking(body.domain, body.keyword, loc))
    return {
        "domain": body.domain,
        "keyword": body.keyword,
        "checked_at": datetime.utcnow().isoformat(),
        "results": results,
    }


@app.post("/api/monitor")
async def create_monitor(body: MonitorRequest, api_key: str = Depends(verify_api_key)):
    monitor_id = str(uuid.uuid4())[:8]
    monitors_db[monitor_id] = {
        "id": monitor_id,
        "domain": body.domain,
        "keywords": body.keywords,
        "locations": body.locations,
        "created_at": datetime.utcnow().isoformat(),
        "status": "active",
    }
    return {
        "message": "Monitor created successfully",
        "monitor_id": monitor_id,
        "domain": body.domain,
        "keywords_count": len(body.keywords),
        "locations_count": len(body.locations),
        "next_check": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
    }


@app.get("/api/locations")
async def list_locations(api_key: str = Depends(verify_api_key)):
    return {"count": len(SUPPORTED_LOCATIONS), "locations": SUPPORTED_LOCATIONS}


@app.get("/api/report/{monitor_id}")
async def get_report(monitor_id: str, api_key: str = Depends(verify_api_key)):
    monitor = monitors_db.get(monitor_id)
    if not monitor:
        # Generate a demo report for any ID
        monitor = {
            "id": monitor_id,
            "domain": "example.com",
            "keywords": ["seo tools", "rank tracker"],
            "locations": ["New York", "London", "Tokyo"],
        }

    report_data = {}
    for kw in monitor["keywords"]:
        report_data[kw] = {}
        for loc in monitor["locations"]:
            daily = []
            for day in range(7):
                ranking = generate_ranking(monitor["domain"], kw, loc, day)
                ranking["date"] = (datetime.utcnow() - timedelta(days=6 - day)).strftime("%Y-%m-%d")
                daily.append(ranking)
            report_data[kw][loc] = daily

    return {
        "monitor_id": monitor_id,
        "domain": monitor["domain"],
        "generated_at": datetime.utcnow().isoformat(),
        "period": "last_7_days",
        "data": report_data,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8772)

# Phase 2: Add SQLite persistence for monitors
import aiosqlite
import json as json_lib

DB_PATH = "monitors.db"

async def init_monitors_db():
    """Initialize monitors database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS monitors (
                id TEXT PRIMARY KEY,
                api_key_id INTEGER,
                keywords TEXT,
                locations TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        await db.commit()

async def save_monitor(monitor_id: str, api_key_id: int, keywords: list, locations: list):
    """Save monitor to database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO monitors (id, api_key_id, keywords, locations)
            VALUES (?, ?, ?, ?)
        """, (monitor_id, api_key_id, json_lib.dumps(keywords), json_lib.dumps(locations)))
        await db.commit()

async def get_monitors_for_api_key(api_key_id: int) -> list:
    """Get all monitors for an API key."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM monitors WHERE api_key_id = ? AND is_active = 1
        """, (api_key_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def delete_monitor(monitor_id: str, api_key_id: int):
    """Delete a monitor."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE monitors SET is_active = 0
            WHERE id = ? AND api_key_id = ?
        """, (monitor_id, api_key_id))
        await db.commit()

# Initialize on startup
@app.on_event("startup")
async def startup():
    await init_monitors_db()

