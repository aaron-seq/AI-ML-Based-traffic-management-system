# Contributing to AI Traffic Management System

Thank you for your interest in contributing to the AI Traffic Management System. This document provides guidelines and instructions for contributing to make the process smooth and consistent.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Code Organization](#code-organization)
- [Coding Standards](#coding-standards)
- [Git Workflow](#git-workflow)
- [Testing Requirements](#testing-requirements)
- [Pull Request Process](#pull-request-process)
- [Security Guidelines](#security-guidelines)

## Code of Conduct

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before contributing.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Set up the development environment
4. Create a feature branch
5. Make your changes
6. Test thoroughly
7. Submit a Pull Request

## Development Setup

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Frontend Setup

```bash
cd frontend
npm install
```

### Environment Configuration

```bash
cp .env.example .env
# Edit .env with your local settings
```

## Code Organization

We follow a structured approach to code organization:

### Backend Structure

```
backend/
├── app/
│   ├── core/           # Configuration, logging, security, metrics
│   ├── models/         # Pydantic data models
│   ├── services/       # Business logic services
│   ├── middleware.py   # HTTP middleware
│   └── main.py         # Application entry point
├── tests/
│   ├── unit/           # Unit tests
│   ├── integration/    # Integration tests
│   └── conftest.py     # Test fixtures
```

### Code Categories

| Category   | Purpose                           | Location          |
|------------|-----------------------------------|-------------------|
| **Block**  | Business logic, algorithms        | `app/services/`   |
| **Helpers**| Project-specific utilities        | `app/core/`       |
| **Utils**  | Shared/reusable utilities         | `app/utils/`      |

## Coding Standards

### Python Guidelines

1. **PEP 8 Compliance**: Follow PEP 8 style guide
2. **Type Hints**: Use type hints for all function signatures
3. **Docstrings**: Write docstrings for all public functions and classes
4. **Line Length**: Maximum 88 characters (Black formatter default)

### Error Handling

```python
# CORRECT: Handle errors explicitly with logging
try:
    result = await some_operation()
except SomeException as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Operation failed")

# INCORRECT: Never silently fail
try:
    result = await some_operation()
except:
    pass  # DO NOT DO THIS
```

### Comments

Write comments that explain **why**, not just **what**:

```python
# GOOD: Explains reasoning
# Using batch size of 32 to balance memory usage and throughput
# based on benchmarks with YOLOv8n model
BATCH_SIZE = 32

# BAD: Just restates the code
# Set batch size to 32
BATCH_SIZE = 32
```

### SOLID Principles

- **Single Responsibility**: Each class/function should have one purpose
- **Open/Closed**: Open for extension, closed for modification
- **Liskov Substitution**: Subtypes must be substitutable for base types
- **Interface Segregation**: Many specific interfaces over one general
- **Dependency Inversion**: Depend on abstractions, not concretions

## Git Workflow

### Branch Naming

| Type      | Format                          | Example                        |
|-----------|---------------------------------|--------------------------------|
| Feature   | `feature/description`           | `feature/add-emergency-alerts` |
| Bug Fix   | `fix/description`               | `fix/detection-timeout`        |
| Hotfix    | `hotfix/description`            | `hotfix/critical-security`     |
| Docs      | `docs/description`              | `docs/api-documentation`       |
| Refactor  | `refactor/description`          | `refactor/service-layer`       |

### Commit Messages

Follow the conventional commits format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

**Examples**:
```
feat(detection): add emergency vehicle detection algorithm
fix(api): resolve timeout issue in vehicle detection endpoint
docs(readme): update installation instructions
test(services): add unit tests for traffic manager
```

## Testing Requirements

### Before Submitting PR

1. **All tests must pass**:
   ```bash
   cd backend
   python -m pytest tests/ -v
   ```

2. **Code coverage minimum 80%**:
   ```bash
   python -m pytest tests/ --cov=app --cov-report=term-missing
   ```

3. **Linting passes**:
   ```bash
   python -m flake8 app/
   python -m black --check app/
   python -m isort --check-only app/
   ```

4. **Type checking**:
   ```bash
   python -m mypy app/ --ignore-missing-imports
   ```

### Test Categories

| Marker        | Description                    | When to Run              |
|---------------|--------------------------------|--------------------------|
| (default)     | Unit tests                     | Always before commit     |
| `integration` | Requires external services     | Before PR, in CI         |
| `slow`        | Performance/load tests         | Weekly, before release   |

## Pull Request Process

### Checklist

Before submitting, ensure:

- [ ] Code follows the style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] Documentation updated if needed
- [ ] Tests added/updated
- [ ] All tests passing
- [ ] No new linting errors

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe testing performed

## Related Issues
Closes #issue_number
```

### Review Process

1. Submit PR against `develop` branch
2. Automated CI checks run
3. At least one maintainer review required
4. Address feedback and update
5. Squash and merge when approved

## Security Guidelines

### Sensitive Data

- Never commit secrets, API keys, or passwords
- Use environment variables for sensitive configuration
- Review `.gitignore` before committing

### Input Validation

- Always validate and sanitize user inputs
- Use Pydantic models for request validation
- Apply rate limiting to sensitive endpoints

### Dependencies

- Keep dependencies updated
- Review security advisories regularly
- Run `safety check` before releases

## Questions?

- Open an issue for questions
- Email: aaronsequeira12@gmail.com
- Discussions: GitHub Discussions

---

Thank you for contributing to make traffic management smarter and safer.
