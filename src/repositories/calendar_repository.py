from datetime import date, datetime

from sqlalchemy import text

from database import Context


class CalendarRepository:
    """Que horas são e se hoje é dia útil — perguntado ao PRÓPRIO banco.

    Dia útil = não é sábado nem domingo e não está na tabela holiday.
    """

    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def local_now(self) -> datetime:
        return self.session.execute(text("SELECT now() AT TIME ZONE 'America/Sao_Paulo'")).scalar_one()

    def is_business_day(self, day: date) -> bool:
        if day.weekday() >= 5:
            return False
        holiday = self.session.execute(text("SELECT 1 FROM holiday WHERE date = :day"), {"day": day}).first()
        return holiday is None

    def next_business_day_on_or_after(self, day: date) -> date:
        from datetime import timedelta

        while not self.is_business_day(day):
            day = day + timedelta(days=1)
        return day
