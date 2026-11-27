import socket
import time

STATUS_NAO_RECUPERAVEIS = {400, 401, 403, 404, 410, 422}


def aguardar_conexao(
    host: str = "integrate.api.nvidia.com",
    porta: int = 443,
    intervalo_s: float = 10.0,
) -> None:
    avisou = False
    while True:
        try:
            with socket.create_connection((host, porta), timeout=5):
                if avisou:
                    print("   [REDE] Conexão restabelecida. Retomando...", flush=True)
                return
        except OSError:
            if not avisou:
                print("   [REDE] Sem internet/DNS. Aguardando conexão voltar...", flush=True)
                avisou = True
            time.sleep(intervalo_s)


def _eh_erro_conexao(exc: Exception) -> bool:
    msg = str(exc).lower()
    return isinstance(exc, ConnectionError) or "connection" in msg or "name resolution" in msg


def executar_crew_com_retry(crew, max_tentativas: int = 3, espera_s: float = 2.0):
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