import base64
import os
from pathlib import Path
from typing import Any

import httpx

from gateway_mcp.backends.common import BackendConfigError, BackendRouteError
from gateway_mcp.services.auth import current_actor
from gateway_mcp.services.file_transfers import ready_file_for_actor
from gateway_mcp.services.managed_integrations import integration_value


def _openrouter_headers() -> dict[str, str]:
    api_key = integration_value("openrouter", "OPENROUTER_API_KEY")
    if not api_key:
        raise BackendConfigError("OpenRouter managed integration is not configured")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _openrouter_allowed_path(file_path: Path) -> bool:
    raw = os.getenv("OPENROUTER_ALLOWED_AUDIO_DIRS", "").strip()
    if not raw:
        return True
    allowed = [Path(path.strip()).expanduser().resolve() for path in raw.split(";") if path.strip()]
    resolved = file_path.expanduser().resolve()
    for base in allowed:
        try:
            resolved.relative_to(base)
            return True
        except ValueError:
            continue
    return False


def _read_audio_base64(file_path: str) -> tuple[str, str, Path]:
    path = Path(file_path).expanduser().resolve()
    if not _openrouter_allowed_path(path):
        raise BackendConfigError("Audio path is not allowed by OPENROUTER_ALLOWED_AUDIO_DIRS")
    max_size = int(os.getenv("OPENROUTER_MAX_AUDIO_SIZE_MB", "10")) * 1024 * 1024
    if path.stat().st_size > max_size:
        raise BackendConfigError("Audio file exceeds OPENROUTER_MAX_AUDIO_SIZE_MB")
    audio_format = path.suffix.lower().lstrip(".") or "wav"
    return base64.b64encode(path.read_bytes()).decode("ascii"), audio_format, path


async def _call_openrouter_audio(route: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    operation = route.get("operation")
    base_url = integration_value("openrouter", "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    timeout = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "120"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        if operation == "list_audio_models":
            response = await client.get(f"{base_url}/models", headers=_openrouter_headers())
            try:
                data: Any = response.json()
            except ValueError:
                data = {"raw": response.text}
            models = data.get("data") or data.get("models") or [] if isinstance(data, dict) else []
            audio_models: list[dict[str, Any]] = []
            for model in models:
                input_modalities = (
                    model.get("input_modalities")
                    or model.get("inputModalities")
                    or model.get("modalities", {}).get("input")
                    or []
                )
                if isinstance(input_modalities, str):
                    input_modalities = [input_modalities]
                if "audio" in set(input_modalities):
                    audio_models.append(
                        {
                            "id": model.get("id") or model.get("model") or model.get("name"),
                            "name": model.get("name") or model.get("id"),
                            "context_length": model.get("context_length") or model.get("contextLength"),
                            "pricing": model.get("pricing"),
                        }
                    )
            limit = max(1, int(arguments.get("limit") or 30))
            return {
                "ok": response.is_success,
                "status": response.status_code,
                "backend": "openrouter-audio",
                "data": {"audio_models": audio_models[:limit]},
            }

        if operation != "transcribe_audio":
            raise BackendRouteError(f"Unsupported OpenRouter audio operation: {operation or '<missing>'}")

        model_id = str(arguments.get("model") or integration_value("openrouter", "OPENROUTER_TRANSCRIBE_MODEL")).strip()
        if not model_id:
            raise BackendConfigError("Provide model or set OPENROUTER_TRANSCRIBE_MODEL")
        upload_id = str(arguments.get("upload_id") or "").strip()
        file_path = str(arguments.get("file_path") or "").strip()
        if upload_id:
            staged_path, staged = ready_file_for_actor(actor=current_actor(), upload_id=upload_id)
            audio_b64 = base64.b64encode(staged_path.read_bytes()).decode("ascii")
            audio_format = Path(str(staged.get("filename") or "audio.wav")).suffix.lower().lstrip(".") or "wav"
            resolved_path = staged_path
        elif file_path:
            audio_b64, audio_format, resolved_path = _read_audio_base64(file_path)
        else:
            raise BackendRouteError("OpenRouter audio transcription requires upload_id or file_path")
        language = str(arguments.get("language") or "ru")
        prompt = str(arguments.get("prompt") or "")
        instruction = (
            "You are a transcription engine. Return ONLY the transcript text. "
            "No markdown, no explanations. "
            f"Language hint: {language}. "
        )
        if prompt:
            instruction += f"Context hint: {prompt}. "
        instruction += "If speakers are obvious, add short speaker labels."

        payload: dict[str, Any] = {
            "model": model_id,
            "temperature": float(arguments.get("temperature") or 0.0),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": audio_format},
                        },
                    ],
                }
            ],
            "stream": False,
        }
        if int(arguments.get("max_tokens") or 0) > 0:
            payload["max_tokens"] = int(arguments["max_tokens"])

        response = await client.post(
            f"{base_url}/chat/completions",
            headers=_openrouter_headers(),
            json=payload,
        )

    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}

    text = ""
    if isinstance(data, dict):
        try:
            text = ((data.get("choices") or [])[0].get("message") or {}).get("content") or ""
        except (AttributeError, IndexError, TypeError):
            text = ""

    output_file = None
    if arguments.get("save_to_file") and text:
        output_path = resolved_path.parent / f"{resolved_path.stem} - transcript.txt"
        output_path.write_text(text.strip(), encoding="utf-8")
        output_file = str(output_path)

    return {
        "ok": response.is_success,
        "status": response.status_code,
        "backend": "openrouter-audio",
        "model": data.get("model") or model_id if isinstance(data, dict) else model_id,
        "data": {
            "text": text.strip(),
            "usage": data.get("usage") if isinstance(data, dict) else None,
            "raw_id": data.get("id") if isinstance(data, dict) else None,
            "output_file": output_file,
        },
    }
