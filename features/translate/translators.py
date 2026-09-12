# -*- coding: utf-8 -*-
"""
Translation backends (stdlib only): Google free API, OpenAI-compatible, DeepL.

@feature  translate
@layer    features
@public   build_translator, translate_entries, TranslateError,
@public   TruncatedError, GoogleTranslator, OpenAICompatibleTranslator,
@public   DeepLTranslator, _http
@depends  core.textutil, core.safety.backup
@tested   tests/features/translate/
@footprint docs/FEATURES.md#translate
@note     vendored：来自 rpgmaker_translation_tool/tool/translators.py。
@note     M3a 接线时改为按功能模块暴露 register(ctx)。
"""

from __future__ import annotations

import json
import re
import collections
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class TranslateError(Exception):
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


class TruncatedError(TranslateError):
    """Model output could not be parsed (likely truncated or too large)."""


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _clean_json(raw):
    """Strip code fences and tolerate trailing commas (common LLM mistakes)."""
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    for _ in range(4):
        new = _TRAILING_COMMA_RE.sub(r"\1", text)
        if new == text:
            break
        text = new
    return text


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _http(method, url, params=None, form=None, json_body=None, headers=None, timeout=40):
    """Minimal HTTP helper.  Returns (status, body-bytes); network failures raise."""
    if params:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(params, doseq=True)
    body = None
    headers = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        body = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read(500)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TranslateError("网络请求失败: %s" % e)


class GoogleTranslator:
    name = "google"

    def __init__(self, batch_size=50):
        self.batch_size = batch_size

    def _request(self, q, dst):
        status, body = _http(
            "POST",
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "dt": "t", "sl": "auto", "tl": dst},
            form={"q": q},
            timeout=40,
        )
        if status != 200:
            raise TranslateError("Google 翻译请求失败 (HTTP %d)" % status)
        js = json.loads(body.decode("utf-8", "replace"))
        if not isinstance(js, list) or not js:
            raise TranslateError("Google 翻译返回格式异常")
        return "".join(p[0] for p in js[0] if isinstance(p, list) and p)

    def translate_batch(self, texts, src, dst):
        out = []
        chunk = []
        chars = 0
        for t in texts:
            if chunk and (len(chunk) >= self.batch_size or chars + len(t) > 3000):
                out.extend(self._translate_chunk(chunk, dst))
                chunk = []
                chars = 0
            chunk.append(t)
            chars += len(t)
        if chunk:
            out.extend(self._translate_chunk(chunk, dst))
        return out

    def _translate_chunk(self, chunk, dst):
        joined = "\n".join(chunk)
        try:
            lines = self._request(joined, dst).split("\n")
            if len(lines) == len(chunk):
                return lines
        except TranslateError:
            pass
        # Line count mismatch: split the batch in half and retry, never
        # degrading to one request per line (unless a single line remains).
        if len(chunk) > 1:
            mid = len(chunk) // 2
            return (self._translate_chunk(chunk[:mid], dst) +
                    self._translate_chunk(chunk[mid:], dst))
        return [self._request(chunk[0], dst)]


