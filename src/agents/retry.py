import logging
import time

logger = logging.getLogger(__name__)


def executar_crew_com_retry(crew, max_tentativas: int = 2, espera_s: float = 1.5):
    for tentativa in range(1, max_tentativas + 1):
        try:
            return crew.kickoff()
        except (ValueError, TypeError, KeyError):
            raise
        except Exception as exc:
            if tentativa >= max_tentativas:
                raise
            logger.warning("Falha transitória no LLM (%d/%d): %s", tentativa, max_tentativas, exc)
            time.sleep(espera_s * tentativa)