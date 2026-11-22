"""The core of the language (python/base_node), as this library finds it.

Installed, the core is the package `base_node` beside this one. Inside the Blender add-on both are
sub-packages of the extension, which may add no top-level module: the core is then `lang`, beside
this library. The other modules of the library take what they use of the core from here.
"""

if "." in __package__:
    from ..lang import (EDITION, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, STDLIB_VERSION, BnError, Diagnostic,
                        __version__, ast, colors, format_source, parse, printer, to_source, tokenize, too_deep)
    from ..lang.header import Header as CoreHeader
    from ..lang.header import read_head, unquote, unquoted
    from ..lang.names import RESERVED, goes_on_name, is_bare, is_word, key, snake, starts_name
    from ..lang.parser import WORDS
else:
    from base_node import (EDITION, MAX_HEIGHT, MAX_NESTING, MAX_SOURCE_BYTES, STDLIB_VERSION, BnError, Diagnostic,
                           __version__, ast, colors, format_source, parse, to_source, tokenize, too_deep)
    from base_node import printer
    from base_node.header import Header as CoreHeader
    from base_node.header import read_head, unquote, unquoted
    from base_node.names import RESERVED, goes_on_name, is_bare, is_word, key, snake, starts_name
    from base_node.parser import WORDS
