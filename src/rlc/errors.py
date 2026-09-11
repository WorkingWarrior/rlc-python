from .common import Location


class RLCError(Exception):
    def __init__(self, message: str, location: Location | None = None):
        super().__init__(message)
        self.message = message
        self.location = location

    def __str__(self) -> str:
        if self.location:
            return f"{self.location}: {self.message}"
        return self.message


class PreprocessorError(RLCError):
    """Base class for preprocessor errors."""

    pass


class FileNotFoundErrorPreprocessor(PreprocessorError):
    """Raised when an included file is not found."""

    def __init__(self, filepath: str, directive_location: Location | None = None):
        super().__init__(f"File not found during preprocessing: '{filepath}'", directive_location)
        self.filepath = filepath


class RecursiveIncludeError(PreprocessorError):
    """Raised when a recursive include is detected."""

    def __init__(self, filepath: str, directive_location: Location | None = None):
        super().__init__(f"Recursive include detected for file: '{filepath}'", directive_location)
        self.filepath = filepath
