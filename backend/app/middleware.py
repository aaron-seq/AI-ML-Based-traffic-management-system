"""Custom middleware for the traffic management system"""

import time
from typing import Callable
from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .core.logger import get_application_logger
from .core.security import check_rate_limit, get_client_ip, log_security_event
from .core.metrics import (
    http_requests_total, http_request_duration_seconds, 
    http_requests_in_progress, errors_total
)

logger = get_application_logger("middleware")


class SecurityMiddleware(BaseHTTPMiddleware):
    """Security middleware for request validation and rate limiting"""
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.blocked_paths = set()
        self.sensitive_paths = {
            '/api/detect-vehicles',
            '/api/emergency-override',
            '/api/configuration'
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        client_ip = get_client_ip(request)
        path = request.url.path
        method = request.method
        
        # Security headers for all responses
        def add_security_headers(response: Response) -> Response:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            return response
        
        try:
            # Rate limiting for sensitive endpoints
            if path in self.sensitive_paths:
                try:
                    await check_rate_limit(request, limit=10, window=60)  # 10 requests per minute
                except HTTPException as e:
                    log_security_event(
                        "rate_limit_exceeded",
                        client_ip,
                        {"path": path, "method": method},
                        "WARNING"
                    )
                    response = JSONResponse(
                        status_code=e.status_code,
                        content={"detail": e.detail}
                    )
                    return add_security_headers(response)
            
            # General rate limiting
            try:
                await check_rate_limit(request, limit=100, window=60)  # 100 requests per minute
            except HTTPException as e:
                response = JSONResponse(
                    status_code=e.status_code,
                    content={"detail": e.detail}
                )
                return add_security_headers(response)
            
            # Block suspicious requests
            if self._is_suspicious_request(request):
                log_security_event(
                    "suspicious_request_blocked",
                    client_ip,
                    {
                        "path": path,
                        "method": method,
                        "user_agent": request.headers.get("user-agent", "")
                    },
                    "WARNING"
                )
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Request blocked for security reasons"}
                )
                return add_security_headers(response)
            
            # Process request
            response = await call_next(request)
            
            # Add security headers
            response = add_security_headers(response)
            
            # Log successful request
            processing_time = time.time() - start_time
            logger.info(
                f"{method} {path} - {response.status_code} - {processing_time:.3f}s - {client_ip}"
            )
            
            return response
            
        except Exception as e:
            # Log error
            processing_time = time.time() - start_time
            logger.error(
                f"Request error: {method} {path} - {type(e).__name__}: {str(e)} - {processing_time:.3f}s - {client_ip}"
            )
            
            # Return error response
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"}
            )
            return add_security_headers(response)
    
    def _is_suspicious_request(self, request: Request) -> bool:
        """Detect suspicious request patterns"""
        path = request.url.path.lower()
        query = str(request.query_params).lower()
        user_agent = request.headers.get("user-agent", "").lower()
        
        # Common attack patterns
        suspicious_patterns = [
            "../", "..%2f", "..%5c",  # Path traversal
            "<script", "javascript:", "onload=",  # XSS
            "union select", "drop table", "insert into",  # SQL injection
            "etc/passwd", "windows/system32",  # File access
            "cmd.exe", "/bin/sh", "powershell",  # Command injection
        ]
        
        # Check for suspicious patterns
        combined_content = f"{path} {query}"
        for pattern in suspicious_patterns:
            if pattern in combined_content:
                return True
        
        # Check for suspicious user agents
        suspicious_agents = [
            "sqlmap", "nikto", "nmap", "masscan",
            "nessus", "openvas", "w3af", "skipfish"
        ]
        
        for agent in suspicious_agents:
            if agent in user_agent:
                return True
        
        return False


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for collecting Prometheus metrics"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        method = request.method
        path = request.url.path
        
        # Normalize path for metrics (remove IDs and dynamic parts)
        normalized_path = self._normalize_path(path)
        
        # Track request start
        http_requests_in_progress.labels(
            method=method,
            endpoint=normalized_path
        ).inc()
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Track successful request
            http_requests_total.labels(
                method=method,
                endpoint=normalized_path,
                status_code=status_code
            ).inc()
            
            return response
            
        except Exception as e:
            # Track error
            errors_total.labels(
                error_type=type(e).__name__,
                component='http_middleware'
            ).inc()
            
            http_requests_total.labels(
                method=method,
                endpoint=normalized_path,
                status_code=500
            ).inc()
            
            raise
        
        finally:
            # Track request completion
            processing_time = time.time() - start_time
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=normalized_path
            ).observe(processing_time)
            
            http_requests_in_progress.labels(
                method=method,
                endpoint=normalized_path
            ).dec()
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics by removing dynamic segments"""
        # Remove trailing slash
        path = path.rstrip('/')
        
        # Common normalizations
        normalizations = [
            (r'/api/analytics/\w+', '/api/analytics/{type}'),
            (r'/api/detection/[0-9a-f-]+', '/api/detection/{id}'),
            (r'/files/[0-9a-f-]+', '/files/{id}'),
        ]
        
        import re
        for pattern, replacement in normalizations:
            path = re.sub(pattern, replacement, path)
        
        return path or '/'


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for detailed request/response logging"""
    
    def __init__(self, app: ASGIApp, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        client_ip = get_client_ip(request)
        
        # Log request
        request_info = {
            "method": request.method,
            "url": str(request.url),
            "client_ip": client_ip,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "content_type": request.headers.get("content-type", "unknown"),
            "content_length": request.headers.get("content-length", "0"),
        }
        
        logger.info("Request started", extra=request_info)
        
        try:
            response = await call_next(request)
            
            # Log response
            processing_time = time.time() - start_time
            response_info = {
                **request_info,
                "status_code": response.status_code,
                "response_time": round(processing_time, 3),
                "response_size": response.headers.get("content-length", "unknown")
            }
            
            if response.status_code >= 400:
                logger.warning("Request completed with error", extra=response_info)
            else:
                logger.info("Request completed successfully", extra=response_info)
            
            return response
            
        except Exception as e:
            # Log exception
            processing_time = time.time() - start_time
            error_info = {
                **request_info,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "processing_time": round(processing_time, 3)
            }
            
            logger.error("Request failed with exception", extra=error_info)
            raise


class HealthCheckMiddleware(BaseHTTPMiddleware):
    """Middleware for health check optimization"""
    
    def __init__(self, app: ASGIApp, health_paths: set = None):
        super().__init__(app)
        self.health_paths = health_paths or {'/health', '/healthz', '/ready'}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Fast path for health checks
        if request.url.path in self.health_paths:
            # Skip heavy middleware for health checks
            return await call_next(request)
        
        # Normal processing for other requests
        return await call_next(request)


class CompressionMiddleware(BaseHTTPMiddleware):
    """Middleware for response compression"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # Add compression hint header
        accept_encoding = request.headers.get("accept-encoding", "")
        if "gzip" in accept_encoding.lower():
            # Let the web server handle actual compression
            response.headers["Vary"] = "Accept-Encoding"
        
        return response
