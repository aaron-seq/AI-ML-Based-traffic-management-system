# AI Traffic Management System - Architecture

This document describes the software architecture of the AI Traffic Management System using C4 model diagrams.

## System Overview

The AI Traffic Management System is a modern, intelligent traffic control solution that uses computer vision and machine learning to optimize traffic flow at intersections.

## C4 Model Diagrams

### Level 1: System Context

```mermaid
C4Context
    title System Context Diagram - AI Traffic Management System

    Person(traffic_operator, "Traffic Operator", "Monitors and controls traffic signals")
    Person(city_admin, "City Administrator", "Reviews analytics and system performance")
    
    System(traffic_system, "AI Traffic Management System", "Detects vehicles, optimizes signal timing, provides real-time analytics")
    
    System_Ext(camera_system, "Traffic Cameras", "Captures intersection images")
    System_Ext(signal_controller, "Traffic Signal Controller", "Physical traffic lights hardware")
    System_Ext(emergency_dispatch, "Emergency Dispatch", "Notifies of emergency vehicles")
    
    Rel(traffic_operator, traffic_system, "Uses", "HTTPS/WebSocket")
    Rel(city_admin, traffic_system, "Reviews analytics", "HTTPS")
    Rel(camera_system, traffic_system, "Sends images", "HTTP POST")
    Rel(traffic_system, signal_controller, "Controls signals", "IoT Protocol")
    Rel(emergency_dispatch, traffic_system, "Emergency alerts", "HTTPS")
```

### Level 2: Container Diagram

```mermaid
C4Container
    title Container Diagram - AI Traffic Management System

    Person(operator, "Traffic Operator")
    
    Container_Boundary(traffic_system, "AI Traffic Management System") {
        Container(frontend, "Web Dashboard", "React, TypeScript", "Real-time traffic monitoring and control interface")
        Container(backend, "API Server", "FastAPI, Python", "REST API with WebSocket support for real-time updates")
        Container(detection_engine, "Detection Engine", "YOLOv8, PyTorch", "AI model for vehicle detection and classification")
        Container(redis_cache, "Cache", "Redis", "Session storage, rate limiting, real-time data")
        Container(mongodb, "Database", "MongoDB", "Analytics data, configuration, historical records")
    }
    
    System_Ext(cameras, "Traffic Cameras")
    
    Rel(operator, frontend, "Uses", "HTTPS")
    Rel(frontend, backend, "API calls", "HTTPS/WebSocket")
    Rel(backend, detection_engine, "Processes images", "Internal")
    Rel(backend, redis_cache, "Caches data", "Redis Protocol")
    Rel(backend, mongodb, "Stores data", "MongoDB Protocol")
    Rel(cameras, backend, "Sends images", "HTTP POST")
```

### Level 3: Component Diagram (Backend)

```mermaid
C4Component
    title Component Diagram - Backend API Server

    Container_Boundary(backend, "Backend API Server") {
        Component(main, "Main Application", "FastAPI", "Application entry point, route registration")
        Component(middleware, "Middleware Layer", "Starlette", "Security, metrics, logging, rate limiting")
        
        Component(vehicle_detector, "Vehicle Detector Service", "Python", "YOLOv8 inference, vehicle classification")
        Component(traffic_manager, "Traffic Manager Service", "Python", "Adaptive signal timing, emergency handling")
        Component(analytics_service, "Analytics Service", "Python", "Data aggregation, reporting, metrics")
        
        Component(config, "Configuration", "Pydantic", "Environment-based settings with validation")
        Component(models, "Data Models", "Pydantic", "Request/response validation schemas")
        Component(security, "Security Module", "Python", "JWT, rate limiting, input validation")
        Component(metrics, "Metrics Module", "Prometheus", "System observability and monitoring")
    }
    
    Rel(main, middleware, "Uses")
    Rel(main, vehicle_detector, "Uses")
    Rel(main, traffic_manager, "Uses")
    Rel(main, analytics_service, "Uses")
    Rel(vehicle_detector, models, "Uses")
    Rel(traffic_manager, models, "Uses")
    Rel(main, config, "Reads")
    Rel(middleware, security, "Uses")
    Rel(middleware, metrics, "Records")
```