class OpenAICompatibleTranslator:
    name = "openai"

    def __init__(self, base_url, api_key, model, batch_size=25, temperature=0.1,
                 timeout=120, json_mode=True, prompt=None, max_tokens_cap=8192,
                 disable_thinking=True):
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.batch_size = max(1, int(batch_size))
        self.temperature = temperature
        self.timeout = timeout
        self.json_mode = json_mode
        self.prompt = prompt
        self.max_tokens_cap = max_tokens_cap
        self.disable_thinking = disable_thinking

    def _endpoints(self):
        if self.base_url.endswith("/chat/completions"):
            return [self.base_url]
        if self.base_url.endswith("/v1"):
            return [self.base_url + "/chat/completions"]
        return [self.base_url + "/chat/completions", self.base_url + "/v1/chat/completions"]

    def _call(self, texts, src, dst, use_json_mode):
        numbered = "\n".join("%d: %s" % (i, t) for i, t in enumerate(texts, 1))
        system = self.prompt or (
            "You are a professional game localizer for RPG Maker games. "
            "Translate each line from %s to %s.\n"
            "Rules:\n"
            "- Translate the meaning naturally; keep proper nouns unless clearly translatable.\n"
            "- PRESERVE every control code and markup tag EXACTLY and in the same position "
            "(backslash codes like \\V[3], \\N[1], \\C[16], \\\\, \\>, \\}, \\., \\!, and <...> blocks).\n"
            "- Preserve line breaks and the number of lines exactly.\n"
            "- If a line is empty or has nothing to translate, output an empty string.\n"
            "- Return ONLY a valid JSON object mapping the 1-based line number to the translated line, "
            'e.g. {"1":"...","2":"..."} with exactly %d entries.'
            % (src or "auto", dst, len(texts))
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": numbered},
            ],
            "temperature": self.temperature,
        }
        est = sum(len(t) for t in texts)
        cap = int(getattr(self, "max_tokens_cap", 8192) or 8192)
        payload["max_tokens"] = min(cap, max(2000, est * 2 + 1500))
        is_deepseek = "deepseek" in (self.model or "").lower()
        if is_deepseek and self.disable_thinking:
            # deepseek-v4 models default to thinking mode, which makes batch
            # translation extremely slow / prone to timeout.
            payload["thinking"] = {"type": "disabled"}
        if use_json_mode and not is_deepseek:
            payload["response_format"] = {"type": "json_object"}
        headers = {}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        endpoints = self._endpoints()
        last_err = None
        for url in endpoints:
            try:
                status, body = _http("POST", url, json_body=payload,
                                     headers=headers, timeout=self.timeout)
                if status == 404 and url != endpoints[-1]:
                    continue
                if status == 400 and use_json_mode:
                    return self._call(texts, src, dst, False)
                if status == 429:
                    raise TranslateError("接口限流(429)，已自动等待后重试")
                if status in (400, 401, 402, 403, 413):
                    detail = body[:300].decode("utf-8", "replace")
                    if status == 402:
                        raise TranslateError("接口返回 HTTP 402（可能是账户余额不足）: %s" % detail, retryable=False)
                    if status in (401, 403):
                        raise TranslateError("接口返回 HTTP %d（可能是 Key 无效或无权限）: %s" % (status, detail), retryable=False)
                    if status == 404:
                        raise TranslateError("接口地址不存在(404)，请检查 base_url 是否正确: %s" % detail, retryable=False)
                    raise TruncatedError("接口返回 HTTP %d（批次过大或参数不符，已自动缩小重试）: %s" % (status, detail))
                if status != 200:
                    raise TranslateError("接口返回 HTTP %d: %s" % (status, body[:300].decode("utf-8", "replace")), retryable=status >= 500)
                data = json.loads(body.decode("utf-8", "replace"))
                content = data["choices"][0]["message"]["content"]
                try:
                    return self._parse(content, len(texts))
                except TranslateError as e:
                    raise TruncatedError("模型返回无法解析（可能被截断，已自动缩小重试）: %s" % e)
            except TranslateError:
                raise
            except Exception as e:
                last_err = e
        raise TranslateError("OpenAI 兼容接口请求失败: %s" % last_err)

    def _parse(self, content, expected):
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            start, end = text.index("{"), text.rindex("}")
            obj = json.loads(_clean_json(text[start:end + 1]))
            if isinstance(obj, dict):
                vals = obj.get("translations")
                if not isinstance(vals, list):
                    # 1-based dict form, e.g. {"1":"...","2":"..."}
                    items = []
                    for k, v in obj.items():
                        if isinstance(k, str) and k.isdigit():
                            items.append((int(k), v))
                    items.sort()
                    vals = [v for _, v in items]
                if isinstance(vals, list) and all(isinstance(v, str) for v in vals):
                    if len(vals) != expected:
                        raise TranslateError("模型返回条数不符(%d != %d)" % (len(vals), expected))
                    return vals
        except TranslateError:
            raise
        except Exception:
            pass
        lines = []
        for line in text.splitlines():
            m = re.match(r"^\s*(\d+)\s*[:：.]\s*(.*)$", line)
            if m:
                lines.append((int(m.group(1)), m.group(2).strip()))
        idxs = [i for i, _ in lines]
        if len(lines) == expected and (idxs == list(range(1, expected + 1)) or
                                       idxs == list(range(expected))):
            return [t for _, t in lines]
        raise TranslateError("无法解析模型返回内容")

    def translate_batch(self, texts, src, dst):
        out = []
        for chunk in _chunks(texts, self.batch_size):
            out.extend(self._translate_chunk(list(chunk), src, dst))
        return out

    def _translate_chunk(self, chunk, src, dst):
        try:
            return self._call(chunk, src, dst, self.json_mode)
        except TruncatedError:
            if len(chunk) > 1:
                mid = len(chunk) // 2
                return (self._translate_chunk(chunk[:mid], src, dst) +
                        self._translate_chunk(chunk[mid:], src, dst))
            raise


