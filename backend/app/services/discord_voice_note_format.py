"""Meeting note labels and dates shared by the recorder and summarizer."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings


QUICK_SECTIONS = {
    'discussion': 'U diskutua',
    'decisions': '✅ U vendos',
    'actions': 'U kërkua të bëhet',
    'open_points': '⚠️ Mbeti e hapur',
    'follow_up': 'Për takimin tjetër',
}

DAYS = ('e hënë', 'e martë', 'e mërkurë', 'e enjte', 'e premte', 'e shtunë', 'e diel')
MONTHS = ('janar', 'shkurt', 'mars', 'prill', 'maj', 'qershor', 'korrik', 'gusht',
    'shtator', 'tetor', 'nëntor', 'dhjetor')


def albanian_date(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo(settings.APP_TIMEZONE))
    text = f'{DAYS[local.weekday()]}, {local.day} {MONTHS[local.month - 1]} {local.year}'
    return text[0].upper() + text[1:]
