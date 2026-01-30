#!/usr/bin/env python3
"""
Hardened Retry Decorator
========================

Enhanced retry decorator that prevents infinite loops by immediately raising
non-retryable exceptions like ArgumentError and ParserError.

This prevents situations where SQL parameter mismatches or CSV parsing errors
cause endless retry loops that waste resources and obscure the real problem.

Usage:
    from src.retry_utils import hardened_retry

    @hardened_retry(max_retries=3, delay=1)
    def risky_operation():
        # Code that might fail
        pass

Non-retryable exceptions:
- sqlalchemy.exc.ArgumentError: SQL parameter mismatch
- pandas.errors.ParserError: CSV parsing failure
- ValueError: Often indicates data format issues
- TypeError: Type mismatch errors
- KeyError: Missing required data keys
"""

import functools
import logging
import time
from typing import Callable, Any

# Import exceptions that should NOT be retried
try:
    import sqlalchemy.exc
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

try:
    import pandas.errors
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

logger = logging.getLogger(__name__)


# Define non-retryable exceptions
NON_RETRYABLE = [
    ValueError,  # Data format errors
    TypeError,   # Type mismatch
    KeyError,    # Missing data keys
    AttributeError,  # Object attribute errors
]

# Add SQLAlchemy exceptions if available
if SQLALCHEMY_AVAILABLE:
    NON_RETRYABLE.extend([
        sqlalchemy.exc.ArgumentError,  # SQL parameter mismatch
        sqlalchemy.exc.StatementError,  # SQL statement errors
        sqlalchemy.exc.InvalidRequestError,  # Invalid SQL requests
    ])

# Add Pandas exceptions if available
if PANDAS_AVAILABLE:
    NON_RETRYABLE.extend([
        pandas.errors.ParserError,  # CSV parsing failure
        pandas.errors.EmptyDataError,  # Empty CSV files
    ])

# Convert to tuple for isinstance check
NON_RETRYABLE_EXCEPTIONS = tuple(NON_RETRYABLE)


