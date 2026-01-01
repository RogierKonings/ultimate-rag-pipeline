# US-6.5: Structured Logging

> **Story ID:** US-6.5  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-6.1 (OpenTelemetry Integration)

## User Story

**As a** developer  
**I want** structured JSON logging  
**So that** logs are searchable and parseable

## Context

Structured logging is essential for effective debugging and log analysis in a distributed system. JSON-formatted logs with consistent fields enable:

- Correlation with distributed traces
- Log aggregation and searching in Loki/Elasticsearch
- Automated log-based alerting
- Easy parsing and analysis

This story implements a standardized logging framework across all RAG services with trace context injection, sensitive data filtering, and integration with Loki for log aggregation.

## Technical Requirements

### Directory Structure

```
observability/
├── logging/
│   ├── __init__.py
│   ├── config.py              # Logging configuration
│   ├── logger.py              # Logger factory
│   ├── formatters.py          # JSON formatters
│   ├── filters.py             # Sensitive data filters
│   ├── context.py             # Context injection (trace, tenant)
│   ├── handlers.py            # Custom handlers
│   └── middleware/
│       ├── __init__.py
│       ├── fastapi.py         # FastAPI logging middleware
│       └── celery.py          # Celery task logging
├── loki/
│   ├── loki-config.yaml       # Loki configuration
│   └── promtail-config.yaml   # Promtail configuration
└── k8s/
    ├── loki.yaml              # Loki deployment
    └── promtail.yaml          # Promtail DaemonSet
```

### Logging Configuration

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import os


