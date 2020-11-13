"""
Utilities for monitoring code_owner
"""
import logging
import re
from functools import wraps

from django.conf import settings

from ..utils import set_custom_attribute

log = logging.getLogger(__name__)


def get_code_owner_from_module(module):
    """
    Attempts lookup of code_owner based on a code module,
    finding the most specific match. If no match, returns None.

    For example, if the module were 'openedx.features.discounts.views',
    this lookup would match on 'openedx.features.discounts' before
    'openedx.features', because the former is more specific.

    See how to:
    https://github.com/edx/edx-django-utils/blob/master/edx_django_utils/monitoring/docs/how_tos/add_code_owner_custom_attribute_to_an_ida.rst

    """
    if not module:
        return None

    code_owner_mappings = get_code_owner_mappings()
    if code_owner_mappings is None:
        return None

    module_parts = module.split('.')
    # To make the most specific match, start with the max number of parts
    for number_of_parts in range(len(module_parts), 0, -1):
        partial_path = '.'.join(module_parts[0:number_of_parts])
        if partial_path in code_owner_mappings:
            code_owner = code_owner_mappings[partial_path]
            return code_owner
    return None


def is_code_owner_mappings_configured():
    """
    Returns True if code owner mappings were configured, and False otherwise.
    """
    return isinstance(get_code_owner_mappings(), dict)


# cached lookup table for code owner given a module path.
# do not access this directly, but instead use get_code_owner_mappings.
_PATH_TO_CODE_OWNER_MAPPINGS = None


def get_code_owner_mappings():
    """
    Returns the contents of the CODE_OWNER_MAPPINGS Django Setting, processed
    for efficient lookup by path.

    Returns:
         (dict): dict mapping modules to code owners, or None if there are no
            configured mappings, or an empty dict if there is an error processing
            the setting.

    Example return value::

        {
            'xblock_django': 'team-red',
            'openedx.core.djangoapps.xblock': 'team-red',
            'badges': 'team-blue',
        }

    """
    global _PATH_TO_CODE_OWNER_MAPPINGS

    # Return cached processed mappings if already processed
    if _PATH_TO_CODE_OWNER_MAPPINGS is not None:
        return _PATH_TO_CODE_OWNER_MAPPINGS

    # Uses temporary variable to build mappings to avoid multi-threading issue with a partially
    # processed map.  Worst case, it is processed more than once at start-up.
    path_to_code_owner_mapping = {}

    # .. setting_name: CODE_OWNER_MAPPINGS
    # .. setting_default: None
    # .. setting_description: Used for monitoring and reporting of ownership. Use a
    #      dict with keys of code owner name and value as a list of dotted path
    #      module names owned by the code owner.
    code_owner_mappings = getattr(settings, 'CODE_OWNER_MAPPINGS', None)
    if code_owner_mappings is None:
        return None

    try:
        for code_owner in code_owner_mappings:
            path_list = code_owner_mappings[code_owner]
            for path in path_list:
                path_to_code_owner_mapping[path] = code_owner
                optional_module_prefix_match = _OPTIONAL_MODULE_PREFIX_PATTERN.match(path)
                # if path has an optional prefix, also add the module name without the prefix
                if optional_module_prefix_match:
                    path_without_prefix = path[optional_module_prefix_match.end():]
                    path_to_code_owner_mapping[path_without_prefix] = code_owner
    except Exception as e:  # pylint: disable=broad-except
        # will remove broad exceptions after ensuring all proper cases are covered
        set_custom_attribute('deprecated_broad_except_get_code_owner_mappings', e.__class__)
        log.exception('Error processing code_owner_mappings. {}'.format(e))

    _PATH_TO_CODE_OWNER_MAPPINGS = path_to_code_owner_mapping
    return _PATH_TO_CODE_OWNER_MAPPINGS


def _get_catch_all_code_owner():
    """
    If the catch-all module "*" is configured, return the code_owner.

    Returns:
        (str): code_owner or None if no catch-all configured.

    """
    try:
        code_owner = get_code_owner_from_module('*')
        return code_owner
    except Exception as e:  # pylint: disable=broad-except; #pragma: no cover
        # will remove broad exceptions after ensuring all proper cases are covered
        set_custom_attribute('deprecated_broad_except___get_module_from_current_transaction', e.__class__)
        return None


def set_code_owner_attribute_from_module(module):
    """
    Updates the code_owner and code_owner_module custom attributes.

    Celery tasks or other non-web functions do not use middleware, so we need
        an alternative way to set the code_owner custom attribute.

    Note: These settings will be overridden by the CodeOwnerMonitoringMiddleware.
        This method can't be used to override web functions at this time.

    Usage::

        set_code_owner_attribute_from_module(__name__)

    """
    set_custom_attribute('code_owner_module', module)
    code_owner = get_code_owner_from_module(module)
    if not code_owner:
        code_owner = _get_catch_all_code_owner()

    if code_owner:
        set_custom_attribute('code_owner', code_owner)


def set_code_owner_attribute(wrapped_function):
    """
    Decorator to set the code_owner and code_owner_module custom attributes.

    Celery tasks or other non-web functions do not use middleware, so we need
        an alternative way to set the code_owner custom attribute.

    Usage::

        @task()
        @set_code_owner_attribute
        def example_task():
            ...

    Note: If the decorator can't be used for some reason, just call
        ``set_code_owner_attribute_from_module`` directly.

    """
    @wraps(wrapped_function)
    def new_function(*args, **kwargs):
        set_code_owner_attribute_from_module(wrapped_function.__module__)
        return wrapped_function(*args, **kwargs)
    return new_function


def clear_cached_mappings():
    """
    Clears the cached path to code owner mappings. Useful for testing.
    """
    global _PATH_TO_CODE_OWNER_MAPPINGS
    _PATH_TO_CODE_OWNER_MAPPINGS = None


# TODO: Retire this once edx-platform import_shims is no longer used.
#   See https://github.com/edx/edx-platform/tree/854502b560bda74ef898501bb2a95ce238cf794c/import_shims
_OPTIONAL_MODULE_PREFIX_PATTERN = re.compile(r'^(lms|common|openedx\.core)\.djangoapps\.')