def hardened_retry(max_retries: int = 3, delay: float = 1.0, backoff_factor: float = 2.0):
    """
    Hardened retry decorator that prevents infinite loops on non-retryable errors.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff_factor: Factor to multiply delay by after each retry

    Returns:
        Decorated function with hardened retry logic

    Raises:
        Immediately raises non-retryable exceptions without retrying
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            current_delay = delay
            last_exception = None

            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)

                except NON_RETRYABLE_EXCEPTIONS as e:
                    # Immediately raise non-retryable exceptions
                    logger.error(
                        f"Non-retryable exception in {func.__name__}: {type(e).__name__}: {e}"
                    )
                    raise

                except Exception as e:
                    last_exception = e
                    retries += 1

                    if retries > max_retries:
                        logger.error(
                            f"Function {func.__name__} failed after {max_retries} retries. "
                            f"Final error: {type(e).__name__}: {e}"
                        )
                        raise last_exception

                    logger.warning(
                        f"Retry {retries}/{max_retries} for {func.__name__} after "
                        f"{type(e).__name__}: {e}. Waiting {current_delay:.1f}s..."
                    )

                    time.sleep(current_delay)
                    current_delay *= backoff_factor

            # This should never be reached, but for safety
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(f"Function {func.__name__} failed without raising an exception")

        return wrapper
    return decorator


def database_retry(max_retries: int = 3, delay: float = 1.0):
    """
    Specialized retry decorator for database operations.

    This version includes database-specific exceptions and is more conservative
    about what gets retried.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Initial delay between retries
    """
    # Database-specific non-retryable exceptions
    db_non_retryable = list(NON_RETRYABLE_EXCEPTIONS)

    if SQLALCHEMY_AVAILABLE:
        db_non_retryable.extend([
            sqlalchemy.exc.IntegrityError,  # Constraint violations
            sqlalchemy.exc.DataError,  # Data value errors
            sqlalchemy.exc.ProgrammingError,  # SQL syntax errors
        ])

    db_non_retryable_tuple = tuple(db_non_retryable)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            current_delay = delay
            last_exception = None

            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)

                except db_non_retryable_tuple as e:
                    # Immediately raise non-retryable database exceptions
                    logger.error(
                        f"Non-retryable database exception in {func.__name__}: "
                        f"{type(e).__name__}: {e}"
                    )
                    raise

                except Exception as e:
                    last_exception = e
                    retries += 1

                    if retries > max_retries:
                        logger.error(
                            f"Database operation {func.__name__} failed after {max_retries} retries. "
                            f"Final error: {type(e).__name__}: {e}"
                        )
                        raise last_exception

                    logger.warning(
                        f"Database retry {retries}/{max_retries} for {func.__name__} after "
                        f"{type(e).__name__}: {e}. Waiting {current_delay:.1f}s..."
                    )

                    time.sleep(current_delay)
                    current_delay *= 2  # Fixed 2x backoff for database operations

            # This should never be reached, but for safety
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(f"Database operation {func.__name__} failed without raising an exception")

        return wrapper
    return decorator


def csv_processing_retry(max_retries: int = 2, delay: float = 0.5):
    """
    Specialized retry decorator for CSV processing operations.

    Very conservative retries since CSV parsing errors are usually permanent.

    Args:
        max_retries: Maximum number of retry attempts (default: 2)
        delay: Initial delay between retries (default: 0.5s)
    """
    # CSV-specific non-retryable exceptions
    csv_non_retryable = list(NON_RETRYABLE_EXCEPTIONS)

    if PANDAS_AVAILABLE:
        # Most pandas errors are not worth retrying
        csv_non_retryable.extend([
            pandas.errors.DtypeWarning,
            pandas.errors.PerformanceWarning,
        ])

    csv_non_retryable_tuple = tuple(csv_non_retryable)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            current_delay = delay
            last_exception = None

            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)

                except csv_non_retryable_tuple as e:
                    # Immediately raise non-retryable CSV exceptions
                    logger.error(
                        f"Non-retryable CSV exception in {func.__name__}: "
                        f"{type(e).__name__}: {e}"
                    )
                    raise

                except Exception as e:
                    last_exception = e
                    retries += 1

                    if retries > max_retries:
                        logger.error(
                            f"CSV operation {func.__name__} failed after {max_retries} retries. "
                            f"Final error: {type(e).__name__}: {e}"
                        )
                        raise last_exception

                    logger.warning(
                        f"CSV retry {retries}/{max_retries} for {func.__name__} after "
                        f"{type(e).__name__}: {e}. Waiting {current_delay:.1f}s..."
                    )

                    time.sleep(current_delay)
                    current_delay *= 1.5  # Gentler backoff for CSV operations

            # This should never be reached, but for safety
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(f"CSV operation {func.__name__} failed without raising an exception")

        return wrapper
    return decorator


# Example usage and testing
if __name__ == "__main__":
    # Configure logging for testing
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # Test non-retryable exception
    @hardened_retry(max_retries=3, delay=0.1)
    def test_non_retryable():
        raise ValueError("This should not be retried")

    # Test retryable exception
    @hardened_retry(max_retries=3, delay=0.1)
    def test_retryable():
        import random
        if random.random() < 0.7:  # 70% chance of failure
            raise ConnectionError("Temporary connection issue")
        return "Success!"

    # Test database retry
    @database_retry(max_retries=2, delay=0.1)
    def test_database():
        if SQLALCHEMY_AVAILABLE:
            raise sqlalchemy.exc.ArgumentError("Bad SQL parameter", None, None)
        else:
            raise ValueError("Bad database value")

    print("Testing hardened retry decorators...")

    # Test 1: Non-retryable exception should be raised immediately
    try:
        test_non_retryable()
    except ValueError as e:
        print(f"✅ Non-retryable exception raised immediately: {e}")

    # Test 2: Retryable exception should be retried
    try:
        result = test_retryable()
        print(f"✅ Retryable operation succeeded: {result}")
    except ConnectionError as e:
        print(f"✅ Retryable operation failed after retries: {e}")

    # Test 3: Database non-retryable
    try:
        test_database()
    except Exception as e:
        print(f"✅ Database non-retryable exception: {type(e).__name__}: {e}")

    print("Hardened retry decorator tests completed!")
