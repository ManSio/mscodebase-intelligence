# Contributing

Thanks for your interest in contributing to MSCodebase Intelligence! This document outlines the contribution guidelines to help you get started.

## 🎯 Getting Started

### Prerequisites

- **Python 3.10+**
- **LM Studio** with running embedding server on port 1234
- **Zed IDE** (for testing)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/ManSio/mscodebase-intelligence.git
cd mscodebase-intelligence

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 📋 Code Quality Standards

### Linting and Formatting

We use standard Python conventions with some project-specific adjustments:

- **Line length**: 88 characters (Black default)
- **Import order**: isort
- **Code style**: Black
- **Type hints**: Required for public APIs

### Testing

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_searcher.py

# Run with coverage
pytest --cov=src --cov-report=html
```

### Commit Message Guidelines

Follow these conventions for commit messages:

- **Subject line**: Start with imperative, keep under 50 characters
- **Body**: Explain what and why, wrap at 72 characters
- **Scope**: Use scope in parentheses for specific components
- **Examples**:
  - `feat(searcher): add BM25 hybrid search implementation`
  - `fix(indexer): handle empty embeddings from LM Studio`
  - `docs: update README with architecture diagram`

## 🔧 Development Workflow

### 1. Branching Strategy

- **Main**: Production-ready code
- **Development**: Current development work
- **Feature branches**: For specific features/bugs
- **Feature/xxx**: Feature branches named after GitHub issue

### 2. Pull Request Process

1. **Create branch** from `development`
2. **Make changes** following code standards
3. **Run tests** locally
4. **Create pull request** with description
5. **Request reviews** from maintainers
6. **Address feedback** and update PR
7. **Merge** after approval

### 3. Local Testing

Before submitting changes, ensure:

```bash
# Test the specific component
pytest tests/test_searcher.py -v

# Test integration
pytest tests/test_integration.py -v

# Check for any linting issues
black --check src/
isort --check-only src/
```

## 🚀 Feature Requests

### New Features

1. **Open an issue** with clear description
2. **Discuss** in comments if needed
3. **Create PR** with implementation
4. **Update documentation** accordingly

### Bug Reports

1. **Reproduce** the issue locally
2. **Create issue** with:
   - Clear steps to reproduce
   - Expected vs actual behavior
   - Log output if applicable
3. **Test fix** before submitting PR

## 📚 Documentation

### Writing Documentation

- Use Markdown for all documentation
- Follow existing style and formatting
- Include examples where helpful
- Update API documentation for new features

### Updating README

- Keep examples up-to-date
- Update installation instructions
- Add new features to "Capabilities" section
- Update architecture diagrams when needed

## 🏷️ Versioning

We use semantic versioning (SemVer):

- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

## 🤝 Community Guidelines

### Code of Conduct

Please behave professionally and respectfully in all interactions. We follow the open-source community code of conduct.

### Communication

- Use clear, respectful language
- Provide constructive feedback
- Be patient with contributors new to the project
- Focus on code and technical issues

## 🔄 Updating Dependencies

### Python Dependencies

```bash
# Update requirements.txt from pyproject.toml
pip install -r requirements.txt

# Update pyproject.toml dependencies
# Edit pyproject.toml directly, then:
pip install -e .
```

### Third-Party Libraries

When updating external dependencies:

1. **Check compatibility** with existing code
2. **Run full test suite** after updates
3. **Update CHANGELOG.md**
4. **Consider semantic versioning** impact

## 📝 License

By contributing, you agree that your contributions will be licensed under the MIT License.

## 🙏 Acknowledgments

Special thanks to all contributors who have helped make this project better!

---

*Last updated: 2026-06-24*

## 📬 Contact

For questions or issues not covered here:

- **GitHub Issues**: [ManSio/mscodebase-intelligence](https://github.com/ManSio/mscodebase-intelligence/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ManSio/mscodebase-intelligence/discussions)