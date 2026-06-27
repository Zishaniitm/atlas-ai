"""Weather skill — Open-Meteo API (free, no API key). SRS: FR-028"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_WMO_CODES: dict[int, str] = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "showers",
    95: "thunderstorm", 99: "heavy thunderstorm",
}


class WeatherSkill(BaseSkill):
    name: ClassVar[str] = "get_weather"
    description: ClassVar[str] = (
        "Fetch current weather and 7-day forecast for a given city."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "city":  {"type": "string", "required": True},
        "units": {"type": "string", "required": False,
                  "enum": ["celsius", "fahrenheit"], "default": "celsius"},
    }
    permissions: ClassVar[list[str]] = ["network.outbound"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, city: str, units: str = "celsius") -> SkillResult:
        """SRS: FR-028, SRS Appendix 14.1"""
        try:
            import httpx  # type: ignore[import]

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: geocode city → lat/lon via Open-Meteo geocoding
                geo = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": city, "count": 1, "format": "json"},
                )
                geo.raise_for_status()
                geo_data = geo.json()

                locations = geo_data.get("results", [])
                if not locations:
                    return SkillResult(success=False,
                                       error=f"City not found: '{city}'")

                loc = locations[0]
                lat, lon = loc["latitude"], loc["longitude"]
                city_name = loc.get("name", city)
                country   = loc.get("country", "")
                temp_unit = "celsius" if units == "celsius" else "fahrenheit"

                # Step 2: fetch weather
                weather = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat, "longitude": lon,
                        "current": ["temperature_2m", "weathercode", "windspeed_10m", "relativehumidity_2m"],
                        "daily": ["temperature_2m_max", "temperature_2m_min", "weathercode"],
                        "temperature_unit": temp_unit,
                        "timezone": "auto",
                        "forecast_days": 7,
                    },
                )
                weather.raise_for_status()
                w = weather.json()

            current = w.get("current", {})
            daily   = w.get("daily", {})

            temp      = current.get("temperature_2m")
            humidity  = current.get("relativehumidity_2m")
            wind      = current.get("windspeed_10m")
            wmo_code  = current.get("weathercode", 0)
            condition = _WMO_CODES.get(wmo_code, "unknown")
            unit_sym  = "°C" if units == "celsius" else "°F"

            forecast = []
            dates     = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            wmo_daily = daily.get("weathercode", [])

            for i in range(min(7, len(dates))):
                forecast.append({
                    "date":      dates[i],
                    "max_temp":  max_temps[i] if i < len(max_temps) else None,
                    "min_temp":  min_temps[i] if i < len(min_temps) else None,
                    "condition": _WMO_CODES.get(wmo_daily[i] if i < len(wmo_daily) else 0, ""),
                })

            return SkillResult(
                success=True,
                data={
                    "city": city_name, "country": country,
                    "temp": temp, "unit": unit_sym, "condition": condition,
                    "humidity": humidity, "wind_kmh": wind,
                    "forecast": forecast,
                },
                speak=(
                    f"Currently in {city_name}: {temp}{unit_sym}, {condition}. "
                    f"Humidity {humidity}%, wind {wind} km/h."
                ),
            )

        except Exception as exc:
            logger.error("weather_failed", city=city, exc_info=exc)
            return SkillResult(success=False, error=f"Weather lookup failed: {exc}")
