"""
Application middleware for logging and error handling
"""

import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..core.logger import get_application_logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log incoming requests and responses"""

    async def dispatch(self, request: Request, call_next) -> Response:

        logger = get_application_logger("middleware")

        start_time = time.time()

        logger.info(
            "Request received",
            extra={
                "method": request.method,
                "url": str(request.url),
                "client_host": request.client.host,
                "client_port": request.client.port,
            },
        )

        try:
            response = await call_next(request)
            processing_time = (time.time() - start_time) * 1000  # in ms

            logger.info(
                "Request processed successfully",
                extra={
                    "status_code": response.status_code,
                    "processing_time_ms": f"{processing_time:.2f}",
                },
            )

            return response

        except Exception as e:
            logger.exception(
                "An unhandled error occurred",
                extra={"error": str(e)}
            )
            # Re-raise the exception to be handled by FastAPI's error handling
            raise
