import datetime
from typing import Optional


class CalendarMonth:
    def __init__(self, year: int, month: int):
        self.id = f"{month}.{year}"
        self.year = year
        self.month = month

    def __repr__(self) -> str:
        return f"CalendarMonth({self.year}, {self.month})"


class Calendar:
    def __init__(
        self,
        calendar_id: str,
        name: str,
        display_name: Optional[str] = None,
        color_hex: Optional[str] = None,
    ):
        self.calendar_id = calendar_id
        self.name = name
        self.display_name = (
            display_name or name
        )  # Use display_name if provided, otherwise fall back to name
        self.color = color_hex

    def get_display_name(self) -> str:
        """Returns the display name if set, otherwise returns the original name"""
        return self.display_name if self.display_name else self.name


class CalendarEvent:
    def __init__(
        self,
        id: str,
        calendar: Calendar,
        month: CalendarMonth,
        title: str,
        start_datetime: datetime.datetime,
        end_datetime: datetime.datetime,
        all_day: bool = False,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """
        Initialize a CalendarEvent object.
        """
        self.id = id
        self.calendar = calendar
        self.month = month
        self.title = title
        self.start = start_datetime
        self.end = end_datetime
        self.all_day = all_day
        self.location = location
        self.description = description

    def __repr__(self) -> str:
        return (
            f"CalendarEvent({self.start}, {self.end}, {self.title}, {self.description})"
        )