class LogLevel(str, Enum):
    """Standard log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogOutput(str, Enum):
    """Log output destinations."""
    CONSOLE = "console"
    FILE = "file"
    BOTH = "both"


class LoggingConfig(BaseModel):
    """
    Logging configuration for RAG services.
    
    Supports structured JSON logging with trace context,
    sensitive data filtering, and multiple output targets.
    """
    # Service identification
    service_name: str
    service_version: str = "1.0.0"
    environment: str = "development"
    
    # Log level
    level: LogLevel = LogLevel.INFO
    
    # Output configuration
    output: LogOutput = LogOutput.CONSOLE
    log_file_path: Optional[str] = None
    
    # JSON formatting
    json_format: bool = True
    pretty_print: bool = False  # Only for development
    
    # Trace context
    include_trace_context: bool = True
    
    # Performance
    async_logging: bool = True
    buffer_size: int = 1000
    
    # Filtering
    filter_sensitive_fields: List[str] = Field(
        default_factory=lambda: [
            "password",
            "token",
            "api_key",
            "secret",
            "authorization",
            "cookie",
            "credit_card",
            "ssn",
        ]
    )
    mask_pattern: str = "***REDACTED***"
    
    # Request logging
    log_request_body: bool = False  # Disable by default for performance
    log_response_body: bool = False
    max_body_length: int = 1000
    
    # Excluded paths (health checks, metrics)
    excluded_paths: List[str] = Field(
        default_factory=lambda: [
            "/health",
            "/ready",
            "/metrics",
            "/favicon.ico",
        ]
    )
    
    @classmethod
    def from_env(cls, service_name: str) -> "LoggingConfig":
        """Create config from environment variables."""
        return cls(
            service_name=service_name,
            service_version=os.getenv("SERVICE_VERSION", "1.0.0"),
            environment=os.getenv("ENVIRONMENT", "development"),
            level=LogLevel(os.getenv("LOG_LEVEL", "INFO")),
            json_format=os.getenv("LOG_JSON", "true").lower() == "true",
            include_trace_context=os.getenv("LOG_TRACE_CONTEXT", "true").lower() == "true",
        )
```

### JSON Formatter

```python
import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from opentelemetry import trace


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter with trace context.
    
    Produces structured JSON logs with:
    - Timestamp in ISO 8601 format
    - Log level
    - Service identification
    - Trace/span IDs for correlation
    - Custom fields
    - Exception details
    """
    
    def __init__(
        self,
        service_name: str,
        service_version: str,
        environment: str,
        include_trace_context: bool = True,
        extra_fields: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.include_trace_context = include_trace_context
        self.extra_fields = extra_fields or {}
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_dict = self._build_log_dict(record)
        return json.dumps(log_dict, default=str, ensure_ascii=False)
    
    def _build_log_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Build the log dictionary."""
        log_dict = {
            # Timestamp
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "time_unix_ms": int(record.created * 1000),
            
            # Log level
            "level": record.levelname,
            "level_num": record.levelno,
            
            # Message
            "message": record.getMessage(),
            
            # Service identification
            "service": {
                "name": self.service_name,
                "version": self.service_version,
                "environment": self.environment,
            },
            
            # Source location
            "source": {
                "file": record.filename,
                "line": record.lineno,
                "function": record.funcName,
                "module": record.module,
            },
        }
        
        # Add trace context
        if self.include_trace_context:
            trace_context = self._get_trace_context()
            if trace_context:
                log_dict["trace"] = trace_context
        
        # Add exception info
        if record.exc_info:
            log_dict["exception"] = self._format_exception(record.exc_info)
        
        # Add extra fields from record
        if hasattr(record, "extra"):
            log_dict["extra"] = record.extra
        
        # Add any additional fields passed via extra
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "extra", "message",
            }:
                if "extra" not in log_dict:
                    log_dict["extra"] = {}
                log_dict["extra"][key] = value
        
        # Add static extra fields
        log_dict.update(self.extra_fields)
        
        return log_dict
    
    def _get_trace_context(self) -> Optional[Dict[str, str]]:
        """Get current trace context from OpenTelemetry."""
        span = trace.get_current_span()
        ctx = span.get_span_context()
        
        if ctx.is_valid:
            return {
                "trace_id": format(ctx.trace_id, '032x'),
                "span_id": format(ctx.span_id, '016x'),
            }
        return None
    
    def _format_exception(self, exc_info) -> Dict[str, Any]:
        """Format exception information."""
        exc_type, exc_value, exc_tb = exc_info
        
        return {
            "type": exc_type.__name__ if exc_type else None,
            "message": str(exc_value) if exc_value else None,
            "stacktrace": traceback.format_exception(
                exc_type, exc_value, exc_tb
            ) if exc_tb else None,
        }


class PrettyJSONFormatter(JSONFormatter):
    """
    Pretty-printed JSON formatter for development.
    
    Same as JSONFormatter but with indentation for readability.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_dict = self._build_log_dict(record)
        return json.dumps(log_dict, default=str, indent=2, ensure_ascii=False)
```

### Sensitive Data Filter

```python
import re
import logging
from typing import List, Any, Dict, Set
import copy


class SensitiveDataFilter(logging.Filter):
    """
    Filter to mask sensitive data in log records.
    
    Scans log messages and extra fields for sensitive patterns
    and replaces them with a mask.
    """
    
    def __init__(
        self,
        sensitive_fields: List[str],
        mask: str = "***REDACTED***",
    ):
        super().__init__()
        self.sensitive_fields = set(f.lower() for f in sensitive_fields)
        self.mask = mask
        
        # Patterns for common sensitive data
        self.patterns = [
            # API keys (various formats)
            (re.compile(r'api[_-]?key["\s:=]+["\']?([a-zA-Z0-9_\-]{20,})["\']?', re.I), 'api_key'),
            # Bearer tokens
            (re.compile(r'bearer\s+([a-zA-Z0-9_\-\.]+)', re.I), 'token'),
            # Basic auth
            (re.compile(r'basic\s+([a-zA-Z0-9+/=]+)', re.I), 'auth'),
            # JWT tokens
            (re.compile(r'eyJ[a-zA-Z0-9_\-]*\.eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]*'), 'jwt'),
            # Credit card numbers
            (re.compile(r'\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b'), 'credit_card'),
            # Email addresses (optional, may want to keep)
            # (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), 'email'),
        ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and mask sensitive data in the record."""
        # Mask message
        record.msg = self._mask_string(record.msg)
        
        # Mask args
        if record.args:
            record.args = tuple(
                self._mask_value(arg) for arg in record.args
            )
        
        # Mask extra fields
        for key in list(record.__dict__.keys()):
            if key.lower() in self.sensitive_fields:
                setattr(record, key, self.mask)
            elif isinstance(getattr(record, key), (dict, list)):
                setattr(record, key, self._mask_value(getattr(record, key)))
        
        return True  # Always allow the record through
    
    def _mask_string(self, value: str) -> str:
        """Mask sensitive patterns in a string."""
        if not isinstance(value, str):
            return value
        
        result = value
        for pattern, name in self.patterns:
            result = pattern.sub(f'{name}={self.mask}', result)
        
        return result
    
    def _mask_value(self, value: Any) -> Any:
        """Recursively mask sensitive values."""
        if isinstance(value, str):
            return self._mask_string(value)
        elif isinstance(value, dict):
            return self._mask_dict(value)
        elif isinstance(value, (list, tuple)):
            return type(value)(self._mask_value(v) for v in value)
        return value
    
    def _mask_dict(self, d: Dict) -> Dict:
        """Mask sensitive keys in a dictionary."""
        result = {}
        for key, value in d.items():
            if key.lower() in self.sensitive_fields:
                result[key] = self.mask
            else:
                result[key] = self._mask_value(value)
        return result
```

### Context Injection

```python
import logging
import contextvars
from typing import Optional, Dict, Any
from uuid import UUID


# Context variables for request context
request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'request_id', default=None
)
tenant_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'tenant_id', default=None
)
user_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'user_id', default=None
)


class ContextInjectorFilter(logging.Filter):
    """
    Filter that injects context information into log records.
    
    Adds:
    - request_id
    - tenant_id
    - user_id
    - Any additional context variables
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Inject context into the log record."""
        record.request_id = request_id_var.get()
        record.tenant_id = tenant_id_var.get()
        record.user_id = user_id_var.get()
        return True


def set_request_context(
    request_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Set request context for the current async context."""
    if request_id:
        request_id_var.set(request_id)
    if tenant_id:
        tenant_id_var.set(tenant_id)
    if user_id:
        user_id_var.set(user_id)


def clear_request_context() -> None:
    """Clear request context."""
    request_id_var.set(None)
    tenant_id_var.set(None)
    user_id_var.set(None)


class LoggerAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds context to all log calls.
    
    Example:
        logger = get_logger("my-service")
        logger.info("Processing request", extra={"query": query})
    """
    
    def process(self, msg, kwargs):
        """Add context to kwargs."""
        extra = kwargs.get('extra', {})
        
        # Add context variables
        extra['request_id'] = request_id_var.get()
        extra['tenant_id'] = tenant_id_var.get()
        extra['user_id'] = user_id_var.get()
        
        # Add any adapter extra
        extra.update(self.extra)
        
        kwargs['extra'] = extra
        return msg, kwargs
```

### Logger Factory

```python
import logging
import sys
from typing import Optional, Dict, Any
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
from queue import Queue


_loggers: Dict[str, logging.Logger] = {}
_queue_listener: Optional[QueueListener] = None


def setup_logging(config: LoggingConfig) -> None:
    """
    Set up logging for the application.
    
    Configures:
    1. Root logger with JSON formatter
    2. Sensitive data filter
    3. Context injection
    4. Async logging (if enabled)
    """
    global _queue_listener
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level.value))
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Create formatter
    if config.json_format:
        if config.pretty_print:
            formatter = PrettyJSONFormatter(
                service_name=config.service_name,
                service_version=config.service_version,
                environment=config.environment,
                include_trace_context=config.include_trace_context,
            )
        else:
            formatter = JSONFormatter(
                service_name=config.service_name,
                service_version=config.service_version,
                environment=config.environment,
                include_trace_context=config.include_trace_context,
            )
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    # Create handlers
    handlers = []
    
    if config.output in (LogOutput.CONSOLE, LogOutput.BOTH):
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)
    
    if config.output in (LogOutput.FILE, LogOutput.BOTH) and config.log_file_path:
        file_handler = RotatingFileHandler(
            config.log_file_path,
            maxBytes=100 * 1024 * 1024,  # 100 MB
            backupCount=5,
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # Create filters
    sensitive_filter = SensitiveDataFilter(
        sensitive_fields=config.filter_sensitive_fields,
        mask=config.mask_pattern,
    )
    context_filter = ContextInjectorFilter()
    
    # Apply filters to handlers
    for handler in handlers:
        handler.addFilter(sensitive_filter)
        handler.addFilter(context_filter)
    
    # Set up async logging if enabled
    if config.async_logging:
        log_queue = Queue(maxsize=config.buffer_size)
        queue_handler = QueueHandler(log_queue)
        root_logger.addHandler(queue_handler)
        
        _queue_listener = QueueListener(log_queue, *handlers, respect_handler_level=True)
        _queue_listener.start()
    else:
        for handler in handlers:
            root_logger.addHandler(handler)
    
    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> LoggerAdapter:
    """
    Get a logger with context injection.
    
    Args:
        name: Logger name (usually module name or service name)
    
    Returns:
        LoggerAdapter that injects context into all log calls
    
    Example:
        logger = get_logger(__name__)
        logger.info("Processing query", extra={"query_id": query_id})
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    
    return LoggerAdapter(_loggers[name], {})


def shutdown_logging() -> None:
    """Shutdown logging (flushes async queue)."""
    global _queue_listener
    if _queue_listener:
        _queue_listener.stop()
        _queue_listener = None
```

### FastAPI Logging Middleware

```python
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import time
import uuid


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for logging HTTP requests and responses.
    
    Logs:
    - Request start with method, path, headers
    - Request completion with status, duration
    - Errors with exception details
    """
    
    def __init__(
        self,
        app: FastAPI,
        config: LoggingConfig,
    ):
        super().__init__(app)
        self.config = config
        self.logger = get_logger("http")
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        # Skip excluded paths
        if request.url.path in self.config.excluded_paths:
            return await call_next(request)
        
        # Generate request ID if not present
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        tenant_id = request.headers.get("x-tenant-id")
        user_id = request.headers.get("x-user-id")
        
        # Set context for logging
        set_request_context(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        
        # Log request start
        self.logger.info(
            "Request started",
            extra={
                "http": {
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.query_params),
                    "client_ip": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                },
            },
        )
        
        start_time = time.perf_counter()
        
        try:
            response = await call_next(request)
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            # Log request completion
            log_method = self.logger.warning if response.status_code >= 400 else self.logger.info
            log_method(
                "Request completed",
                extra={
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round(duration_ms, 2),
                    },
                },
            )
            
            # Add request ID to response headers
            response.headers["x-request-id"] = request_id
            
            return response
        
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            self.logger.error(
                "Request failed",
                extra={
                    "http": {
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round(duration_ms, 2),
                    },
                    "error": str(e),
                },
                exc_info=True,
            )
            raise
        
        finally:
            clear_request_context()


def setup_logging_middleware(
    app: FastAPI,
    config: LoggingConfig,
) -> None:
    """Set up logging middleware for FastAPI."""
    app.add_middleware(RequestLoggingMiddleware, config=config)
```

### Loki Configuration

```yaml
# loki-config.yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v12
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /loki/index
    cache_location: /loki/cache
    cache_ttl: 24h
  filesystem:
    directory: /loki/chunks

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  max_entries_limit_per_query: 5000
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32

chunk_store_config:
  max_look_back_period: 0s

table_manager:
  retention_deletes_enabled: true
  retention_period: 720h  # 30 days

ruler:
  alertmanager_url: http://alertmanager:9093
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /loki/rules-temp
  ring:
    kvstore:
      store: inmemory
  enable_api: true

analytics:
  reporting_enabled: false
```

```yaml
# promtail-config.yaml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    pipeline_stages:
      # Parse JSON logs
      - json:
          expressions:
            level: level
            message: message
            service: service.name
            trace_id: trace.trace_id
            span_id: trace.span_id
            tenant_id: tenant_id
            request_id: request_id
      
      # Set labels from JSON fields
      - labels:
          level:
          service:
          tenant_id:
      
      # Extract timestamp
      - timestamp:
          source: timestamp
          format: RFC3339Nano
      
      # Output message as log line
      - output:
          source: message
    
    relabel_configs:
      - source_labels:
          - __meta_kubernetes_pod_annotation_prometheus_io_scrape
        action: keep
        regex: true
      - source_labels:
          - __meta_kubernetes_pod_label_app
        target_label: app
      - source_labels:
          - __meta_kubernetes_namespace
        target_label: namespace
      - source_labels:
          - __meta_kubernetes_pod_name
        target_label: pod
      - source_labels:
          - __meta_kubernetes_pod_container_name
        target_label: container
```

### Kubernetes Deployment

```yaml
# loki.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: loki
  namespace: observability
spec:
  serviceName: loki
  replicas: 1
  selector:
    matchLabels:
      app: loki
  template:
    metadata:
      labels:
        app: loki
    spec:
      containers:
        - name: loki
          image: grafana/loki:2.9.3
          ports:
            - containerPort: 3100
              name: http
            - containerPort: 9096
              name: grpc
          args:
            - -config.file=/etc/loki/loki-config.yaml
          resources:
            requests:
              memory: 256Mi
              cpu: 100m
            limits:
              memory: 512Mi
              cpu: 500m
          volumeMounts:
            - name: config
              mountPath: /etc/loki
            - name: storage
              mountPath: /loki
          livenessProbe:
            httpGet:
              path: /ready
              port: 3100
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /ready
              port: 3100
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: config
          configMap:
            name: loki-config
  volumeClaimTemplates:
    - metadata:
        name: storage
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 50Gi
---
apiVersion: v1
kind: Service
metadata:
  name: loki
  namespace: observability
spec:
  selector:
    app: loki
  ports:
    - name: http
      port: 3100
      targetPort: 3100
    - name: grpc
      port: 9096
      targetPort: 9096
```

```yaml
# promtail.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: promtail
  namespace: observability
spec:
  selector:
    matchLabels:
      app: promtail
  template:
    metadata:
      labels:
        app: promtail
    spec:
      serviceAccountName: promtail
      containers:
        - name: promtail
          image: grafana/promtail:2.9.3
          args:
            - -config.file=/etc/promtail/promtail-config.yaml
          ports:
            - containerPort: 9080
              name: http
          resources:
            requests:
              memory: 128Mi
              cpu: 50m
            limits:
              memory: 256Mi
              cpu: 200m
          volumeMounts:
            - name: config
              mountPath: /etc/promtail
            - name: varlog
              mountPath: /var/log
              readOnly: true
            - name: varlibdockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: promtail-config
        - name: varlog
          hostPath:
            path: /var/log
        - name: varlibdockercontainers
          hostPath:
            path: /var/lib/docker/containers
```

## Unit Tests

```python
import pytest
import logging
import json
from unittest.mock import Mock, patch
from io import StringIO


@pytest.fixture
def logging_config():
    """Create test logging configuration."""
    return LoggingConfig(
        service_name="test-service",
        service_version="1.0.0",
        environment="test",
        level=LogLevel.DEBUG,
        json_format=True,
        include_trace_context=False,
    )


@pytest.fixture
def json_formatter(logging_config):
    """Create JSON formatter."""
    return JSONFormatter(
        service_name=logging_config.service_name,
        service_version=logging_config.service_version,
        environment=logging_config.environment,
        include_trace_context=False,
    )


def test_json_formatter_output(json_formatter):
    """Test JSON formatter produces valid JSON."""
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    
    output = json_formatter.format(record)
    parsed = json.loads(output)
    
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "Test message"
    assert parsed["service"]["name"] == "test-service"


def test_json_formatter_with_exception(json_formatter):
    """Test JSON formatter handles exceptions."""
    try:
        raise ValueError("Test error")
    except ValueError:
        import sys
        exc_info = sys.exc_info()
    
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=10,
        msg="Error occurred",
        args=(),
        exc_info=exc_info,
    )
    
    output = json_formatter.format(record)
    parsed = json.loads(output)
    
    assert "exception" in parsed
    assert parsed["exception"]["type"] == "ValueError"
    assert parsed["exception"]["message"] == "Test error"


def test_sensitive_data_filter():
    """Test sensitive data filter masks secrets."""
    filter = SensitiveDataFilter(
        sensitive_fields=["password", "api_key"],
        mask="[REDACTED]",
    )
    
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="User login with password=secret123",
        args=(),
        exc_info=None,
    )
    
    filter.filter(record)
    
    assert "secret123" not in record.msg
    assert "[REDACTED]" in record.msg or "password=[REDACTED]" in record.msg


def test_sensitive_data_filter_dict():
    """Test sensitive data filter masks dicts."""
    filter = SensitiveDataFilter(
        sensitive_fields=["password", "api_key"],
        mask="[REDACTED]",
    )
    
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Request data",
        args=(),
        exc_info=None,
    )
    record.data = {"username": "alice", "password": "secret123"}
    
    filter.filter(record)
    
    assert record.data["password"] == "[REDACTED]"
    assert record.data["username"] == "alice"


def test_context_injection():
    """Test context variables are injected."""
    set_request_context(
        request_id="req-123",
        tenant_id="tenant-abc",
        user_id="user-xyz",
    )
    
    filter = ContextInjectorFilter()
    
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test",
        args=(),
        exc_info=None,
    )
    
    filter.filter(record)
    
    assert record.request_id == "req-123"
    assert record.tenant_id == "tenant-abc"
    assert record.user_id == "user-xyz"
    
    clear_request_context()


def test_logger_adapter():
    """Test logger adapter adds context."""
    set_request_context(request_id="req-456")
    
    logger = get_logger("test")
    
    with patch.object(logger.logger, 'info') as mock_info:
        logger.info("Test message", extra={"custom": "value"})
        
        call_kwargs = mock_info.call_args[1]
        assert call_kwargs['extra']['request_id'] == "req-456"
        assert call_kwargs['extra']['custom'] == "value"
    
    clear_request_context()


def test_setup_logging(logging_config, capsys):
    """Test logging setup."""
    setup_logging(logging_config)
    
    logger = get_logger("test")
    logger.info("Test log message")
    
    # Allow async logging to process
    import time
    time.sleep(0.1)
    
    shutdown_logging()


def test_jwt_token_masking():
    """Test JWT tokens are masked."""
    filter = SensitiveDataFilter(
        sensitive_fields=[],
        mask="[REDACTED]",
    )
    
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        args=(),
        exc_info=None,
    )
    
    filter.filter(record)
    
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in record.msg
```

## Integration Tests

```python
@pytest.mark.integration
def test_logging_with_otel_trace():
    """Test logs include OpenTelemetry trace context."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer(__name__)
    
    config = LoggingConfig(
        service_name="integration-test",
        include_trace_context=True,
    )
    
    setup_logging(config)
    logger = get_logger("test")
    
    with tracer.start_as_current_span("test-span"):
        # Log within a span
        logger.info("Message with trace context")
    
    shutdown_logging()


@pytest.mark.integration
def test_loki_push():
    """Test logs can be pushed to Loki."""
    import requests
    
    log_entry = {
        "streams": [
            {
                "stream": {
                    "service": "test",
                    "level": "info"
                },
                "values": [
                    [str(int(time.time() * 1e9)), "Test log message"]
                ]
            }
        ]
    }
    
    response = requests.post(
        "http://localhost:3100/loki/api/v1/push",
        json=log_entry,
        headers={"Content-Type": "application/json"},
    )
    
    assert response.status_code == 204
```

## Dependencies

```
python-json-logger>=2.0.0  # Optional, for alternative formatter
```

## Definition of Done

- [ ] LoggingConfig with environment variable support
- [ ] JSONFormatter with service identification
- [ ] Trace context included in logs
- [ ] SensitiveDataFilter masks passwords, tokens, API keys
- [ ] JWT tokens detected and masked
- [ ] Context injection (request_id, tenant_id, user_id)
- [ ] LoggerAdapter for consistent context
- [ ] Async logging with QueueHandler/QueueListener
- [ ] FastAPI RequestLoggingMiddleware
- [ ] Request start/completion logging
- [ ] Error logging with stack traces
- [ ] Loki configuration for log aggregation
- [ ] Promtail configuration for Kubernetes
- [ ] Kubernetes deployment manifests
- [ ] Third-party library log levels reduced
- [ ] >90% test coverage
- [ ] Documentation complete
