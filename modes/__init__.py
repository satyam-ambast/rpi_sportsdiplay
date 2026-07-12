from modes.weather import WeatherMode
from modes.cricket import CricketMode
from modes.football import FootballMode
from modes.f1 import F1Mode

# Registry the rest of the app uses to look up a mode by its key.
MODES = {
    m.key: m
    for m in [WeatherMode(), CricketMode(), FootballMode(), F1Mode()]
}
