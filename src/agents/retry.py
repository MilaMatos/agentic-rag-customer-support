import socket
import time

STATUS_NAO_RECUPERAVEIS = {400, 401, 403, 404, 410, 422}
STATUS_SEM_FALLBACK = {400, 401, 403, 422}


def aguardar_conexao(
    host: str = "integrate.api.nvidia.com",
    porta: int = 443,
    intervalo_s: float = 3.0,
    max_verificacoes: int = 3,
) -> bool:
    for tentativa in range(1, max_verificacoes + 1):
        try:
            with socket.create_connection((host, porta), timeout=5):
                return True
        except OSError:
            if tentativa == 1:
                print("   [REDE] Sem internet/DNS. Tentando reconectar...", flush=True)
            if tentativa < max_verificacoes:
                time.sleep(intervalo_s)
    return False


def _eh_erro_conexao(exc: Exception) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, ConnectionError) or "connection" in msg or "name resolution" in msg


def _kickoff_com_retry(crew, max_tentativas: int = 2, espera_s: float = 2.0):
    for tentativa in range(1, max_tentativas + 1):
        try:
            return crew.kickoff()
        except (ValueError, TypeError, KeyError):
            raise
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in STATUS_NAO_RECUPERAVEIS or tentativa >= max_tentativas:
                raise
            if _eh_erro_conexao(exc):
                aguardar_conexao()
            print(f"   [RETRY {tentativa}/{max_tentativas}] {type(exc).__name__}", flush=True)
            time.sleep(espera_s * tentativa)


def executar_crew_com_retry(
    crew,
    max_tentativas: int = 2,
    espera_s: float = 2.0,
    fallback_llm=None,
):
    try:
        return _kickoff_com_retry(crew, max_tentativas=max_tentativas, espera_s=espera_s)
    except (ValueError, TypeError, KeyError):
        raise
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if fallback_llm is None or status in STATUS_SEM_FALLBACK:
            raise
        print(f"   [FALLBACK] Acionando modelo reserva após {type(exc).__name__}", flush=True)
        for agent in crew.agents:
            agent.llm = fallback_llm
        return _kickoff_com_retry(crew, max_tentativas=1, espera_s=espera_s)