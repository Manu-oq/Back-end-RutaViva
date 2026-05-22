from typing import Any


class AppError(Exception):
    status_code: int = 500
    detail: str = "Internal server error."

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        self.detail = detail or self.__class__.detail
        self.extra = extra
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found."


class PermissionError(AppError):
    status_code = 403
    detail = "You do not have permission to perform this action."


class ValidationError(AppError):
    status_code = 422
    detail = "Validation failed."


class ExternalServiceError(AppError):
    status_code = 502
    detail = "External service error."
