"""WeatherContextAgent — injects current weather into CC memory system.

Runs every 30 minutes. Fetches current conditions and today/tomorrow forecast
via OpenWeather API, then pushes into the command center's memory system so
Jarvis has proactive weather awareness during conversations.

Requires OPENWEATHER_API_KEY to be configured.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

try:
    from jarvis_log_client import JarvisLogger
except ImportError:
    import logging

    class JarvisLogger:
        def __init__(self, **kw: str) -> None:
            self._log = logging.getLogger(kw.get("service", __name__))
        def info(self, msg: str, **kw: object) -> None: self._log.info(msg)
        def warning(self, msg: str, **kw: object) -> None: self._log.warning(msg)
        def error(self, msg: str, **kw: object) -> None: self._log.error(msg)
        def debug(self, msg: str, **kw: object) -> None: self._log.debug(msg)

from jarvis_command_sdk import (
    AgentSchedule,
    Alert,
    IJarvisAgent,
    IJarvisSecret,
    JarvisSecret,
    JarvisStorage,
)

logger = JarvisLogger(service="jarvis-node")

REFRESH_INTERVAL_SECONDS = 1800  # 30 minutes
CURRENT_TTL_HOURS = 3
FORECAST_TTL_HOURS = 12

_storage = JarvisStorage("weather_context")


class WeatherContextAgent(IJarvisAgent):
    """Background agent that injects weather context into CC memory."""

    def __init__(self) -> None:
        self._alerts: List[Alert] = []

    @property
    def name(self) -> str:
        return "weather_context"

    @property
    def description(self) -> str:
        return "Periodically fetches weather and injects into memory for proactive awareness"

    @property
    def schedule(self) -> AgentSchedule:
        return AgentSchedule(
            interval_seconds=REFRESH_INTERVAL_SECONDS,
            run_on_startup=True,
        )

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return [
            JarvisSecret(
                "OPENWEATHER_API_KEY",
                "OpenWeather API key (free tier: 1000 calls/day)",
                "integration",
                "string",
                required=True,
            ),
            JarvisSecret(
                "OPENWEATHER_LOCATION",
                "Default location as city,state_code,country_code (e.g., Miami,FL,US)",
                "integration",
                "string",
                required=False,
            ),
        ]

    @property
    def include_in_context(self) -> bool:
        return False

    async def run(self) -> None:
        """Fetch weather and inject into CC memory."""
        # Verify API key is available
        api_key = _storage.get_secret("OPENWEATHER_API_KEY")
        if not api_key:
            logger.debug("Weather agent skipped — no OPENWEATHER_API_KEY configured")
            return

        try:
            try:
                # Source layout (dev / tests): commands/get_weather/command.py
                from commands.get_weather.command import OpenWeatherCommand
            except ImportError:
                # Installed layout: the component is named "get_weather_openweather"
                # in the manifest, so the node scatters the command to
                # commands/custom_commands/get_weather_openweather/ — NOT
                # ".../get_weather/" (which the source path implies).
                from commands.custom_commands.get_weather_openweather.command import OpenWeatherCommand

            from jarvis_command_sdk import RequestInformation

            cmd = OpenWeatherCommand()

            # OpenWeatherCommand.run() requires secrets as a keyword-only arg
            # (commit 919cf36: refactor to SDK secrets kwarg). The voice path
            # gets this from the runtime; agents call .run() directly so we
            # have to assemble the dict ourselves.
            secrets: dict[str, str] = {"OPENWEATHER_API_KEY": api_key}
            for optional_key in ("OPENWEATHER_LOCATION", "OPENWEATHER_UNITS"):
                val = _storage.get_secret(optional_key)
                if val:
                    secrets[optional_key] = val

            # resolved_datetimes must be ISO date strings (YYYY-MM-DD), not
            # relative keys like "today"/"tomorrow". The voice path goes
            # through the SDK's RelativeDateKeys resolver before the command
            # sees them; we have to pre-resolve ourselves. Local-time dates
            # are what the user means by "today"/"tomorrow" in their tz.
            today_iso = datetime.now().date().isoformat()
            tomorrow_iso = (datetime.now().date() + timedelta(days=1)).isoformat()

            # Fetch current weather
            request_info = RequestInformation(
                voice_command="weather check",
                conversation_id="weather-context-agent",
            )
            current_response = cmd.run(
                request_info, secrets=secrets, resolved_datetimes=[today_iso],
            )

            # Fetch tomorrow's forecast
            tomorrow_response = cmd.run(
                request_info, secrets=secrets, resolved_datetimes=[tomorrow_iso],
            )

            memories = []
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Current conditions
            if current_response.success and current_response.context_data:
                ctx = current_response.context_data
                city = ctx.get("city", "")
                temp = ctx.get("temperature", "")
                desc = ctx.get("description", "")
                humidity = ctx.get("humidity", "")
                wind = ctx.get("wind_speed", "")
                units = ctx.get("unit_system", "imperial")
                temp_unit = "°F" if units == "imperial" else "°C"

                content = f"Current weather in {city}: {temp}{temp_unit}"
                if desc:
                    content += f", {desc}"
                if humidity and humidity != "N/A":
                    content += f". Humidity {humidity}%"
                if wind and wind != "N/A":
                    speed_unit = "mph" if units == "imperial" else "m/s"
                    content += f", wind {wind} {speed_unit}"

                memories.append({
                    "content": content,
                    "category": "weather",
                    "key": f"weather:current:{today}",
                    "ttl_hours": CURRENT_TTL_HOURS,
                    "source": "weather-agent:openweather",
                })

                # Today's high/low from forecast details
                details = ctx.get("forecast_details", [])
                if details:
                    d = details[0]
                    high = d.get("high_temp", "")
                    low = d.get("low_temp", "")
                    pop = d.get("pop", 0)
                    forecast_desc = d.get("description", "")

                    fc = f"Today's forecast for {city}: High {high}{temp_unit}, low {low}{temp_unit}"
                    if forecast_desc:
                        fc += f", {forecast_desc}"
                    if pop and pop > 0.2:
                        fc += f". {int(pop * 100)}% chance of precipitation"

                    memories.append({
                        "content": fc,
                        "category": "weather",
                        "key": f"weather:forecast:today:{today}",
                        "ttl_hours": FORECAST_TTL_HOURS,
                        "source": "weather-agent:openweather",
                    })

            # Tomorrow's forecast
            if tomorrow_response.success and tomorrow_response.context_data:
                ctx = tomorrow_response.context_data
                city = ctx.get("city", "")
                details = ctx.get("forecast_details", [])
                units = ctx.get("unit_system", "imperial")
                temp_unit = "°F" if units == "imperial" else "°C"

                if details:
                    d = details[0]
                    high = d.get("high_temp", "")
                    low = d.get("low_temp", "")
                    pop = d.get("pop", 0)
                    desc = d.get("description", "")

                    fc = f"Tomorrow's forecast for {city}: High {high}{temp_unit}, low {low}{temp_unit}"
                    if desc:
                        fc += f", {desc}"
                    if pop and pop > 0.2:
                        fc += f". {int(pop * 100)}% chance of precipitation"

                    memories.append({
                        "content": fc,
                        "category": "weather",
                        "key": f"weather:forecast:tomorrow:{today}",
                        "ttl_hours": FORECAST_TTL_HOURS,
                        "source": "weather-agent:openweather",
                    })

            # Inject into CC
            if memories:
                try:
                    from clients.rest_client import RestClient
                    result = RestClient.inject_memories(memories)
                    if result:
                        logger.info(
                            "Weather agent injected memories",
                            count=result.get("injected", 0) + result.get("updated", 0),
                        )
                except ImportError:
                    logger.debug("RestClient not available — skipping memory injection")

        except Exception as e:
            logger.error("Weather context agent run failed", error=str(e))

    def get_context_data(self) -> Dict[str, Any]:
        return {}

    def get_alerts(self) -> List[Alert]:
        return list(self._alerts)