## Technology Stack

### Backend

| Layer          | Technology        | Purpose                              |
|----------------|-------------------|--------------------------------------|
| Web Framework  | FastAPI 0.104     | Async API with OpenAPI documentation |
| ML Framework   | PyTorch 2.0+      | Deep learning inference              |
| CV Model       | YOLOv8            | Real-time object detection           |
| Validation     | Pydantic 2.5      | Request/response validation          |
| Database       | MongoDB 7         | Document storage for analytics       |
| Cache          | Redis 7           | Session, rate limiting, real-time    |
| Metrics        | Prometheus        | System observability                 |
| Logging        | structlog         | Structured logging                   |

### Frontend

| Layer          | Technology        | Purpose                              |
|----------------|-------------------|--------------------------------------|
| Framework      | React 18          | UI components                        |
| Build Tool     | Vite 4            | Fast development and building        |
| Language       | TypeScript 5      | Type-safe JavaScript                 |
| Styling        | TailwindCSS 3     | Utility-first CSS                    |
| Charts         | Chart.js          | Data visualization                   |
| Real-time      | Socket.io         | WebSocket communication              |

## Data Flow

### Vehicle Detection Flow

```
1. Camera captures intersection image
2. Image uploaded via POST /api/detect-vehicles
3. Image validated and preprocessed
4. YOLOv8 model performs inference
5. Detection results processed (bounding boxes, classification)
6. Lane assignment based on position
7. Results stored in analytics database
8. Traffic manager notified of vehicle counts
9. Signal timing optimized
10. Real-time update broadcast via WebSocket
```

### Emergency Override Flow

```
1. Emergency alert received via POST /api/emergency-override
2. Alert validated and prioritized
3. Current intersection status queried
4. Optimal clear path calculated
5. Signal states overridden for emergency lane
6. Override duration timer started
7. WebSocket broadcast to connected clients
8. Normal operation restored after timeout
```

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         PRODUCTION                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   Vercel     │    │   Railway    │    │  MongoDB     │       │
│  │  (Frontend)  │───►│  (Backend)   │───►│   Atlas      │       │
│  │              │    │              │    │              │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                                    │
│         │                   ▼                                    │
│         │            ┌──────────────┐                           │
│         │            │    Redis     │                           │
│         │            │   Cloud      │                           │
│         │            └──────────────┘                           │
│         │                                                        │
│         └──────────────────────────────────────────────────────►│
│                        WebSocket Connection                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Security Architecture

### Authentication Flow

```
1. User requests access token
2. Credentials validated
3. JWT token generated with expiration
4. Token included in Authorization header
5. Middleware validates token on each request
6. Rate limiting applied per client IP
7. Security headers added to responses
```

### Security Layers

| Layer              | Implementation                        |
|--------------------|---------------------------------------|
| Transport          | HTTPS/TLS 1.3                         |
| Authentication     | JWT tokens (HS256)                    |
| Authorization      | Role-based access control             |
| Input Validation   | Pydantic models                       |
| Rate Limiting      | Token bucket algorithm                |
| CORS               | Configured allowed origins            |
| Security Headers   | X-Frame-Options, CSP, etc.            |

## Scalability Considerations

### Horizontal Scaling

- Stateless API design enables multiple backend instances
- Redis for shared session and rate limit state
- MongoDB replica set for database scaling
- CDN for static frontend assets

### Performance Optimizations

- YOLOv8n model (nano) for fast inference
- Async/await throughout backend
- Redis caching for frequent queries
- Connection pooling for database
- Response compression

## Monitoring and Observability

### Metrics Collected

- HTTP request latency (histogram)
- Request throughput (counter)
- Error rates by type (counter)
- Model inference time (histogram)
- Active WebSocket connections (gauge)
- System resources (CPU, memory)

### Health Checks

- `/health` - Comprehensive system health
- `/healthz` - Kubernetes liveness probe
- `/ready` - Kubernetes readiness probe

## Future Architecture Considerations

1. **Multi-intersection support**: Message queue for cross-intersection coordination
2. **Edge deployment**: Lightweight inference at camera locations
3. **ML Pipeline**: MLOps for model retraining and deployment
4. **Event sourcing**: Complete audit trail of signal changes
