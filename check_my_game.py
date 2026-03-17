"""
check_my_game.py - Standalone endpoint for "Check My Game" feature

No AI involved - just data lookup:
1. Get current CCU for the game
2. Search YouTube for recent coverage
3. Return structured results

Can be called from frontend as a simple API endpoint.
"""

import asyncio
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
import duckdb
import json

def _resolve_default_db_path() -> Path:
    env_path = os.getenv("DB_PATH")
    if env_path:
        return Path(env_path)

    project_root = Path(__file__).parent
    primary_db = project_root / "early_shift.db"
    if primary_db.exists():
        src = primary_db
    elif (project_root / "early_shift_demo.db").exists():
        src = project_root / "early_shift_demo.db"
    else:
        return primary_db

    # Copy to a writable location so DuckDB can create lock/WAL files
    # (Streamlit Cloud mounts the repo read-only).
    tmp_dest = Path(tempfile.gettempdir()) / src.name
    if not tmp_dest.exists():
        shutil.copy2(src, tmp_dest)
    return tmp_dest


DB_PATH = _resolve_default_db_path()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


async def search_youtube_for_game(game_name: str, max_results: int = 10) -> list:
    """Search YouTube for recent videos about a game."""
    if not YOUTUBE_API_KEY:
        return []
    
    published_after = datetime.utcnow() - timedelta(hours=72)  # Last 3 days
    query = f"{game_name} roblox"
    
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "key": YOUTUBE_API_KEY,
        "q": query,
        "type": "video",
        "part": "snippet",
        "maxResults": max_results,
        "order": "date",
        "publishedAfter": published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    def _fetch_json() -> dict:
        request_url = f"{url}?{urlencode(params)}"
        try:
            with urlopen(request_url, timeout=10) as response:
                if response.status != 200:
                    return {}
                return json.load(response)
        except Exception:
            return {}

    data = await asyncio.to_thread(_fetch_json)
    
    videos = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = item.get("id", {}).get("videoId")
        videos.append({
            "title": snippet.get("title"),
            "channel": snippet.get("channelTitle"),
            "published": snippet.get("publishedAt"),
            "url": f"https://youtube.com/watch?v={video_id}" if video_id else None,
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
        })
    
    return videos


def get_game_ccu_status(game_name: str) -> dict:
    """Get CCU and growth status for a specific game."""
    db = duckdb.connect(str(DB_PATH), read_only=True)
    
    # Fuzzy match game name
    result = db.execute("""
        WITH latest AS (SELECT MAX(timestamp) as max_ts FROM games),
        current AS (
            SELECT universe_id, name, ccu, timestamp
            FROM games g, latest l
            WHERE g.timestamp >= l.max_ts - INTERVAL 1 HOUR
        ),
        baseline AS (
            SELECT universe_id, AVG(ccu) as avg_ccu
            FROM games g, latest l
            WHERE g.timestamp BETWEEN l.max_ts - INTERVAL 3 DAY AND l.max_ts - INTERVAL 2 DAY
            GROUP BY universe_id
        )
        SELECT 
            c.universe_id,
            c.name,
            c.ccu as current_ccu,
            b.avg_ccu as baseline_ccu,
            ROUND((c.ccu - b.avg_ccu) / NULLIF(b.avg_ccu, 0) * 100, 1) as growth_pct
        FROM current c
        LEFT JOIN baseline b ON c.universe_id = b.universe_id
        WHERE LOWER(c.name) LIKE LOWER(?)
        ORDER BY c.ccu DESC
        LIMIT 1
    """, [f"%{game_name}%"]).fetchone()
    
    if not result:
        return {"found": False, "game_name": game_name, "universe_id": None}
    
    return {
        "found": True,
        "universe_id": result[0],
        "game_name": result[1],
        "current_ccu": result[2],
        "baseline_ccu": result[3],
        "growth_pct": result[4],
        "is_growing": result[4] and result[4] > 25,
    }


