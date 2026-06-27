# Re-exporta el módulo stdlib operator desde su extensión C (_operator)
# para evitar que este directorio lo tape al correr python main.py
from _operator import *  # noqa: F401, F403
try:
    from _operator import __doc__  # noqa: F401
except ImportError:
    pass
