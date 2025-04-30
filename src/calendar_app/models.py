import datetime

class CalendarMonth:
    def __init__(self, year: int, month: int):
        self.id = f'{month}.{year}'
        self.year = year
        self.month = month

    def __repr__(self):
        return f"CalendarMonth({self.year}, {self.month})"

class Calendar:
    def __init__(self, calendar_id, name: str, color_hex: str=None):
        self.calendar_id = calendar_id
        self.name = name
        self.color = color_hex

class CalendarEvent:
    def __init__(self,
                 id: str,
                 calendar: Calendar,
                 month: CalendarMonth, 
                 title: str, 
                 start_datetime: datetime.datetime, 
                 end_datetime: datetime.datetime, 
                 all_day: bool = False,
                 location: str = None,
                 description: str = None
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

    def __repr__(self):
        return f"CalendarEvent({self.start}, {self.end}, {self.title}, {self.description})"