async def check_my_game(game_name: str) -> dict:
    """
    Main function: Check a game's status and YouTube coverage.
    
    Returns structured data ready for frontend display.
    """
    # Get CCU status
    ccu_status = get_game_ccu_status(game_name)
    
    # Search YouTube
    videos = await search_youtube_for_game(game_name)
    
    # Determine signal strength
    video_count = len(videos)
    if video_count >= 8:
        signal = "STRONG"
        signal_emoji = "🔥🔥🔥"
    elif video_count >= 3:
        signal = "MEDIUM"
        signal_emoji = "🔥🔥"
    elif video_count >= 1:
        signal = "WEAK"
        signal_emoji = "🔥"
    else:
        signal = "NONE"
        signal_emoji = "❄️"
    
    # Build response
    response = {
        "query": game_name,
        "timestamp": datetime.utcnow().isoformat(),
        
        # CCU Data
        "ccu": {
            "found": ccu_status["found"],
            "game_name": ccu_status.get("game_name"),
            "current": ccu_status.get("current_ccu"),
            "baseline": ccu_status.get("baseline_ccu"),
            "growth_pct": ccu_status.get("growth_pct"),
            "is_growing": ccu_status.get("is_growing", False),
        },
        
        # YouTube Data
        "youtube": {
            "video_count": video_count,
            "signal_strength": signal,
            "signal_emoji": signal_emoji,
            "videos": videos[:5],  # Top 5 for display
        },
        
        # Overall Assessment
        "assessment": {
            "has_momentum": ccu_status.get("is_growing", False) and video_count >= 3,
            "recommendation": _get_recommendation(ccu_status, video_count),
        }
    }
    
    return response


def _get_recommendation(ccu_status: dict, video_count: int) -> str:
    """Generate a simple recommendation based on data."""
    is_growing = ccu_status.get("is_growing", False)
    growth = ccu_status.get("growth_pct", 0) or 0
    
    if is_growing and video_count >= 5:
        return "🚀 High momentum - creators are covering this game and CCU is spiking"
    elif is_growing and video_count >= 1:
        return "📈 Growing with some coverage - good time to push marketing"
    elif is_growing and video_count == 0:
        return "📊 Organic growth detected - no YouTube signal yet, could be opportunity"
    elif video_count >= 5:
        return "🎬 High YouTube activity but CCU flat - watch for delayed spike"
    elif video_count >= 1:
        return "👀 Some coverage, stable CCU - monitor for changes"
    else:
        return "😴 Low activity - no significant signals detected"


# CLI for testing
async def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python check_my_game.py <game_name>")
        print("Example: python check_my_game.py 'Dress To Impress'")
        return
    
    game_name = " ".join(sys.argv[1:])
    print(f"\n🔍 Checking: {game_name}\n")
    
    result = await check_my_game(game_name)
    
    # Display results
    print("=" * 50)
    print(f"GAME: {result['ccu']['game_name'] or game_name}")
    print("=" * 50)
    
    if result['ccu']['found']:
        print(f"\n📊 CCU STATUS")
        print(f"   Current:  {result['ccu']['current']:,}")
        print(f"   Baseline: {result['ccu']['baseline']:,.0f}" if result['ccu']['baseline'] else "   Baseline: N/A")
        print(f"   Growth:   {result['ccu']['growth_pct']:+.1f}%" if result['ccu']['growth_pct'] else "   Growth:   N/A")
    else:
        print(f"\n⚠️  Game not found in CCU database")
    
    print(f"\n🎬 YOUTUBE COVERAGE")
    print(f"   Videos (72h): {result['youtube']['video_count']}")
    print(f"   Signal:       {result['youtube']['signal_emoji']} {result['youtube']['signal_strength']}")
    
    if result['youtube']['videos']:
        print(f"\n   Recent videos:")
        for v in result['youtube']['videos'][:3]:
            print(f"   • {v['title'][:50]}...")
            print(f"     by {v['channel']}")
    
    print(f"\n💡 ASSESSMENT")
    print(f"   {result['assessment']['recommendation']}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
