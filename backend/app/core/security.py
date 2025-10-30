"""Security utilities and middleware for traffic management system"""

import hashlib
import secrets
import time
from typing import Dict, Optional, List
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
import redis

from .config import settings
from .logger import get_application_logger

logger = get_application_logger("security")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security bearer
security = HTTPBearer(auto_error=False)

# Rate limiting storage (in-memory fallback)
rate_limit_storage: Dict[str, Dict] = {}


class RateLimiter:
    """Rate limiting implementation with Redis backend"""
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.fallback_storage = {}
    
    def _get_key(self, identifier: str, window: str) -> str:
        """Generate rate limit key"""
        return f"rate_limit:{identifier}:{window}"
    
    def _get_window_key(self, window_seconds: int) -> str:
        """Get current time window key"""
        return str(int(time.time()) // window_seconds)
    
    async def is_allowed(self, 
                        identifier: str, 
                        limit: int, 
                        window_seconds: int = 60) -> bool:
        """Check if request is allowed under rate limit"""
        window_key = self._get_window_key(window_seconds)
        key = f"{self._get_key(identifier, window_key)}"
        
        try:
            if self.redis_client:
                # Use Redis for distributed rate limiting
                current_count = await self._redis_increment(key, window_seconds)
                return current_count <= limit
            else:
                # Fallback to in-memory storage
                return self._memory_check(key, limit, window_seconds)
        
        except Exception as e:
            logger.error(f"Rate limiting error: {e}")
            # Allow request on error (fail open)
            return True
    
    async def _redis_increment(self, key: str, ttl: int) -> int:
        """Increment counter in Redis"""
        pipe = self.redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        results = pipe.execute()
        return results[0]
    
    def _memory_check(self, key: str, limit: int, window_seconds: int) -> bool:
        """Check rate limit using in-memory storage"""
        now = time.time()
        
        if key not in self.fallback_storage:
            self.fallback_storage[key] = {'count': 1, 'reset_time': now + window_seconds}
            return True
        
        entry = self.fallback_storage[key]
        
        if now > entry['reset_time']:
            # Reset window
            entry['count'] = 1
            entry['reset_time'] = now + window_seconds
            return True
        
        entry['count'] += 1
        return entry['count'] <= limit


class SecurityManager:
    """Central security management"""
    
    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.blocked_ips: set = set()
        self.api_keys: Dict[str, Dict] = {}
    
    def generate_api_key(self, name: str, permissions: List[str]) -> str:
        """Generate new API key"""
        api_key = secrets.token_urlsafe(32)
        self.api_keys[api_key] = {
            'name': name,
            'permissions': permissions,
            'created_at': datetime.utcnow(),
            'last_used': None,
            'usage_count': 0
        }
        return api_key
    
    def validate_api_key(self, api_key: str) -> Optional[Dict]:
        """Validate API key and return info"""
        if api_key in self.api_keys:
            key_info = self.api_keys[api_key]
            key_info['last_used'] = datetime.utcnow()
            key_info['usage_count'] += 1
            return key_info
        return None
    
    def block_ip(self, ip_address: str, reason: str = "Security violation"):
        """Block IP address"""
        self.blocked_ips.add(ip_address)
        logger.warning(f"Blocked IP {ip_address}: {reason}")
    
    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP is blocked"""
        return ip_address in self.blocked_ips


# Global security manager
security_manager = SecurityManager()


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    # Check for forwarded IP headers (reverse proxy)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback to direct connection IP
    return request.client.host if request.client else "unknown"


def generate_csrf_token() -> str:
    """Generate CSRF token"""
    return secrets.token_urlsafe(32)


def verify_csrf_token(token: str, expected: str) -> bool:
    """Verify CSRF token"""
    return secrets.compare_digest(token, expected)


def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)
    
    to_encode.update({"exp": expire})
    
    if not settings.jwt_secret_key:
        raise ValueError("JWT secret key not configured")
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.jwt_secret_key, 
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload"""
    try:
        if not settings.jwt_secret_key:
            return None
            
        payload = jwt.decode(
            token, 
            settings.jwt_secret_key, 
            algorithms=[settings.jwt_algorithm]
        )
        return payload
        
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None


def get_password_hash(password: str) -> str:
    """Generate password hash"""
    return pwd_context.hash(password)


def verify_password_hash(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(password, password_hash)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal"""
    import os.path
    import re
    
    # Remove directory separators
    filename = os.path.basename(filename)
    
    # Remove or replace dangerous characters
    filename = re.sub(r'[^\w\-_\.]', '_', filename)
    
    # Limit length
    filename = filename[:255]
    
    # Ensure it's not empty
    if not filename or filename.startswith('.'):
        filename = f"file_{secrets.token_urlsafe(8)}.tmp"
    
    return filename


def validate_file_type(filename: str, allowed_types: List[str]) -> bool:
    """Validate file type against allowed extensions"""
    if not filename:
        return False
    
    extension = filename.lower().split('.')[-1] if '.' in filename else ''
    return extension in [t.lower().lstrip('.') for t in allowed_types]


def generate_secure_filename(original_filename: str) -> str:
    """Generate secure filename with timestamp"""
    sanitized = sanitize_filename(original_filename)
    timestamp = int(time.time())
    random_suffix = secrets.token_urlsafe(8)
    
    name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
    ext = f".{ext}" if ext else ""
    
    return f"{name}_{timestamp}_{random_suffix}{ext}"


async def check_rate_limit(request: Request, 
                          limit: int = 100, 
                          window: int = 60) -> bool:
    """Check rate limit for request"""
    client_ip = get_client_ip(request)
    
    # Check if IP is blocked
    if security_manager.is_ip_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP address blocked"
        )
    
    # Check rate limit
    allowed = await security_manager.rate_limiter.is_allowed(
        client_ip, limit, window
    )
    
    if not allowed:
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    
    return True


async def validate_api_key(credentials: Optional[HTTPAuthorizationCredentials] = None) -> Optional[Dict]:
    """Validate API key from Authorization header"""
    if not credentials:
        return None
    
    if credentials.scheme.lower() != "bearer":
        return None
    
    api_key_info = security_manager.validate_api_key(credentials.credentials)
    if not api_key_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return api_key_info


def require_permissions(required_permissions: List[str]):
    """Decorator to require specific permissions"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # This would be implemented based on your auth system
            # For now, it's a placeholder
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def log_security_event(event_type: str, 
                      client_ip: str, 
                      details: Dict, 
                      severity: str = "INFO"):
    """Log security events for monitoring"""
    log_entry = {
        'event_type': event_type,
        'client_ip': client_ip,
        'timestamp': datetime.utcnow().isoformat(),
        'severity': severity,
        'details': details
    }
    
    if severity == "WARNING":
        logger.warning(f"Security Event: {event_type}", extra=log_entry)
    elif severity == "ERROR":
        logger.error(f"Security Event: {event_type}", extra=log_entry)
    else:
        logger.info(f"Security Event: {event_type}", extra=log_entry)
