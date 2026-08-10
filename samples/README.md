# Samples Directory

Place your PDF documents here for testing and validation.

## Required for Integration Tests

The integration tests (`tests/integration/`) require:

```
samples/
└── test_poliza.pdf    ← Place any valid PDF here
```

Any PDF will work. Ideally use a real póliza de seguros or condiciones generales.

## Suggested Test Files

| File | Purpose |
|------|---------|
| `test_poliza.pdf` | Primary integration test document |
| `test_condiciones.pdf` | Test with complex multi-section layout |
| `test_tablas.pdf` | Test with complex table structures |
| `test_multicolumna.pdf` | Test with multi-column layout |

## Why Not Include Sample PDFs?

Sample insurance documents may contain proprietary or personal information.
Place your own documents here for testing.

## Quick Test

Once you have a PDF in this folder, run:

```bash
# Unit tests (no PDF needed)
pytest tests/unit/ -v

# Integration tests (requires test_poliza.pdf)
pytest tests/integration/ -v -m integration
```

Or use the CLI directly:

```bash
python main.py extract samples/test_poliza.pdf
```
