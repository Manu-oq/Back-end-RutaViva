from typing import Any


class AppError(Exception):
    status_code: int = 500
    detail: str = "Internal server error."

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail or self.__class__.detail
        self.extra = extra
        super().__init__(self.detail)


class PermissionError(AppError):
    status_code = 403
    detail = "You do not have permission to perform this action."


class ConflictError(AppError):
    status_code = 409
    detail = "The requested operation conflicts with the current resource state."


class ItineraryNotEditableError(ConflictError):
    detail = "Itinerary is no longer editable."
