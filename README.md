# QC-Studio

QC-Studio is a web-based quality control (QC) application for neuroimaging data. It gives raters a unified, portable interface (i.e. a web browser) to review raw imaging data, processed pipeline derivatives, and image quality metrics (IQMs), and export ratings as a tab-separated table. See [Why QC-Studio](docs/source/overview/why_qc-studio.md) for the motivation and vocabulary.

## 🎯 Goals

- Create an interactive web app to visualize neuroimaging data - raw and processed!
- Support multiple image types: 3D MRI (NIfTI), 2D image montages, and IQM metrics
- Enable structured quality control ratings through a clean, intuitive interface

## 📚 Documentation
https://qc-studio.readthedocs.io/en/latest/

## 📄 License

See the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please:

1. Read the [architecture.md](docs/source/development/architecture.md) for design patterns
2. Check [ui/tests/README.md](ui/tests/README.md) for testing practices
3. Set up the development tooling as described [here](docs/source/overview/installation.md#developer-setup)
4. Ensure all tests pass before submitting PR

Before pushing, run all pre-commit checks. This includes the same UI test command used in CI.

```bash
pre-commit run --all-files
```

## ❓ Support

For issues, questions, or suggestions open an issue on GitHub with detailed description