class DeepLTranslator:
    name = "deepl"

    def __init__(self, api_key, batch_size=40, pro=False):
        self.api_key = api_key
        self.batch_size = batch_size
        self.url = ("https://api.deepl.com/v2/translate" if pro
                    else "https://api-free.deepl.com/v2/translate")

    def _lang(self, code):
        m = {"zh-cn": "ZH", "zh": "ZH", "zh-tw": "ZH-HANT", "ja": "JA", "en": "EN",
             "ko": "KO", "fr": "FR", "de": "DE", "ru": "RU", "es": "ES"}
        return m.get((code or "").lower(), (code or "EN").upper())

    def translate_batch(self, texts, src, dst):
        out = []
        for chunk in _chunks(texts, self.batch_size):
            form = {"auth_key": self.api_key, "target_lang": self._lang(dst), "text": list(chunk)}
            if src:
                form["source_lang"] = self._lang(src)
            status, body = _http("POST", self.url, form=form, timeout=60)
            if status != 200:
                raise TranslateError("DeepL 请求失败 (HTTP %d): %s" % (status, body[:300].decode("utf-8", "replace")))
            js = json.loads(body.decode("utf-8", "replace"))
            items = js.get("translations") or []
            if len(items) != len(chunk):
                raise TranslateError("DeepL 返回条数不符")
            out.extend(t["text"] for t in items)
        return out


def build_translator(cfg):
    """Create a translator instance from a config dict."""
    kind = (cfg.get("engine") or "google").lower()
    if kind == "google":
        return GoogleTranslator(batch_size=cfg.get("batch_size", 50))
    if kind in ("openai", "ollama", "compatible"):
        base = cfg.get("base_url") or ("http://localhost:11434/v1" if kind == "ollama"
                                       else "https://api.openai.com/v1")
        model = cfg.get("model") or ("qwen2.5:7b" if kind == "ollama" else "gpt-4o-mini")
        return OpenAICompatibleTranslator(
            base_url=base,
            api_key=cfg.get("api_key", ""),
            model=model,
            batch_size=cfg.get("batch_size", 25),
            max_tokens_cap=cfg.get("max_tokens_cap", 8192),
            disable_thinking=bool(cfg.get("disable_thinking", True)),
            temperature=cfg.get("temperature", 0.1),
            timeout=cfg.get("timeout", 90),
            json_mode=bool(cfg.get("json_mode", True)),
            prompt=cfg.get("prompt") or None,
        )
    if kind == "deepl":
        return DeepLTranslator(cfg.get("api_key", ""), pro=bool(cfg.get("deepl_pro", False)))
    raise TranslateError("未知翻译引擎: %s" % kind)


