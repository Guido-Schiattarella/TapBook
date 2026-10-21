"""Domain errors raised by the controllers.

They carry a message for the user and a status code the view uses for the
HTTP response: the controller knows nothing about HTTP, but suggests the outcome.
"""


class ControlError(Exception):
    status = 400

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details   # extra information for the view (e.g. the reason)


class InvalidInput(ControlError):
    status = 400


class NotFound(ControlError):
    status = 404


class AlreadyExists(ControlError):
    status = 409


class Conflict(ControlError):
    status = 409


class AuthError(ControlError):
    status = 401
