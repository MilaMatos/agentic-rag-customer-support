import logging
import os
import warnings

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

warnings.filterwarnings("ignore", category=DeprecationWarning, module="crewai.*")

# para silenciar o aviso de contagem aproximada de tokens no CrewAI
logging.getLogger("crewai.llms.base_llm").setLevel(logging.ERROR)
logging.getLogger("crewai").setLevel(logging.ERROR)