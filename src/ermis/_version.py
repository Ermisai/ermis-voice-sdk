"""A versão do SDK, que é a mesma da Ermis Voice API com que ele fala (0.5.3 com 0.5.3)."""

import re

__version__ = "0.5.3"
# A versão da API: o X.Y.Z do SDK (uma correção só do SDK, 0.5.3.post1, continua falando com a 0.5.3)
API_VERSION = re.match(r"\d+\.\d+\.\d+", __version__)[0]
USER_AGENT = f"ermis-voice-python/{__version__}"
