class Chore:
    def __init__(self, id: str, title: str, notes: str, status: str, due: str):
        self.id = id
        self.assigned_to = title
        self.description = notes
        self.status = status # from google: 'needsAction' or 'completed'. from a user: 'invisible'
        self.due = due