def translate_entries(session, cfg, progress_cb=None, cancel_event=None, only_errors=False):
    """Translate all pending entries; returns (done, failed) counts."""
    from core.textutil import collect_segments, rebuild

    translator = build_translator(cfg)
    src = cfg.get("src_lang") or "auto"
    dst = cfg.get("dst_lang") or "zh-CN"
    redo = bool(cfg.get("redo", False))

    # Deduplicate: translate each unique original once, then fan the result
    # out to every entry with the same text.
    pending_by_orig = {}
    for e in session.entries.values():
        if only_errors and e["status"] != "error":
            continue
        if e["status"] == "error":
            e["status"] = "pending"
            e["error"] = ""
        if e["status"] == "pending" or (redo and e["status"] in ("translated", "error")):
            orig = e["original"]
            if not orig:
                continue
            cached = session.cache.get(orig)
            if cached and not redo:
                e["translated"] = cached
                e["status"] = "translated"
                continue
            pending_by_orig.setdefault(orig, []).append(e)

    unique_groups = [{"original": orig, "entries": lst}
                     for orig, lst in pending_by_orig.items()]
    total_entries = sum(len(g["entries"]) for g in unique_groups)
    done = 0
    failed = 0
    batch = max(1, int(cfg.get("entries_per_batch") or cfg.get("batch_size") or 10))
    chunk_timeout = int(cfg.get("chunk_timeout", 120))
    lock = threading.Lock()
    error_counter = collections.Counter()
    import concurrent.futures

    def translate_with_watchdog(segments):
        """Run one translator call with a hard timeout so a hung request
        can never freeze the whole job."""
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(translator.translate_batch, segments, src, dst)
        try:
            return fut.result(timeout=chunk_timeout)
        except concurrent.futures.TimeoutError:
            raise TranslateError("单个批次超过 %d 秒未返回，已重试" % chunk_timeout)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def work(chunk):
        nonlocal done, failed
        if cancel_event and cancel_event.is_set():
            return 0, sum(len(g["entries"]) for g in chunk)
        texts = [g["original"] for g in chunk]
        segments, slices = collect_segments(texts)
        translated = []
        if segments:
            for attempt in range(3):
                if cancel_event and cancel_event.is_set():
                    return 0, sum(len(g["entries"]) for g in chunk)
                try:
                    translated = translate_with_watchdog(segments)
                    break
                except Exception as ex:
                    retryable = getattr(ex, "retryable", True)
                    if attempt == 2 or not retryable:
                        msg = str(ex)[:200]
                        print("[翻译错误] %s" % ex, flush=True)
                        with lock:
                            for g in chunk:
                                for e in g["entries"]:
                                    e["status"] = "error"
                                    e["error"] = str(ex)
                            error_counter[msg] += sum(len(g["entries"]) for g in chunk)
                        return (sum(len(g["entries"]) for g in chunk),
                                sum(len(g["entries"]) for g in chunk))
                    time.sleep((3, 10, 30)[attempt])
        if cancel_event and cancel_event.is_set():
            return 0, sum(len(g["entries"]) for g in chunk)
        rebuilt = rebuild(texts, slices, translated) if segments else texts
        with lock:
            for g, t in zip(chunk, rebuilt):
                if t.strip():
                    for e in g["entries"]:
                        e["translated"] = t
                        e["status"] = "translated"
                        e["error"] = ""
                    session.cache[g["original"]] = t
                else:
                    msg = "译文为空"
                    for e in g["entries"]:
                        e["status"] = "error"
                        e["error"] = msg
                    error_counter[msg] += len(g["entries"])
        return 0, sum(len(g["entries"]) for g in chunk)

    workers = max(1, int(cfg.get("workers", 4)))
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(work, list(chunk)) for chunk in _chunks(unique_groups, batch)]
    try:
        pending = set(futs)
        while pending:
            if cancel_event and cancel_event.is_set():
                break
            finished, pending = concurrent.futures.wait(
                pending, timeout=1.0, return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in finished:
                try:
                    f_err, f_done = fut.result()
                    failed += f_err
                    done += f_done
                except Exception:
                    failed += batch
                    done += batch
            if progress_cb:
                if finished:
                    progress_cb(min(done, total_entries), total_entries, failed)
                elif pending:
                    progress_cb(min(done, total_entries), total_entries, failed,
                                "等待接口返回中（已启动 %d 个批次）…" % len(pending))
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    print("[翻译完成] 成功 %d 条，失败 %d 条" % (done - failed, failed), flush=True)
    return done, failed, [{"msg": m, "count": c} for m, c in error_counter.most_common(5)]
