# QC-Studio UI Test Suite

This directory contains comprehensive test coverage for the QC-Studio UI components, including `ui.py` and `layout.py`.

## Test Structure

```
tests/
├── __init__.py              # Package marker
├── conftest.py              # Pytest fixtures and configuration
├── pytest.ini               # Pytest configuration file
├── test_models.py           # Tests for Pydantic models
├── test_utils.py            # Tests for utility functions
├── test_ui.py               # Tests for ui.py module
├── test_layout.py           # Tests for layout.py module
└── README.md                # This file
```

## Test Coverage

### `test_models.py`
Tests for data models and validation:
- **MetricQC**: Metric quality control model
  - Field validation
  - Optional fields
  - Serialization

- **QCRecord**: Quality control record model
  - Required fields validation
  - Optional fields (task_id, run_id)
  - JSON serialization

- **QCTask**: QC configuration task model
  - Path field handling
  - Type conversion

- **QCConfig**: Top-level QC configuration model
  - JSON parsing
  - Task access
  - Serialization

### `test_utils.py`
Tests for utility functions:
- **parse_qc_config()**: Parse QC JSON configuration
  - Valid configuration parsing
  - Non-existent tasks
  - Invalid files and malformed JSON

- **load_mri_data()**: Load MRI image files
  - Load both base and overlay images
  - Load single image
  - Handle non-existent files

- **load_montage_data()**: Load 2D montage image files
  - Load valid SVG, PNG, and JPG/JPEG files
  - Handle non-existent files
  - Handle read errors

- **load_iqm_data()**: Load IQM JSON files
  - Parse valid IQM data
  - Handle malformed JSON
  - Handle missing files

- **save_qc_results_to_csv()**: Save QC results
  - Save records to CSV/TSV
  - Handle empty records
  - Duplicate removal

### `test_ui.py`
Tests for ui.py module:
- **parse_args()**: Command-line argument parsing
  - All required arguments
  - Default values (session_list)
  - Missing argument validation

- **Session State**: Initialization and management
  - Default values
  - Session keys
  - Page bounds

- **Participant List**: Loading and navigation
  - Load from TSV
  - Calculate total participants
  - Retrieve participant IDs

### `test_layout.py`
Tests for layout.py module:
- **show_landing_page()**: Landing page display
  - Title display
  - Pipeline info
  - Error handling
  - Three-column layout

- **Rater Information**: Rater details form
  - Form display
  - Experience level options
  - Fatigue level options

- **Panel Selection**: Display panel selection
  - Checkbox display
  - Default selections
  - Validation (at least one panel)

- **CSV Upload**: File upload functionality
  - Upload display
  - CSV validation
  - Participant validation

- **Main App**: App initialization and navigation
  - Landing page when incomplete
  - Congratulations page
  - Navigation controls

## Installation

### Install Test Dependencies

```bash
pip install -r requirements-test.txt
```

Or add to your existing requirements:

```bash
pytest>=7.0
pytest-mock>=3.10
pytest-cov>=4.0
```

## Running Tests

### Run All Tests
```bash
pytest ui/tests/
```

### Run Specific Test File
```bash
pytest ui/tests/test_models.py
```

### Run Specific Test Class
```bash
pytest ui/tests/test_utils.py::TestParseQcConfig
```

### Run Specific Test
```bash
pytest ui/tests/test_utils.py::TestParseQcConfig::test_parse_valid_qc_config
```

### Run with Coverage Report
```bash
pytest ui/tests/ --cov=ui --cov-report=html
```

### Run Only Unit Tests
```bash
pytest ui/tests/ -m unit
```

### Run with Verbose Output
```bash
pytest ui/tests/ -v
```

### Run with Short Summary
```bash
pytest ui/tests/ -q
```

## Test Fixtures

The `conftest.py` file provides shared fixtures for all tests:

### File Fixtures
- **`temp_dir`**: Temporary directory for test files
- **`sample_participant_list`**: Sample participants TSV file
- **`sample_qc_config`**: Sample QC configuration JSON
- **`sample_qc_results_csv`**: Sample QC results CSV file
- **`sample_svg_content`**: Sample SVG content string used in montage image tests

### Data Fixtures
- **`sample_session_state`**: Mock Streamlit session state
- **`qc_record_sample`**: Sample QCRecord object
- **`mock_streamlit`**: Mock Streamlit module

### Usage Example
```python
def test_something(sample_participant_list, temp_dir):
    """Use fixtures in your test."""
    # sample_participant_list is already created
    df = pd.read_csv(sample_participant_list, delimiter="\t")
    assert len(df) > 0
```

## Mocking Streamlit

Since Streamlit is a reactive framework, tests use mocking extensively:

```python
from unittest.mock import patch, MagicMock

@patch('layout.st')
def test_something(mock_st):
    """Mock Streamlit functions."""
    mock_st.session_state = {}
    mock_st.columns.return_value = (MagicMock(), MagicMock())
    
    # Your test code here
```

## Test Guidelines

### Writing New Tests

1. **Follow naming conventions**:
   - Test files: `test_*.py`
   - Test classes: `Test*`
   - Test methods: `test_*`

2. **Use descriptive names**:
   ```python
   def test_parse_qc_config_with_valid_file_and_existing_task(self):
       """Test parsing valid QC config with existing task."""
   ```

3. **Arrange, Act, Assert pattern**:
   ```python
   def test_something(self):
       # Arrange
       test_data = create_test_data()
       
       # Act
       result = function_to_test(test_data)
       
       # Assert
       assert result == expected_value
   ```

4. **Use fixtures for setup**:
   ```python
   def test_something(self, sample_participant_list):
       # Reuse fixture instead of creating test data
       df = pd.read_csv(sample_participant_list, delimiter="\t")
   ```

5. **Mock external dependencies**:
   ```python
   @patch('module.external_function')
   def test_something(mock_external):
       mock_external.return_value = test_value
   ```

## Coverage Goals

Current test coverage targets:
- **Models**: 95%+ (Pydantic validation)
- **Utils**: 90%+ (File I/O, parsing)
- **UI**: 85%+ (Streamlit mocking limitations)
- **Layout**: 80%+ (Complex Streamlit interactions)

Check coverage:
```bash
pytest ui/tests/ --cov=ui --cov-report=term-missing
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run Tests
  run: pytest ui/tests/ --cov=ui --cov-report=xml

- name: Upload Coverage
  uses: codecov/codecov-action@v3
  with:
    files: ./coverage.xml
```

## Troubleshooting

### ImportError: No module named 'streamlit'
The tests mock Streamlit, but if you get import errors:
```bash
pip install streamlit
```

### Tests fail due to missing fixtures
Ensure `conftest.py` is in the tests directory and pytest can find it.

### Pydantic validation errors in tests
Make sure Pydantic v2+ is installed:
```bash
pip install "pydantic>=2.0"
```

### Mocking issues
If mocking isn't working correctly:
1. Check the patch path matches the import in the module
2. Ensure mocks are applied before function calls
3. Use `autospec=True` for more strict mocking

## Contributing

When adding new features:
1. Write tests first (TDD approach)
2. Ensure tests pass
3. Check coverage with `--cov`
4. Run full test suite before committing
5. Update this README with new test descriptions

## References

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-mock Documentation](https://pytest-mock.readthedocs.io/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Streamlit Testing Documentation](https://docs.streamlit.io/library/advanced-features/logger)
