"""Translations router -- /api/v1/translations.

Includes AI-powered auto-translation via the unified AIClient.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.ai_client import get_ai_client_from_settings
from api.core.config import settings
from api.core.database import get_db
from api.core.security import get_current_user, require_role
from api.models.users import User, UserRole

logger = logging.getLogger("hosthive.translations")

router = APIRouter()

_admin_dep = require_role("admin")

# Path to locale files - resolved relative to project root
_LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "i18n" / "locales"

# Language metadata mapping (code -> display info)
_LANGUAGE_META: Dict[str, Dict[str, str]] = {
    "en": {"name": "English", "flag": "\U0001f1ec\U0001f1e7"},
    "pl": {"name": "Polski", "flag": "\U0001f1f5\U0001f1f1"},
    "de": {"name": "Deutsch", "flag": "\U0001f1e9\U0001f1ea"},
    "es": {"name": "Espanol", "flag": "\U0001f1ea\U0001f1f8"},
    "fr": {"name": "Francais", "flag": "\U0001f1eb\U0001f1f7"},
    "uk": {"name": "Ukrainska", "flag": "\U0001f1fa\U0001f1e6"},
    "ru": {"name": "Russkij", "flag": "\U0001f1f7\U0001f1fa"},
    "pt": {"name": "Portugues", "flag": "\U0001f1f5\U0001f1f9"},
    "it": {"name": "Italiano", "flag": "\U0001f1ee\U0001f1f9"},
    "ja": {"name": "Japanese", "flag": "\U0001f1ef\U0001f1f5"},
    "zh": {"name": "Chinese", "flag": "\U0001f1e8\U0001f1f3"},
    "ko": {"name": "Korean", "flag": "\U0001f1f0\U0001f1f7"},
    "tr": {"name": "Turkce", "flag": "\U0001f1f9\U0001f1f7"},
    "nl": {"name": "Nederlands", "flag": "\U0001f1f3\U0001f1f1"},
    "sv": {"name": "Svenska", "flag": "\U0001f1f8\U0001f1ea"},
    "cs": {"name": "Cestina", "flag": "\U0001f1e8\U0001f1ff"},
    "ar": {"name": "Arabic", "flag": "\U0001f1f8\U0001f1e6"},
}


def _require_admin(user: User) -> None:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")


def _read_locale(lang: str) -> Dict[str, Any]:
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_locale(lang: str, data: Dict[str, Any]) -> None:
    path = _LOCALES_DIR / f"{lang}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _flatten_keys(data: Dict[str, Any], prefix: str = "") -> List[str]:
    """Flatten nested dict into dot-separated keys."""
    keys = []
    for k, v in data.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_flatten_keys(v, full))
        else:
            keys.append(full)
    return keys


def _get_nested(data: Dict[str, Any], key: str) -> Any:
    parts = key.split(".")
    current = data
    for p in parts:
        if isinstance(current, dict) and p in current:
            current = current[p]
        else:
            return None
    return current


# ── Models ──────────────────────────────────────────────────────────────

class LanguageInfo(BaseModel):
    code: str
    name: str
    flag: str
    translated: int = 0
    total: int = 0
    percentage: float = 0.0


class AddLanguageRequest(BaseModel):
    code: str
    name: str
    flag: str = ""


class TranslationUpdateRequest(BaseModel):
    translations: Dict[str, Any]


# ── Endpoints ───────────────────────────────────────────────────────────

@router.get("/languages", response_model=List[LanguageInfo])
async def list_languages(current_user: User = Depends(get_current_user)):
    """List all available languages with translation progress."""
    en_data = _read_locale("en")
    en_keys = _flatten_keys(en_data)
    total = len(en_keys)

    languages = []
    for f in sorted(_LOCALES_DIR.glob("*.json")):
        code = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        lang_keys = _flatten_keys(data)
        # Count keys that exist and are non-empty
        translated = 0
        for key in en_keys:
            val = _get_nested(data, key)
            if val is not None and val != "" and val != _get_nested(en_data, key):
                translated += 1
            elif code == "en" and val is not None and val != "":
                translated += 1

        meta = _LANGUAGE_META.get(code, {})
        languages.append(LanguageInfo(
            code=code,
            name=meta.get("name", code),
            flag=meta.get("flag", ""),
            translated=translated,
            total=total,
            percentage=round((translated / total * 100) if total else 0, 1),
        ))

    return languages


@router.get("/{lang}")
async def get_translations(lang: str, current_user: User = Depends(get_current_user)):
    """Get all translation strings for a language."""
    return _read_locale(lang)


@router.put("/{lang}")
async def update_translations(
    lang: str,
    body: TranslationUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """Save/update translations for a language. Admin only."""
    _require_admin(current_user)
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found.")

    _write_locale(lang, body.translations)
    return {"detail": f"Translations for '{lang}' saved successfully."}


@router.post("/languages", status_code=status.HTTP_201_CREATED)
async def add_language(
    body: AddLanguageRequest,
    current_user: User = Depends(get_current_user),
):
    """Add a new language by creating an empty locale file. Admin only."""
    _require_admin(current_user)

    code = body.code.lower().strip()
    if not code or len(code) > 10:
        raise HTTPException(status_code=400, detail="Invalid language code.")

    path = _LOCALES_DIR / f"{code}.json"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"Language '{code}' already exists.")

    # Create skeleton from en.json with empty values
    en_data = _read_locale("en")

    def _empty_copy(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _empty_copy(v) for k, v in obj.items()}
        return ""

    skeleton = _empty_copy(en_data)
    _write_locale(code, skeleton)

    # Update metadata
    if code not in _LANGUAGE_META:
        _LANGUAGE_META[code] = {"name": body.name, "flag": body.flag or code.upper()}

    return {"detail": f"Language '{code}' created.", "code": code, "name": body.name}


@router.delete("/languages/{lang}", status_code=status.HTTP_200_OK)
async def delete_language(lang: str, current_user: User = Depends(get_current_user)):
    """Remove a language. Admin only. Cannot delete English."""
    _require_admin(current_user)

    if lang == "en":
        raise HTTPException(status_code=400, detail="Cannot delete the base English language.")

    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Language '{lang}' not found.")

    path.unlink()
    return {"detail": f"Language '{lang}' deleted."}


@router.get("/missing/{lang}")
async def get_missing_translations(lang: str, current_user: User = Depends(get_current_user)):
    """Compare with en.json and return missing/empty keys."""
    en_data = _read_locale("en")
    lang_data = _read_locale(lang)

    en_keys = _flatten_keys(en_data)
    missing = []
    for key in en_keys:
        val = _get_nested(lang_data, key)
        if val is None or val == "":
            missing.append({
                "key": key,
                "english": _get_nested(en_data, key),
            })

    return {"language": lang, "missing_count": len(missing), "total": len(en_keys), "missing": missing}


@router.post("/export/{lang}")
async def export_language(lang: str, current_user: User = Depends(get_current_user)):
    """Export a language file as JSON download."""
    data = _read_locale(lang)
    content = json.dumps(data, ensure_ascii=False, indent=2)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{lang}.json"'},
    )


@router.post("/import")
async def import_language(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Import a JSON translation file. Admin only. Filename determines language code."""
    _require_admin(current_user)

    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a .json file.")

    lang_code = file.filename.rsplit(".", 1)[0].lower()
    if not lang_code or len(lang_code) > 10:
        raise HTTPException(status_code=400, detail="Invalid language code from filename.")

    try:
        raw = await file.read()
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON root must be an object.")

    _write_locale(lang_code, data)
    return {"detail": f"Language '{lang_code}' imported successfully.", "code": lang_code}


