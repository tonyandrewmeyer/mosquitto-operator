# Contributing to Mosquitto Charm

Thank you for your interest in contributing to the Mosquitto charm! This document provides guidelines and information for contributors.

## Getting Started

### Prerequisites

- Python 3.10 or later
- Juju 3.0 or later
- Charmcraft
- Git

### Development Environment Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/mosquitto-operator.git
   cd mosquitto-operator
   ```

2. **Set up Python environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install tox pre-commit
   ```

3. **Install development dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set up pre-commit hooks**
   ```bash
   pre-commit install
   ```

5. **Verify setup**
   ```bash
   tox -e lint
   tox -e unit
   ```

## Development Workflow

### Code Style and Quality

This project uses several tools to maintain code quality:

- **Ruff**: For linting and formatting Python code
- **MyPy**: For static type checking
- **Pre-commit**: For automated checks before commits

Run quality checks locally:

```bash
# Format code
tox -e format

# Run linting and type checking
tox -e lint

# Run all checks that pre-commit would run
pre-commit run --all-files
```

### Testing

We maintain comprehensive test coverage with three types of tests:

#### Unit Tests
```bash
# Run unit tests
tox -e unit

# Run with coverage report
tox -e unit -- --cov-report=html
```

#### Integration Tests
```bash
# Run integration tests (requires Juju controller)
tox -e integration
```

#### Charm Building and Linting
```bash
# Build the charm
charmcraft pack

# Lint the charm
charmcraft lint
```

### Making Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Follow existing code patterns and conventions
   - Add tests for new functionality
   - Update documentation as needed
   - Keep commits focused and atomic

3. **Test your changes**
   ```bash
   tox -e format  # Format code
   tox -e lint    # Check linting
   tox -e unit    # Run unit tests
   ```

4. **Commit your changes**
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

   Use [Conventional Commits](https://www.conventionalcommits.org/) format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `docs:` for documentation changes
   - `test:` for test-related changes
   - `refactor:` for code refactoring
   - `ci:` for CI/CD changes

5. **Push and create a pull request**
   ```bash
   git push origin feature/your-feature-name
   ```

## Contributing Guidelines

### Code Standards

- **Python Version**: Target Python 3.10+ compatibility
- **Type Hints**: Use type hints for all function parameters and return values
- **Error Handling**: Use specific exception types, avoid catching `Exception`
- **Logging**: Use appropriate log levels and include context
- **Documentation**: Update docstrings and comments for new functionality

### Charm-Specific Guidelines

- **Configuration**: Validate all configuration options in the charm
- **Status Management**: Use appropriate Juju status indicators
- **Event Handling**: Keep event handlers focused and delegate to workload methods
- **Testing**: Write unit tests using `ops.testing` framework
- **Relations**: Implement relations following Juju interface specifications

### Documentation

- Update `README.md` for user-facing changes
- Update `TUTORIAL.md` if workflow changes
- Add docstrings to new functions and classes
- Update `CHANGELOG.md` with notable changes

### Security

- Follow security best practices
- Never commit secrets or credentials
- Validate user inputs and configuration
- Use secure defaults
- Report security issues via the process in `SECURITY.md`

## Pull Request Process

### Before Submitting

- [ ] Code follows the project's style guidelines
- [ ] Tests pass locally (`tox -e lint`, `tox -e unit`)
- [ ] Documentation updated if needed
- [ ] Changelog updated for notable changes
- [ ] Commits use conventional commit format

### PR Description Template

```markdown
## Description
Brief description of the changes

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing performed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review of code completed
- [ ] Documentation updated
- [ ] Changes generate no new warnings
```

### Review Process

1. **Automated Checks**: CI pipeline runs automatically
2. **Code Review**: Maintainers review code for:
   - Functionality and correctness
   - Code quality and style
   - Test coverage
   - Documentation completeness
3. **Testing**: Integration tests run in CI
4. **Approval**: At least one maintainer approval required
5. **Merge**: Squash and merge to main branch

## Issue Reporting

### Bug Reports

When reporting bugs, please include:

- **Environment**: Juju version, Ubuntu version, charm version
- **Steps to Reproduce**: Clear, step-by-step instructions
- **Expected Behavior**: What should have happened
- **Actual Behavior**: What actually happened
- **Logs**: Relevant log output (`juju debug-log`)
- **Configuration**: Charm configuration (`juju config mosquitto`)

### Feature Requests

For feature requests, please include:

- **Use Case**: Why is this feature needed?
- **Proposed Solution**: How should it work?
- **Alternatives**: Other approaches considered
- **Impact**: Who would benefit from this feature?

## Release Process

### Versioning

We follow [Semantic Versioning](https://semver.org/):
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

### Changelog Management

- Keep `CHANGELOG.md` updated with notable changes
- Use `[Unreleased]` section for upcoming changes
- Move changes to versioned sections on release
- Follow [Keep a Changelog](https://keepachangelog.com/) format

## Community

### Communication

- **Issues**: Use GitHub issues for bugs and feature requests
- **Discussions**: Use GitHub discussions for questions and ideas
- **Code of Conduct**: Follow our [Code of Conduct](CODE_OF_CONDUCT.md)

### Recognition

Contributors will be recognized in:
- Release notes for significant contributions
- README.md contributors section
- Git commit history

## Additional Resources

- [Juju Documentation](https://juju.is/docs)
- [Ops Framework Reference](https://ops.readthedocs.io/)
- [Charmcraft Documentation](https://juju.is/docs/sdk/charmcraft)
- [MQTT Specification](https://mqtt.org/)
- [Eclipse Mosquitto](https://mosquitto.org/)

## Getting Help

If you need help with development:

1. Check existing issues and documentation
2. Ask questions in GitHub discussions
3. Review the tutorial and examples
4. Contact maintainers via GitHub

Thank you for contributing to the Mosquitto charm!