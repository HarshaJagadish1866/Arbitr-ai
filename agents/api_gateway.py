"""
agents/api_gateway.py — Multi-Key API Gateway

Manages Gemini API key pools for the legal reviewer pipeline
with automatic failover and rotation on HTTP 429 rate limit errors.
"""

import itertools
import logging
import os
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class KeyPoolExhaustedError(RuntimeError):
    """
    Raised when all API keys in a pool have been rate-limited and the
    maximum number of retry attempts has been exhausted.

    Attributes:
        role: The agent role whose key pool was exhausted (e.g. "parser").
        attempts: The total number of attempts made before giving up.
    """

    def __init__(self, role: str, attempts: int) -> None:
        self.role = role
        self.attempts = attempts
        super().__init__(
            f"All API keys in the '{role}' pool have been rate-limited. "
            f"Exhausted after {attempts} retry attempts. "
            "Please wait for rate limits to reset or add additional API keys."
        )


# =============================================================================
# CONSTANTS
# =============================================================================

# Maximum number of retry attempts before declaring pool exhaustion.
# With 2 keys per pool, 3 retries means we cycle through key A → B → A.
MAX_RETRIES = 3

# Environment variable names for the multi-key configuration.
# These are intentionally explicit (no dynamic f-string construction)
# so that a grep for the variable name finds this exact location.
_PARSER_KEY_VARS = ("GEMINI_KEY_PARSER_1", "GEMINI_KEY_PARSER_2")
_ANALYST_KEY_VARS = ("GEMINI_KEY_ANALYST_1", "GEMINI_KEY_ANALYST_2")

# Legacy single-key variable (deprecated but supported for fallback).
_LEGACY_KEY_VAR = "GEMINI_API_KEY"

# Agent roles → pool names (for consistent logging and mapping).
_ROLE_TO_POOL = {
    "parser": "parser",
    "analyst": "analyst",
    "protector": "analyst",  # Protector shares the analyst key pool.
}


# =============================================================================
# AGENT GATEWAY CLASS
# =============================================================================

