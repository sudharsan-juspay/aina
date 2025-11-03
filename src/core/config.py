"""
Configuration Management Module

Thread-safe configuration management with support for:
- YAML configuration files
- Environment-based overrides
- Dynamic configuration updates
- Dot-notation access to nested values

Replaces global CONFIG and DYNAMIC_CONFIG_OVERRIDES variables.
"""

import os
import yaml
from threading import RLock
from typing import Any, Dict, Optional, TypeVar
from pathlib import Path
from loguru import logger

from .exceptions import ConfigurationError


T = TypeVar('T')


class Config:
    """
    Thread-safe configuration manager.

    Features:
    - Load configuration from YAML files
    - Environment-specific overrides (dev, staging, production)
    - Dynamic runtime configuration updates
    - Dot-notation key access (e.g., 'elasticsearch.host')
    - Type-safe value retrieval with defaults
    - Thread-safe for concurrent access

    Example:
        >>> config = Config()
        >>> host = config.get('elasticsearch.host')
        >>> config.set('processing.max_logs', 2000)
        >>> timeout = config.get('timeouts.kibana_request_timeout', default=30, expected_type=int)
    """

    def __init__(self, config_path: Optional[str] = None, env: Optional[str] = None):
        """
        Initialize configuration manager.

        Args:
            config_path: Path to base config.yaml file (default: ./config.yaml)
            env: Environment name for overrides (default: from ENV environment variable)

        Raises:
            ConfigurationError: If configuration file cannot be loaded
        """
        self._lock = RLock()
        self._base_config: Dict[str, Any] = {}
        self._overrides: Dict[str, Any] = {}  # Replaces DYNAMIC_CONFIG_OVERRIDES
        self.env = env or os.getenv('ENV', 'production')

        # Determine config file path
        if config_path is None:
            # Use script directory as base
            script_dir = Path(__file__).parent.parent.parent
            config_path = script_dir / 'config.yaml'
        else:
            config_path = Path(config_path)

        self._config_path = config_path
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        try:
            with open(self._config_path, 'r') as f:
                self._base_config = yaml.safe_load(f) or {}

            logger.info(f"Configuration loaded from {self._config_path}")

            # Load environment-specific overrides if they exist
            env_config_path = self._config_path.parent / f'config.{self.env}.yaml'
            if env_config_path.exists():
                with open(env_config_path, 'r') as f:
                    env_overrides = yaml.safe_load(f) or {}
                    self._merge_config(self._base_config, env_overrides)
                    logger.info(f"Environment overrides loaded from {env_config_path}")

        except FileNotFoundError:
            raise ConfigurationError(
                f"Configuration file not found: {self._config_path}",
                details={'path': str(self._config_path)}
            )
        except yaml.YAMLError as e:
            raise ConfigurationError(
                f"Invalid YAML in configuration file: {e}",
                details={'path': str(self._config_path)}
            )

    def _merge_config(self, base: Dict, override: Dict) -> None:
        """
        Recursively merge override config into base config.

        Args:
            base: Base configuration dictionary
            override: Override configuration dictionary
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def _get_nested_value(self, config_dict: Dict, key_path: str) -> Any:
        """
        Get value from nested dictionary using dot notation.

        Args:
            config_dict: Dictionary to search
            key_path: Dot-separated key path (e.g., 'elasticsearch.host')

        Returns:
            Value at key path

        Raises:
            KeyError: If key path doesn't exist
        """
        keys = key_path.split('.')
        value = config_dict

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                raise KeyError(f"Configuration key not found: {key_path}")

        return value

    def _set_nested_value(self, config_dict: Dict, key_path: str, value: Any) -> None:
        """
        Set value in nested dictionary using dot notation.

        Creates intermediate dictionaries if they don't exist.

        Args:
            config_dict: Dictionary to modify
            key_path: Dot-separated key path (e.g., 'elasticsearch.host')
            value: Value to set
        """
        keys = key_path.split('.')
        current = config_dict

        # Navigate to the parent of the target key
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]

        # Set the final key
        current[keys[-1]] = value

    def get(
        self,
        key_path: str,
        default: Optional[T] = None,
        expected_type: Optional[type] = None
    ) -> Any:
        """
        Get configuration value by dot-notation path.

        Checks overrides first, then base configuration.

        Args:
            key_path: Dot-separated key path (e.g., 'elasticsearch.host')
            default: Default value if key not found
            expected_type: Expected type of the value (validates and converts)

        Returns:
            Configuration value

        Raises:
            ConfigurationError: If key not found and no default provided
            TypeError: If value doesn't match expected_type

        Example:
            >>> host = config.get('elasticsearch.host')
            >>> timeout = config.get('timeout', default=30, expected_type=int)
        """
        with self._lock:
            # Try overrides first
            try:
                value = self._get_nested_value(self._overrides, key_path)
            except KeyError:
                # Fall back to base config
                try:
                    value = self._get_nested_value(self._base_config, key_path)
                except KeyError:
                    if default is not None:
                        value = default
                    else:
                        raise ConfigurationError(
                            f"Configuration key '{key_path}' not found and no default provided",
                            config_key=key_path
                        )

            # Type checking and conversion
            if expected_type is not None:
                if value is None:
                    return value

                # Handle boolean conversion for string values
                if expected_type == bool and isinstance(value, str):
                    value = value.lower() in ('true', '1', 'yes', 'on')
                # Handle numeric conversions
                elif expected_type in (int, float):
                    try:
                        value = expected_type(value)
                    except (ValueError, TypeError):
                        raise TypeError(
                            f"Cannot convert '{key_path}' value to {expected_type.__name__}: {value}"
                        )
                # Check type matches
                elif not isinstance(value, expected_type):
                    raise TypeError(
                        f"Configuration key '{key_path}' has type {type(value).__name__}, "
                        f"expected {expected_type.__name__}"
                    )

            return value

    def set(self, key_path: str, value: Any) -> None:
        """
        Set configuration value (runtime override).

        This sets a dynamic override that takes precedence over
        base configuration values.

        Args:
            key_path: Dot-separated key path
            value: Value to set

        Example:
            >>> config.set('elasticsearch.host', 'new-host.example.com')
            >>> config.set('processing.max_logs', 2000)
        """
        with self._lock:
            self._set_nested_value(self._overrides, key_path, value)
            logger.info(f"Configuration override set: {key_path} = {value}")

    def remove_override(self, key_path: str) -> bool:
        """
        Remove a runtime override.

        Args:
            key_path: Dot-separated key path to remove

        Returns:
            True if override was removed, False if not found
        """
        with self._lock:
            try:
                keys = key_path.split('.')
                current = self._overrides

                # Navigate to parent
                for key in keys[:-1]:
                    if key not in current:
                        return False
                    current = current[key]

                # Remove final key
                if keys[-1] in current:
                    del current[keys[-1]]
                    logger.info(f"Configuration override removed: {key_path}")
                    return True

                return False

            except (KeyError, TypeError):
                return False

    def get_all_overrides(self) -> Dict[str, Any]:
        """
        Get all current runtime overrides.

        Returns:
            Dictionary of all overrides
        """
        with self._lock:
            return dict(self._overrides)

    def clear_overrides(self) -> None:
        """Clear all runtime overrides."""
        with self._lock:
            self._overrides.clear()
            logger.info("All configuration overrides cleared")

    def reload(self) -> None:
        """
        Reload configuration from file.

        Preserves runtime overrides.
        """
        with self._lock:
            self._load_config()
            logger.info("Configuration reloaded from file")

    def to_dict(self) -> Dict[str, Any]:
        """
        Get complete configuration as dictionary.

        Merges base config with overrides.

        Returns:
            Complete configuration dictionary
        """
        with self._lock:
            # Deep copy base config
            import copy
            result = copy.deepcopy(self._base_config)

            # Merge overrides
            self._merge_config(result, self._overrides)

            return result


# Global singleton instance
# This replaces the global CONFIG and DYNAMIC_CONFIG_OVERRIDES variables
config = Config()
