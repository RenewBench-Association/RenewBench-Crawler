# Contributing to RenewBench Crawlers

Welcome to the RenewBench Crawlers repository :sun_with_face:! We're thrilled that you're interested in contributing
to our open-source project :fire:.
By participating, you can help improve the project and make it even better :raised_hands:.

## How to Contribute

1. **Fork the Repository**: Click the "Fork" button at the top right corner of this repository's page to create your own copy.

2. **Clone Your Fork**: Clone your forked repository to your local machine using Git :octocat::
   ```bash
   git clone https://github.com/RenewBench-Association/RenewBench-Crawler
   ```

3. **Install the Package with Development Options** in a separate virtual environment from the main branch of your repo.
   In addition, install the [pre-commit hooks](https://pre-commit.com/) for code linting and formatting with [Ruff](https://github.com/astral-sh/ruff), ensuring PEP-8 conformity
   and overall good code quality consistently. The commands shown below work on Unix-based systems:
   ```bash
   python3 -m venv <insert/path/to/your/venv>
   source <insert/path/to/your/venv/bin/activate>
   python -m pip install -e ".[dev]"
   pre-commit install
   ```
   Now `pre-commit` will run automatically on `git commit`! You can also run the hooks manually:
   ```bash
   pre-commit run --all-files
   ```

4. **Create a Branch**: Create a new branch for your contribution. Choose a descriptive name. Depending on what you want
   to work on, prepend either of the following prefixes, `features`, `maintenance`, `bugfix`, or `hotfix`. Example:
   ```bash
   git checkout -b features/your-feature-name
   ```

5. **Make Changes**: Make your desired changes to the codebase. Please stick to the following guidelines:
   * `rcb` uses [Black](https://black.readthedocs.io/en/stable/the_black_code_style/current_style.html) code style and so should you if you would like to contribute.
   * Please use subscriptable lower-case type hints in all function definitions when possible.
   * Please use American English for all comments and docstrings in the code.
   * In the future, `rcp` will use [pdoc](https://pdoc.dev) to automatically create API reference documentation from docstrings in the code.
     Please use the [Google Docstring Standard](https://google.github.io/styleguide/pyguide.html) (see Section 3.8) for your docstrings.
     A small example of this format is below, but please refer to the official guidelines above for detailed information:

     ```python
     def defined_function(param1: type, param2: type = default) -> type:
         """Short Description.

         Long Description (if needed).

         Args:
            param1 (type): Description of param1.
            param2 (type, optional): Description of param2. Defaults to default.

         Returns:
            type: Description of return value.

         Raises:
            ExceptionType: Description of when and why this exception might be raised.

         Example:
            You can include examples in this section if required.
         """
     ```

      When defining classes, make sure to include the attributes as shown below:

        ```python
        class DefinedClass:
            """Summary of class here.

            Detailed class description (if needed).

            Attributes:
                attribute1 (type): Description of attribute 1.
                attribute2 (type): Description of attribute 2.
            """

            def __init__(self, attribute1: type) -> None:
                """Initializes the instance based on ...

                Args:
                  attribute1 (type): Description of attribute 1.
                """
                self.attribute1 = attribute1
                self.attribute2 = ...
        ```

      You can find further examples of the Google Docstring Standard [here](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html).

6. **Test Changes**: Test all existing and added functionality.
    * ``rcb`` uses ``pytest`` for running the test suite. If you followed all of the above steps correctly, you already have the project and all dependencies installed. All of our tests are located in the ``tests/`` directory. Please also add your tests into the ``tests/`` directory.
    * To run all tests execute:
        ```bash
        pytest tests/
        ```
    * To run the tests with coverage:
        ```bash
        pytest --cov=rbc tests/
        ```

7. **Commit Changes**: Commit your changes with a clear and concise commit message that describes what you have changed.
   Example:
   ```bash
   git commit -m "add checkpoint for entsoe downloader"
   ```

8. **Push Changes**: Push your changes to your fork on GitHub:
   ```bash
   git push origin features/your-feature-name
   ```

9. **Open a Pull Request**: Go to the [original repository](https://github.com/RenewBench-Association/RenewBench-Crawler) and click the "New Pull Request" button. Follow the guidelines in the template to submit your pull request. Resolve possible merge conflicts with the current main branch.

## Code of Conduct

Please note that we have a [Code of Conduct](CODE_OF_CONDUCT.md), and we expect all contributors to follow it. Be kind and respectful to one another :blue_heart:.

## Questions or Issues

If you have questions or encounter any issues, please create an issue in the [Issues](https://github.com/RenewBench-Association/RenewBench-Crawler/issues) section of this repository.

Thank you for your contribution :pray:!