# ══════════════════════════════════════════════════════════════════════════
# AI-powered auto-translation
# ══════════════════════════════════════════════════════════════════════════

# ---------------------------------------------------------------------------
# ISO 639-1 code -> full English name
# ---------------------------------------------------------------------------

_LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English",
    "pl": "Polish",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "uk": "Ukrainian",
    "ru": "Russian",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "pt": "Portuguese",
    "it": "Italian",
    "nl": "Dutch",
    "sv": "Swedish",
    "cs": "Czech",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "ro": "Romanian",
    "hu": "Hungarian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "et": "Estonian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "el": "Greek",
    "he": "Hebrew",
    "fa": "Persian",
    "bn": "Bengali",
    "ta": "Tamil",
    "ur": "Urdu",
    "sr": "Serbian",
    "ka": "Georgian",
    "af": "Afrikaans",
    "sq": "Albanian",
    "ca": "Catalan",
    "eu": "Basque",
    "gl": "Galician",
    "is": "Icelandic",
    "mk": "Macedonian",
    "mt": "Maltese",
    "sw": "Swahili",
    "tl": "Filipino",
    "cy": "Welsh",
    "ga": "Irish",
}


def get_language_name(code: str) -> str:
    """Map an ISO 639-1 language code to its full English name.

    Returns the code itself (capitalized) if not in the known mapping so
    that even unlisted languages get a reasonable label in the AI prompt.
    """
    return _LANGUAGE_NAMES.get(code.lower(), code.capitalize())


