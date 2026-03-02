import json
import logging
import httpx
import redis
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

# --- 1. ERROR HANDLING & LOGGING SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WeatherProxy")

class WeatherAPIException(HTTPException):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)

# --- 2. CACHE LAYER (Scalability Consideration) ---
class MockCache:
    def __init__(self): self.store = {}
    def get(self, key): return self.store.get(key)
    def set(self, key, value, ex=None): self.store[key] = value

try:
    cache_db = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    cache_db.ping()
except Exception as e:
    logger.warning(f"Redis unavailable, falling back to In-Memory: {e}")
    cache_db = MockCache()

# --- 3. WEATHER SERVICE (RESTful Design) ---
class WeatherService:
    def __init__(self, api_key: str, cache):
        self.api_key = api_key
        self.cache = cache
        self.base_url = "https://api.openweathermap.org/data/2.5/weather"

    async def get_city_weather(self, city: str) -> Dict[str, Any]:
        cache_key = f"weather:{city.lower().strip()}"
        
        # Check Cache
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"Cache Hit for city: {city}")
            return json.loads(cached)

        # Fetch External
        logger.info(f"Cache Miss. Fetching from OpenWeatherMap for: {city}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.base_url, 
                    params={"q": city, "appid": self.api_key, "units": "metric"}
                )
                if response.status_code == 404:
                    print(f"API DEBUG LOG : {response.text}") 
                    raise WeatherAPIException("City not found", 404)
                response.raise_for_status()
                
                data = response.json()
                # Store in cache for 10 mins
                self.cache.set(cache_key, json.dumps(data), ex=600)
                return data
            except httpx.HTTPError as e:
                logger.error(f"External API Error: {str(e)}")
                raise WeatherAPIException("Weather provider is currently unreachable", 503)

# --- 4. DEPENDENCY INJECTION ---
def get_weather_service():
    return WeatherService(api_key="535758758a38f6e6bbd27589318a7e8d", cache=cache_db)

# --- 5. APP INITIALIZATION & SECURITY ---
app = FastAPI(title="CSC 281 Weather Proxy")

# Security: CORS Implementation
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/api/v1/weather", status_code=status.HTTP_200_OK)
async def fetch_weather(
    city: str = Query(..., min_length=2, max_length=50),
    service: WeatherService = Depends(get_weather_service)
):
    """
    RESTful endpoint to proxy weather data with caching.
    """
    return await service.get_city_weather(city)

