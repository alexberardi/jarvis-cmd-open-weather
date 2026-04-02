# Weather for Jarvis

Current weather conditions and forecasts up to 8 days via the OpenWeather API.

## Components

| Type | Name | Description |
|------|------|-------------|
| Command | `get_weather` | "What's the weather in Chicago?", "Forecast for tomorrow?", "Do I need an umbrella?" |

## Install

```bash
jarvis pantry install --url https://github.com/alexberardi/jarvis-cmd-weather
```

Or from a local checkout:

```bash
jarvis pantry install --local /path/to/jarvis-cmd-weather
```

## Setup

1. Create a free account at [openweathermap.org](https://openweathermap.org)
2. Copy your API key from **My API Keys**
3. Set `OPENWEATHER_API_KEY` in your node settings

The free tier includes **1,000 calls/day**.

## Secrets

| Key | Required | Description |
|-----|----------|-------------|
| `OPENWEATHER_API_KEY` | Yes | OpenWeather API key |
| `OPENWEATHER_UNITS` | No | `imperial` (default), `metric`, or `kelvin` |
| `OPENWEATHER_LOCATION` | No | Default location as `City,State,Country` (e.g., `Miami,FL,US`) |

## Structure

```
jarvis_package.yaml
commands/
  get_weather/command.py
```

## License

MIT
