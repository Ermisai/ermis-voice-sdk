"""A versão do SDK, que é a mesma da Ermis Voice API com que ele fala (0.4.8 com 0.4.8)."""

import re

__version__ = "0.4.8"
# A versão da API: o X.Y.Z do SDK (uma correção só do SDK, 0.4.8.post1, continua falando com a 0.4.8)
API_VERSION = re.match(r"\d+\.\d+\.\d+", __version__)[0]
USER_AGENT = f"ermis-voice-python/{__version__}"
