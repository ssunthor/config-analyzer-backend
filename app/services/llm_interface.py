# llm_interface.py

import asyncio
import json
import logging
import time
import urllib3
from typing import AsyncGenerator, List, Dict, Any, Optional

import httpx
import requests
from requests.exceptions import RequestException

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class KeycloakTokenManager:
    _instances = {}

    def __new__(cls, auth_url: str, client_id: str, client_secret: str, ssl_verify: bool = False):
        key = (auth_url, client_id)
        if key not in cls._instances:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instances[key] = instance
        return cls._instances[key]

    def __init__(self, auth_url: str, client_id: str, client_secret: str, ssl_verify: bool = False):
        if getattr(self, '_initialized', False):
            return

        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.ssl_verify = ssl_verify
        self.token = None
        self.expires_at = 0
        self._initialized = True
        logger.debug(f"KeycloakTokenManager initialized: auth_url={auth_url} client_id={client_id}")

    def get_token(self) -> Optional[str]:
        if not self.token or time.time() > (self.expires_at - 60):
            logger.debug(
                f"Keycloak token expired or missing — refreshing "
                f"(auth_url={self.auth_url} client_id={self.client_id})"
            )
            self._refresh_token()
        else:
            remaining = self.expires_at - time.time()
            logger.debug(f"Using cached Keycloak token (expires in {remaining:.0f}s)")
        return self.token

    def _refresh_token(self):
        logger.info(f"Fetching new Keycloak token: url={self.auth_url} client_id={self.client_id}")
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials"
        }
        try:
            response = requests.post(self.auth_url, data=payload, verify=self.ssl_verify, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            self.token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 300)
            self.expires_at = time.time() + expires_in
            logger.info(f"Keycloak token acquired successfully (expires_in={expires_in}s)")
        except Exception as e:
            logger.error(f"Failed to fetch Keycloak token from {self.auth_url}: {e}")
            raise


class vLLMClient:
    def __init__(self, config: Dict[str, Any], auth_cfg: Optional[Dict[str, Any]] = None, api_key: Optional[str] = None):
        self.model_name = config["model"]
        # Accept either a full api_url or base_url + api_endpoint
        if "api_url" in config:
            self.api_url = config["api_url"]
        else:
            self.base_url = config["base_url"].rstrip('/')
            self.api_endpoint = config["api_endpoint"]
            self.api_url = f"{self.base_url}{self.api_endpoint}"
        self.chat_timeout = config["chat_timeout_seconds"]
        self.max_tokens = config["num_ctx"]
        self.ssl_verify = config["ssl_verify"]
        self.enable_thinking = config["enable_thinking"]

        self.session = requests.Session()
        self.token_manager = None
        self.api_key = api_key

        if auth_cfg and auth_cfg.get("auth_url") and auth_cfg.get("client_id") and auth_cfg.get("client_secret"):
            self.token_manager = KeycloakTokenManager(
                auth_url=auth_cfg["auth_url"],
                client_id=auth_cfg["client_id"],
                client_secret=auth_cfg["client_secret"],
                ssl_verify=self.ssl_verify
            )
            auth_mode = "keycloak"
        elif api_key:
            auth_mode = "api_key"
        else:
            auth_mode = "none"

        logger.info(
            f"vLLMClient initialized: endpoint={self.api_url} model={self.model_name} "
            f"auth={auth_mode} timeout={self.chat_timeout}s ssl_verify={self.ssl_verify} "
            f"max_tokens={self.max_tokens} enable_thinking={self.enable_thinking}"
        )

    def _get_auth_headers(self) -> Dict[str, str]:
        headers = {}
        if self.token_manager:
            try:
                token = self.token_manager.get_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    logger.debug("Auth header set via Keycloak token manager")
                else:
                    logger.warning("Keycloak token manager returned no token")
            except Exception as e:
                logger.error(f"Failed to get Keycloak token for request: {e}")
        elif self.api_key:
            if self.api_key.lower().startswith("bearer "):
                headers["Authorization"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
            logger.debug("Auth header set via static API key")
        else:
            logger.debug("No auth configured — sending request without Authorization header")
        return headers

    def get_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        json_mode: bool = True,
        max_retries: int = 3,
        max_tokens: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        effective_max_tokens = max_tokens or self.max_tokens
        logger.debug(
            f"LLM request (sync): model={self.model_name} messages={len(messages)} "
            f"temperature={temperature} max_tokens={effective_max_tokens} json_mode={json_mode}"
        )

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "stream": False
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(f"POST {self.api_url} (attempt {attempt}/{max_retries})")
                t0 = time.time()
                response = self.session.post(
                    self.api_url,
                    json=payload,
                    headers=self._get_auth_headers(),
                    timeout=self.chat_timeout,
                    verify=self.ssl_verify,
                )
                elapsed = time.time() - t0
                logger.debug(f"HTTP {response.status_code} in {elapsed:.2f}s")
                response.raise_for_status()
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    msg = data["choices"][0]["message"]
                    content_len = len(msg.get("content", ""))
                    logger.debug(
                        f"LLM response OK: role={msg.get('role')} content_len={content_len} chars "
                        f"(elapsed={elapsed:.2f}s)"
                    )
                    return msg
                logger.warning("LLM response contained no choices")
                return None
            except RequestException as e:
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.warning(
                        f"vLLM request failed (attempt {attempt}/{max_retries}): {e} — "
                        f"retrying in {sleep_time}s"
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(f"vLLM request failed after {max_retries} attempts: {e}")
                    return None

    async def get_chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        effective_max_tokens = max_tokens or self.max_tokens
        logger.debug(
            f"LLM stream request: model={self.model_name} messages={len(messages)} "
            f"temperature={temperature} max_tokens={effective_max_tokens}"
        )

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
            "stream": True,
        }
        if self.enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}

        headers = {"Content-Type": "application/json"}
        headers.update(self._get_auth_headers())

        chunk_count = 0
        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=self.chat_timeout, verify=self.ssl_verify) as client:
                async with client.stream("POST", self.api_url, json=payload, headers=headers) as response:
                    logger.debug(f"LLM stream connected: HTTP {response.status_code}")
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            line = line[6:]
                            if line == "[DONE]":
                                elapsed = time.time() - t0
                                logger.debug(
                                    f"LLM stream complete: {chunk_count} chunks in {elapsed:.2f}s"
                                )
                                return
                            try:
                                data = json.loads(line)
                                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    chunk_count += 1
                                    yield content
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(
                f"LLM stream error after {chunk_count} chunks ({elapsed:.2f}s): {e}"
            )
            raise