# ---------------------------------------------------------------------------
# Rate limiting: 5 auto-translate requests per minute per admin
# ---------------------------------------------------------------------------

_TRANSLATE_RATE_PREFIX = "hosthive:translations:ratelimit:"
_TRANSLATE_RATE_MAX = 5
_TRANSLATE_RATE_WINDOW = 60  # seconds

# In-memory fallback when Redis is unavailable
_memory_rate_limits: Dict[int, List[float]] = {}


async def _check_translate_rate_limit(user_id: int) -> None:
    """Enforce per-admin rate limit.  Redis first, in-memory fallback."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"{_TRANSLATE_RATE_PREFIX}{user_id}"
        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - _TRANSLATE_RATE_WINDOW)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _TRANSLATE_RATE_WINDOW)
        results = await pipe.execute()
        count = results[2]
        await r.aclose()
        if count > _TRANSLATE_RATE_MAX:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {_TRANSLATE_RATE_MAX} auto-translate requests per minute.",
            )
        return
    except HTTPException:
        raise
    except Exception:
        pass

    # In-memory fallback
    now = time.time()
    timestamps = _memory_rate_limits.get(user_id, [])
    timestamps = [t for t in timestamps if t > now - _TRANSLATE_RATE_WINDOW]
    if len(timestamps) >= _TRANSLATE_RATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum {_TRANSLATE_RATE_MAX} auto-translate requests per minute.",
        )
    timestamps.append(now)
    _memory_rate_limits[user_id] = timestamps


# ---------------------------------------------------------------------------
# Flatten / unflatten helpers for dot-notation <-> nested dict
# ---------------------------------------------------------------------------

def _flatten_values(data: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    """Flatten nested dict into {dot.key: value} pairs."""
    result: Dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten_values(value, full_key))
        else:
            result[full_key] = str(value)
    return result


def _unflatten(flat: Dict[str, str]) -> Dict[str, Any]:
    """Convert dot-separated keys back into a nested dict."""
    result: Dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        current = result
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# AI prompt construction
# ---------------------------------------------------------------------------

_TRANSLATION_SYSTEM_PROMPT = (
    "You are a professional translator specializing in software localization. "
    "You translate UI strings for a web hosting control panel called NovaPanel "
    "(also branded HostHive). Always respond with valid JSON only -- no markdown "
    "fences, no explanations, no extra text."
)

_BATCH_SIZE = 50


def _build_translation_prompt(strings: Dict[str, str], language_name: str) -> str:
    """Build the user prompt for one batch of strings."""
    return (
        f"Translate the following UI strings from English to {language_name}. "
        "These are for a web hosting control panel. Keep translations concise and technical. "
        "Return JSON with the same keys.\n\n"
        "Rules:\n"
        "- Keep placeholders like {count}, {name}, {domain}, {username} unchanged.\n"
        "- Do NOT translate brand names: HostHive, NovaPanel.\n"
        "- Do NOT translate technical terms that are universally used in English "
        "(e.g., Docker, WordPress, phpMyAdmin, SSL, DNS, FTP, PHP, CPU, RAM, Cron, TTL).\n"
        "- Return valid JSON with the exact same keys.\n\n"
        f"JSON to translate:\n{json.dumps(strings, ensure_ascii=False, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Request / Response models for auto-translate
# ---------------------------------------------------------------------------

class AutoTranslateRequest(BaseModel):
    target_lang: str = Field(
        ..., min_length=2, max_length=5,
        description="ISO 639-1 language code (e.g. 'de', 'fr')",
    )
    keys: Optional[List[str]] = Field(
        None,
        description="Specific dot-notation keys to translate (e.g. ['common.save', 'dashboard.title'])",
    )
    all_missing: Optional[bool] = Field(
        False,
        description="If true, translate all keys missing in the target locale",
    )


class AutoTranslateResponse(BaseModel):
    target_lang: str
    language_name: str
    translated_count: int
    translations: Dict[str, Any]  # nested dict matching locale structure
    saved: bool


# ---------------------------------------------------------------------------
# POST /translations/auto-translate
# ---------------------------------------------------------------------------

@router.post(
    "/auto-translate",
    response_model=AutoTranslateResponse,
    summary="AI-powered auto-translation of UI strings",
)
async def auto_translate(
    body: AutoTranslateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(_admin_dep),
) -> AutoTranslateResponse:
    """Translate missing or specified UI strings to a target language using AI.

    - Accepts specific ``keys`` **or** ``all_missing: true`` to fill gaps.
    - Batches strings (max 50 per AI call) for efficiency.
    - Merges results into the target locale file on disk.
    - Admin only.  Rate limited to 5 requests per minute.
    """
    await _check_translate_rate_limit(admin.id)

    target_lang = body.target_lang.lower().strip()
    if target_lang == "en":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot auto-translate into English (source language).",
        )

    language_name = get_language_name(target_lang)

    # Load source (English) locale
    en_path = _LOCALES_DIR / "en.json"
    if not en_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="English locale file not found.",
        )
    en_data = json.loads(en_path.read_text(encoding="utf-8"))
    en_flat = _flatten_values(en_data)

    # Load target locale (may not exist yet)
    target_path = _LOCALES_DIR / f"{target_lang}.json"
    target_data: Dict[str, Any] = {}
    if target_path.exists():
        target_data = json.loads(target_path.read_text(encoding="utf-8"))
    target_flat = _flatten_values(target_data)

    # Determine which keys need translation
    if body.all_missing:
        keys_to_translate = [k for k in en_flat if k not in target_flat or target_flat[k] == ""]
    elif body.keys:
        invalid = [k for k in body.keys if k not in en_flat]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Keys not found in English locale: {invalid[:10]}",
            )
        keys_to_translate = body.keys
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'keys' or set 'all_missing' to true.",
        )

    if not keys_to_translate:
        return AutoTranslateResponse(
            target_lang=target_lang,
            language_name=language_name,
            translated_count=0,
            translations={},
            saved=False,
        )

    # Obtain AI client
    ai_client = await get_ai_client_from_settings(db)
    if ai_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not enabled or not configured. Configure AI settings first.",
        )

    # Translate in batches
    all_translated: Dict[str, str] = {}
    try:
        batches = [
            keys_to_translate[i : i + _BATCH_SIZE]
            for i in range(0, len(keys_to_translate), _BATCH_SIZE)
        ]

        for batch_keys in batches:
            batch_strings = {k: en_flat[k] for k in batch_keys}
            prompt = _build_translation_prompt(batch_strings, language_name)

            raw = await ai_client.chat(
                messages=[{"role": "user", "content": prompt}],
                system=_TRANSLATION_SYSTEM_PROMPT,
                json_mode=True,
                max_tokens=4000,
            )
            assert isinstance(raw, str)

            # Parse the AI response
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # Try extracting JSON from markdown fences
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(1))
                else:
                    logger.error("AI returned invalid JSON for translation batch: %s", raw[:300])
                    continue

            # Accept only keys we requested and that are strings
            for key in batch_keys:
                if key in parsed and isinstance(parsed[key], str):
                    all_translated[key] = parsed[key]
                else:
                    logger.warning("AI did not return translation for key: %s", key)
    finally:
        await ai_client.close()

    if not all_translated:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI failed to produce any valid translations.",
        )

    # Merge translated strings into target locale and save
    target_flat.update(all_translated)
    merged = _unflatten(target_flat)
    _write_locale(target_lang, merged)

    translated_nested = _unflatten(all_translated)

    logger.info(
        "Auto-translated %d keys to %s (%s) by admin %s",
        len(all_translated), target_lang, language_name, admin.username,
    )

    return AutoTranslateResponse(
        target_lang=target_lang,
        language_name=language_name,
        translated_count=len(all_translated),
        translations=translated_nested,
        saved=True,
    )
