# Contributing to URL Probe

This document provides guidelines and steps for contributing.

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Poetry (Python package manager)

### Installing

1. Fork the repository and clone your fork:
```bash
# Using SSH (recommended)
git clone git@github.com:your-username/urlprobe.git

# OR using HTTPS
git clone https://github.com/your-username/urlprobe.git

cd urlprobe
```

2. Install dependencies with Poetry:
```bash
poetry install
```

3. Install pre-commit hooks:
```bash
poetry run pre-commit install
```

### Starting the Server

Basic usage:
```bash
poetry run urlprobe
```

The server will start with default settings:
- Host: 127.0.0.1 (localhost only)
- Port: 8080
- Debug mode: off

### Custom Configuration

You can customize the server settings:

```bash
# Run on a different port
poetry run urlprobe --port 8080

# Make accessible from other machines
poetry run urlprobe --host 0.0.0.0

# Enable debug mode (auto-reload on code changes)
poetry run urlprobe --debug

# Combine options
poetry run urlprobe --host 0.0.0.0 --port 8080 --debug
```

### Editor Configuration

The project includes an `.editorconfig` file to maintain consistent coding styles:
- UTF-8 encoding
- Unix-style line endings
- 4 spaces for Python indentation
- 79 character line length for Python files
- 2 spaces for YAML files

## Code Style

This project uses several tools to maintain code quality:
- Black for code formatting
- isort for import sorting
- flake8 for linting with PEP 8 standards
- pre-commit hooks for automated checks

To run all checks manually:
```bash
poetry run pre-commit run --all-files
```

## Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage report
poetry run pytest --cov=src/
```

## Managing Lock File

1. Update lock file without installing packages:
```bash
poetry lock --no-update
```

2. Update lock file and install packages:
```bash
poetry lock
```

3. Check if lock file is up to date with pyproject.toml:
```bash
poetry lock --check
```

4. Force update lock file (if you're having issues):
```bash
poetry lock --no-cache
```

Note: The lock file (`poetry.lock`) ensures that all developers use the exact same package versions. Always commit this file to version control.

## Making Changes

1. Create a new branch:
```bash
git checkout -b feature-or-fix-name
```

2. Make your changes and ensure all tests pass:
```bash
poetry run pytest
```

3. Commit your changes:
```bash
git add .
git commit -m "Description of changes"
```

Your commit will automatically trigger pre-commit hooks to check code quality.

4. Push to your fork:
```bash
git push origin feature-or-fix-name
```

5. Open a Pull Request on GitHub

## Pull Request Guidelines

- Fill in the provided PR template
- Include tests for new features
- Update documentation as needed
- Ensure all checks pass
- Keep PRs focused - one feature or fix per PR

## Getting Help

If you have questions or need help:
1. Check existing issues
2. Open a new issue
3. Reach out to maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License. See the [LICENSE](LICENSE) file for full details.
