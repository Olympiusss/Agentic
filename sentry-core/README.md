# Sentry Agentic Core

Shared core library for Sentry Agentic AI SOC projects.

## Overview

`sentry-core` provides common functionality used across Sentry Agentic projects:

- **Configuration Management**: Centralized configuration with file and environment support
- **Database Layer**: SQLAlchemy models and services for PostgreSQL
- **Secrets Management**: Secure secrets storage with multiple backends
- **Rate Limiting**: Token bucket and rate limiter implementations
- **Exception Handling**: Common exception types

## Installation

```bash
# Install from source (development)
pip install -e .

# Install from git
pip install git+https://github.com/YOUR_USERNAME/sentry-core.git
```

## Usage

```python
# Configuration
from sentry_core.config import get_config_dir, is_demo_mode

# Database
from sentry_core.database.models import Finding, Case
from sentry_core.database.service import DatabaseService
from sentry_core.database.connection import get_db_manager

# Secrets
from sentry_core.secrets import get_secrets_manager

# Rate Limiting
from sentry_core.rate_limit import RateLimiter, get_limiter
```

## Configuration

The library uses `~/.sentry/` for configuration files:

- `integrations_config.json` - Integration settings
- `general_config.json` - General configuration
- `.env` - Secrets (if using file backend)

## Database

Set the database connection via environment variable:

```bash
export DATABASE_URL=postgresql://user:pass@localhost:5432/sentry_soc
```

Or use the `POSTGRES_*` environment variables:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=sentry_soc
export POSTGRES_USER=sentry
export POSTGRES_PASSWORD=your_password
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black sentry_core/
ruff check sentry_core/
```

## License

MIT License - see LICENSE file for details.

