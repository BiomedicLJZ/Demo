"""Proveedor principal (AWS Bedrock), con respaldo en NVIDIA NIM y después Google AI Studio."""
from langchain_aws import ChatBedrockConverse
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from ventas.config import Settings


def construir_modelos(s: Settings) -> tuple[ChatBedrockConverse, ChatNVIDIA, ChatGoogleGenerativeAI]:
    # shortcut: región fija; el token de Bedrock es una API key de larga duración. Si hace falta otra, súbela a Settings.
    bedrock = ChatBedrockConverse(model=s.bedrock_model, api_key=s.bedrock_api_key, region_name="us-east-1",
                                  temperature=0.2)
    nim = ChatNVIDIA(model=s.nim_model, api_key=s.nvidia_api_key, temperature=0.2)
    # shortcut: ChatNVIDIA no expone timeout; se fija en su cliente interno (privado, default 60 s).
    # Si una versión futura lo expone como parámetro, pásalo al constructor.
    nim._client.timeout = s.nim_timeout
    gemini = ChatGoogleGenerativeAI(
        model=s.gemini_model, google_api_key=s.google_api_key, temperature=0.2, max_retries=2, timeout=60
    )
    return bedrock, nim, gemini
