from app.errors import ServiceError


class CollectionError(ServiceError):
    def __init__(self, status, code, message, detail):
        super().__init__(status, code, message)
        self.details = [detail]


class DependencyError(ServiceError):
    """Public diagnostics contain only service, HTTP status and approved code."""
    def __init__(self, status, code, message, upstream_status, upstream_code=None):
        super().__init__(status, code, message)
        detail = {"service": "ai", "upstream_status": upstream_status}
        if upstream_code:
            detail["upstream_code"] = upstream_code
        self.details = [detail]
