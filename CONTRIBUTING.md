# Contributing to SPARC

Thank you for your interest in contributing to SPARC! This document provides guidelines for contributing to the project.

## Branching Strategy

This project follows a two-branch workflow:

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases only. Every merge is tagged (e.g. `v0.2.0`). |
| `dev`  | Integration branch. All feature work lands here first. |

### Workflow

1. Create a feature branch from `dev`:
   ```bash
   git checkout dev
   git checkout -b my-feature
   ```
2. Do your work, commit, and push the feature branch.
3. Open a pull request targeting `dev`.
4. After review and CI passes, merge into `dev`.
5. When `dev` is ready for release, it gets merged into `main` and tagged.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/geduardo/SPARC.git
cd SPARC

# Install in development mode with dev dependencies
pip install -e ".[dev,visualization]"

# Run tests
pytest

# Format code
black src/ tests/

# Check code style
flake8 src/ tests/
```

## Code Style

- We use [Black](https://github.com/psf/black) for code formatting
- Follow PEP 8 guidelines
- Add type hints where appropriate
- Write docstrings for all public functions and classes

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Aim for good test coverage

## Pull Request Process

1. Update the README.md with details of changes if needed
2. Update the documentation if you're changing functionality
3. Ensure your code passes all tests and linting checks
4. Create a descriptive pull request explaining your changes
5. Wait for review and address any feedback

## Reporting Issues

- Use the GitHub issue tracker
- Provide a clear description of the issue
- Include steps to reproduce if it's a bug
- Add relevant labels

## Code of Conduct

Please be respectful and considerate in all interactions. We aim to maintain a welcoming and inclusive environment for all contributors.

## Questions?

Feel free to open an issue for any questions about contributing! 