class AgentGateway:
    """
    Routes API requests through configured key pools with automatic rate-limit failover.
    """

    def __init__(self) -> None:
        """
        Initialise the gateway by loading API keys from environment variables.

        Key loading strategy:
        1. Attempt to load the dedicated multi-key variables for each pool.
        2. If a pool has ZERO keys, check for the legacy GEMINI_API_KEY and
           use it as a fallback for that pool.
        3. If a pool is STILL empty after fallback, raise ValueError.

        Raises:
            ValueError: If any pool ends up with zero usable keys.
        """
        logger.info("Initialising AgentGateway — loading API key pools...")

        # --- Load parser pool keys ---
        parser_keys = self._load_keys_from_env(_PARSER_KEY_VARS)
        if not parser_keys:
            parser_keys = self._try_legacy_fallback("parser")

        # --- Load analyst pool keys ---
        analyst_keys = self._load_keys_from_env(_ANALYST_KEY_VARS)
        if not analyst_keys:
            analyst_keys = self._try_legacy_fallback("analyst")

        # --- Validate that both pools have at least one key ---
        if not parser_keys:
            raise ValueError(
                "No API keys found for the parser pool. "
                "Set at least one of: GEMINI_KEY_PARSER_1, GEMINI_KEY_PARSER_2 "
                f"(or the legacy {_LEGACY_KEY_VAR} as fallback) in your .env file."
            )
        if not analyst_keys:
            raise ValueError(
                "No API keys found for the analyst pool. "
                "Set at least one of: GEMINI_KEY_ANALYST_1, GEMINI_KEY_ANALYST_2 "
                f"(or the legacy {_LEGACY_KEY_VAR} as fallback) in your .env file."
            )

        # --- Build the cycle iterators ---
        # itertools.cycle produces an infinite iterator that loops over the keys.
        # We also store the raw lists for logging pool sizes.
        self._pools = {
            "parser": itertools.cycle(parser_keys),
            "analyst": itertools.cycle(analyst_keys),
        }
        self._pool_sizes = {
            "parser": len(parser_keys),
            "analyst": len(analyst_keys),
        }

        logger.info(
            "AgentGateway ready — parser pool: %d key(s), analyst pool: %d key(s).",
            self._pool_sizes["parser"],
            self._pool_sizes["analyst"],
        )

    # -------------------------------------------------------------------------
    # Key Loading Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_keys_from_env(var_names: tuple[str, ...]) -> list[str]:
        """
        Load API keys from the specified environment variable names.

        Only includes variables that are set and non-empty.
        Strips whitespace from values to prevent subtle auth failures.

        Args:
            var_names: Tuple of environment variable names to check.

        Returns:
            A list of non-empty API key strings.
        """
        keys = []
        for var_name in var_names:
            value = os.getenv(var_name, "").strip()
            if value and value != "your_key_here":
                keys.append(value)
                logger.debug("Loaded API key from %s", var_name)
            else:
                logger.debug("Skipping %s (not set or placeholder)", var_name)
        return keys

    @staticmethod
    def _try_legacy_fallback(pool_name: str) -> list[str]:
        """
        Attempt to use the legacy GEMINI_API_KEY as a fallback for a pool.

        Args:
            pool_name: The pool name (for logging purposes).

        Returns:
            A single-element list with the legacy key, or empty list.
        """
        legacy_key = os.getenv(_LEGACY_KEY_VAR, "").strip()
        if legacy_key and legacy_key != "your_gemini_api_key_here":
            logger.warning(
                "No dedicated keys found for '%s' pool — falling back to "
                "legacy %s. Consider migrating to GEMINI_KEY_PARSER_*/GEMINI_KEY_ANALYST_*.",
                pool_name,
                _LEGACY_KEY_VAR,
            )
            return [legacy_key]
        return []

    # -------------------------------------------------------------------------
    # Key Activation
    # -------------------------------------------------------------------------

    def _activate_next_key(self, role: str) -> str:
        """
        Advance to the next key in the role's pool and set it in os.environ.

        The SDK reads os.environ["GEMINI_API_KEY"] when creating an Agent
        session, so this must be called BEFORE the `async with Agent(...)`.

        Args:
            role: The agent role ("parser", "analyst", or "protector").

        Returns:
            The last 4 characters of the activated key (for safe logging).

        Raises:
            ValueError: If the role is not recognised.
        """
        pool_name = _ROLE_TO_POOL.get(role)
        if pool_name is None:
            raise ValueError(
                f"Unknown agent role: '{role}'. "
                f"Valid roles: {list(_ROLE_TO_POOL.keys())}"
            )

        key = next(self._pools[pool_name])
        os.environ["GEMINI_API_KEY"] = key

        # Log only the last 4 chars for security (never log full keys).
        safe_suffix = key[-4:]
        logger.info(
            "Activated API key ...%s for role '%s' (pool: '%s').",
            safe_suffix, role, pool_name,
        )
        return safe_suffix

    # -------------------------------------------------------------------------
    # Failover Execution
    # -------------------------------------------------------------------------

    async def execute_with_failover(
        self,
        role: str,
        coro_factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        """
        Execute an async agent call with automatic key rotation on rate limits.

        This is the primary method used by the orchestrator. It:
        1. Activates the next key for the given role.
        2. Awaits the coroutine produced by coro_factory().
        3. On HTTP 429 (ResourceExhausted): logs a warning, cycles to the
           next key, and retries.
        4. After MAX_RETRIES failures: raises KeyPoolExhaustedError.

        Design Note — Why coro_factory (not a pre-built coroutine):
            Python coroutines can only be awaited ONCE. Since we may need to
            retry, we need a factory that creates a FRESH coroutine on each
            attempt. A lambda like `lambda: run_parser_agent(...)` does this.

        Args:
            role:          The agent role ("parser", "analyst", "protector").
            coro_factory:  A callable that returns a fresh awaitable each time.

        Returns:
            The result of the successful agent call.

        Raises:
            KeyPoolExhaustedError: If all retries are exhausted due to 429 errors.
            Exception: Any non-429 exception from the agent call is re-raised
                       immediately (no retry for non-rate-limit errors).
        """
        last_exception = None

        for attempt in range(1, MAX_RETRIES + 1):
            key_suffix = self._activate_next_key(role)

            try:
                result = await coro_factory()
                logger.info(
                    "Agent '%s' completed successfully on attempt %d/%d (key ...%s).",
                    role, attempt, MAX_RETRIES, key_suffix,
                )
                return result

            except Exception as e:
                # Check if this is a 429 rate-limit error.
                # The Google API libraries raise google.api_core.exceptions.ResourceExhausted
                # for HTTP 429. We also check for common patterns in other exception types
                # to be robust against SDK version differences.
                if self._is_rate_limit_error(e):
                    last_exception = e
                    logger.warning(
                        "⚠️  Rate limit (429) hit for role '%s' on attempt %d/%d "
                        "(key ...%s). Cycling to next key in '%s' pool...",
                        role, attempt, MAX_RETRIES, key_suffix,
                        _ROLE_TO_POOL[role],
                    )
                    # The next iteration of the loop will call _activate_next_key,
                    # which advances the cycle iterator to the next key.
                    continue
                else:
                    # Non-rate-limit errors are NOT retried — re-raise immediately.
                    logger.error(
                        "Agent '%s' failed with non-retryable error on attempt %d: %s",
                        role, attempt, e,
                    )
                    raise

        # All retry attempts exhausted due to rate limiting.
        raise KeyPoolExhaustedError(role=role, attempts=MAX_RETRIES) from last_exception

    # -------------------------------------------------------------------------
    # Error Classification
    # -------------------------------------------------------------------------

    @staticmethod
    def _is_rate_limit_error(exception: Exception) -> bool:
        """
        Determine if an exception represents an HTTP 429 rate-limit error.

        We check multiple conditions to be robust across SDK versions:
        1. google.api_core.exceptions.ResourceExhausted (the canonical type).
        2. Any exception with a `code` or `status_code` attribute equal to 429.
        3. The string "429" appearing in the exception message (last resort).

        Args:
            exception: The caught exception to classify.

        Returns:
            True if this is a rate-limit error that should trigger key rotation.
        """
        # Check 1: Canonical google.api_core type.
        # We use string-based type checking to avoid a hard import dependency
        # on google.api_core, which may not always be directly installed.
        exception_type_name = type(exception).__name__
        if exception_type_name == "ResourceExhausted":
            return True

        # Check 2: HTTP status code attributes (covers various SDK wrappers).
        for attr in ("code", "status_code", "http_status"):
            code = getattr(exception, attr, None)
            if code == 429:
                return True

        # Check 3: String matching as a last resort.
        # This catches wrapped exceptions where the 429 status is in the message.
        error_str = str(exception).lower()
        if "429" in error_str and ("rate" in error_str or "resource" in error_str or "quota" in error_str):
            return True

        return False
