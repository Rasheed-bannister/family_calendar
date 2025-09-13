class Chore:
    def __init__(self, id: str, title: str, notes: str, status: str, due: str):
        self.id = id
        self.title = title  # Make title available as both title and assigned_to
        self.assigned_to = title
        self.notes = notes  # Make notes available as both notes and description
        self.description = notes
        self.status = status  # from google: 'needsAction' or 'completed'. from a user: 'invisible'
        self.due = due
