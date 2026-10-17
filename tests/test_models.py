from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from ventas.config import Settings
from ventas.models import construir_modelos


def test_construir_modelos_aplica_modelo_y_timeout():
    s = Settings.from_env({
        "NVIDIA_API_KEY": "nvapi-x", "GOOGLE_API_KEY": "g-x", "NIM_MODEL": "meta/llama-3.3-70b-instruct",
        "GEMINI_MODEL": "gemini-x", "DATABASE_URL": "u", "DATABASE_URL_RO": "u", "NIM_TIMEOUT": "7",
    })
    nim, gemini = construir_modelos(s)
    assert isinstance(nim, ChatNVIDIA) and isinstance(gemini, ChatGoogleGenerativeAI)
    assert nim.model == "meta/llama-3.3-70b-instruct" and gemini.model.endswith("gemini-x")
    assert nim._client.timeout == 7
