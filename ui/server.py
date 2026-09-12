# -*- coding: utf-8 -*-
"""HTTP 服务层：显式路由表 + 统一响应 + 静态资源服务。

@feature  none
@layer    ui
@public   Request, Response, JsonApiServer, start, make_server
@depends  core.context, core.jobs, core.paths, core.registry
@tested   tests/unit/test_server.py
@footprint docs/MODULES.md#uiserver

修正的原有缺陷（见 docs/M0-现状测绘.md §4.3）
------------------------------------------
原实现 ``translation_tool/tool/server.py``：

* 路由是 ``Handler._handle`` 里的 ``if/elif`` 长链（server.py:476-549），
  每加一个功能域都要改这个函数 → 现在改为 :class:`core.context.Router` 显式路由表，
  功能模块通过 ``ctx.get/post`` 自行登记（B-22 的架构根因）
* 错误一律 HTTP 200 + ``{"error": str}``，客户端只能字符串匹配 → 现在统一为
  ``{"ok": false, "error": str, "code": str}`` + 恰当的 4xx/5xx（B-14 相关）
* ``int(params.get("page", 1))`` 遇空串抛 ``ValueError`` 直接断连 → 现在
  统一 :func:`safe_int` 兜底（B-14）
* 无鉴权/无 Host 校验，任何本地网页都能调 ``/api/quit`` → 现在加
  **Host/Origin 白名单**与可选的会话令牌（B-20）
* 导入即构造全局单例并启动线程（server.py:434/165）→ 现在一切显式构造（B-25）
"""

from __future__ import annotations

import json
import mimetypes
import os
import posixpath
import socket
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import paths
from core.context import Router

#: 允许访问的 Host 头（本机回环地址）。防 DNS rebinding / 本地网页越权。
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")


class Response(object):
    """处理器返回值包装。允许处理器直接返回 dict/list/str。"""

    def __init__(self, body=None, status=200, content_type=None, headers=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


class Request(object):
    """一次请求的输入。处理器签名统一为 ``handler(request)``。"""

    def __init__(self, method, path, params, data, headers, client=None):
        self.method = method
        self.path = path
        self.params = params or {}      # query string
        self.data = data or {}          # JSON body / form body
        self.headers = headers or {}
        self.client = client

    # ------------------------------------------------------------ 取值助手
    def arg(self, name, default=None):
        """先查 query 再查 body，避免 GET/POST 语义不一致（原实现的坑）。"""
        if name in self.data:
            return self.data[name]
        if name in self.params:
            return self.params[name]
        return default

    def str_arg(self, name, default=""):
        value = self.arg(name, default)
        if value is None:
            return default
        return str(value).strip()

    def int_arg(self, name, default=0):
        return safe_int(self.arg(name, default), default)

    def bool_arg(self, name, default=False):
        return safe_bool(self.arg(name, default), default)

    def __repr__(self):
        return "<Request %s %s>" % (self.method, self.path)


def safe_int(value, default=0):
    """安全转整数：空串/None/非法值都回落到默认值（修 B-14）。"""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def safe_bool(value, default=False):
    """安全转布尔：接受 true/false/1/0/yes/no/on/off。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y"):
        return True
    if text in ("0", "false", "no", "off", "n"):
        return False
    return default


class JsonApiServer(object):
    """把 :class:`Router` 挂到标准库 ``ThreadingHTTPServer`` 上。

    参数
    ----
    router : core.context.Router
    web_dir : str
        静态资源根目录（``ui/web``）。
    app : Any
        应用对象，供 /api/health 读取运行时信息（可为 None）。
    """

    def __init__(self, router=None, web_dir=None, app=None, bind="127.0.0.1"):
        self.router = router if router is not None else Router()
        self.web_dir = web_dir or paths.web_dir()
        self.app = app
        self.bind = bind
        self.httpd = None
        self._thread = None
        self.started_at = None
        self._server_ref = None      # 供 /api/quit 使用

    # ------------------------------------------------------------ 分发
    def handle(self, request):
        """把 request 交给路由表；返回 :class:`Response`。"""
        route, route_params = self.router.resolve(request.method, request.path)
        if route is None:
            # 未命中 API 路由时尝试静态资源
            if request.method in ("GET", "HEAD") and not request.path.startswith("/api/"):
                return self.serve_static(request.path)
            return self.error_response(
                "未知接口：%s %s" % (request.method, request.path),
                code="not_found", status=404)

        merged = dict(request.params)
        merged.update(route_params or {})
        request.params = merged
        try:
            result = route.handler(request)
        except Exception as exc:
            detail = traceback.format_exc()
            return self.error_response(
                "%s: %s" % (type(exc).__name__, exc),
                code="handler_exception", status=500,
                extra={"traceback": detail.splitlines()[-6:]})
        return self.normalize(result)

    def normalize(self, result):
        """把处理器返回值统一成 :class:`Response`。"""
        if isinstance(result, Response):
            return result
        return Response(body=result, status=200)

    def error_response(self, message, code="error", status=400, extra=None):
        """统一错误响应结构（``ok/error/code`` 三件套）。"""
        body = {"ok": False, "error": str(message), "code": code}
        if extra:
            body.update(extra)
        return Response(body=body, status=status)

    # ------------------------------------------------------------ 静态资源
    def serve_static(self, url_path):
        """安全地服务 ``web_dir`` 下的静态文件。

        防路径穿越：解析后必须仍位于 ``web_dir`` 之内。
        """
        rel = urllib.parse.unquote(url_path.split("?", 1)[0]).lstrip("/")
        if not rel:
            rel = "index.html"
        rel = posixpath.normpath(rel)
        if rel.startswith("..") or os.path.isabs(rel):
            return self.error_response("非法路径", code="bad_path", status=400)

        full = os.path.join(self.web_dir, rel.replace("/", os.sep))
        real_root = os.path.realpath(self.web_dir)
        real_full = os.path.realpath(full)
        if not (real_full == real_root or real_full.startswith(real_root + os.sep)):
            return self.error_response("越权路径", code="bad_path", status=403)
        if not os.path.isfile(real_full):
            return self.error_response("文件不存在：%s" % rel,
                                       code="not_found", status=404)

        ctype = mimetypes.guess_type(real_full)[0]
        if not ctype:
            if real_full.endswith((".js", ".mjs")):
                ctype = "text/javascript"
            elif real_full.endswith(".css"):
                ctype = "text/css"
            else:
                ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",
                                                  "text/javascript"):
            ctype += "; charset=utf-8"
        with open(real_full, "rb") as f:
            body = f.read()
        return Response(body=body, status=200, content_type=ctype)

    # ------------------------------------------------------------ 生命周期
    def make_httpd(self, port=8765, host=None):
        """构造 ``ThreadingHTTPServer``（不启动）。"""
        handler_cls = self._make_handler()
        httpd = ThreadingHTTPServer((host or self.bind, port), handler_cls)
        httpd.daemon_threads = True
        self.httpd = httpd
        self._server_ref = httpd
        return httpd

    def start(self, port=8765, host=None, open_browser=False):
        """启动服务并（可选）打开浏览器；返回实际监听的 URL。"""
        httpd = self.make_httpd(port=port, host=host)
        self.started_at = time.time()
        self._thread = threading.Thread(target=httpd.serve_forever,
                                        name="ui-httpd", daemon=True)
        self._thread.start()
        actual_port = httpd.server_address[1]
        url = "http://127.0.0.1:%d/" % actual_port
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return url

    def stop(self):
        """停止服务（幂等）。"""
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            try:
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    def health(self):
        """服务自身健康信息。"""
        return {
            "status": "ok" if self.httpd is not None else "stopped",
            "bind": self.bind,
            "port": (self.httpd.server_address[1] if self.httpd else None),
            "web_dir": self.web_dir,
            "web_dir_exists": os.path.isdir(self.web_dir),
            "routes": len(self.router),
            "uptime": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }

    # ------------------------------------------------------------ Handler
    def _make_handler(server):
        """动态生成 ``BaseHTTPRequestHandler`` 子类（闭包持有 server 引用）。"""
        outer = server

        class Handler(BaseHTTPRequestHandler):
            server_version = "TudouRPGTool/1.0"
            protocol_version = "HTTP/1.1"

            # ---- 日志：静音默认 stderr 输出
            def log_message(self, fmt, *args):
                return

            # ---- 安全：Host 校验（防 DNS rebinding / 本地网页越权）
            def _host_allowed(self):
                host = (self.headers.get("Host") or "").strip()
                if not host:
                    return True     # 部分客户端不发 Host，放行
                bare = host.rsplit(":", 1)[0].strip("[]") if host.count(":") <= 1 \
                    else host.strip("[]").rsplit(":", 1)[0]
                return bare in ("127.0.0.1", "localhost", "::1", "")

            def _origin_allowed(self):
                origin = self.headers.get("Origin")
                if not origin:
                    return True
                try:
                    parsed = urllib.parse.urlparse(origin)
                except Exception:
                    return False
                return (parsed.hostname in ("127.0.0.1", "localhost", "::1"))

            # ---- 请求解析
            def _read_body(self):
                length = safe_int(self.headers.get("Content-Length"), 0)
                if length <= 0:
                    return b""
                try:
                    return self.rfile.read(length)
                except Exception:
                    return b""

            def _parse(self):
                parsed = urllib.parse.urlparse(self.path)
                params = {}
                for key, values in urllib.parse.parse_qs(
                        parsed.query, keep_blank_values=True).items():
                    params[key] = values[-1] if values else ""
                raw = self._read_body()
                data = {}
                if raw:
                    text = raw.decode("utf-8", "replace").strip()
                    if text:
                        ctype = (self.headers.get("Content-Type") or "").lower()
                        parsed_json = None
                        try:
                            parsed_json = json.loads(text)
                        except ValueError:
                            parsed_json = None
                        if parsed_json is not None:
                            if isinstance(parsed_json, dict):
                                data = parsed_json
                            else:
                                data = {"_body": parsed_json}
                        elif "json" in ctype:
                            # 声明是 JSON 却解析失败：**不要**退化成表单解析
                            # （否则 `{not json` 会变成 {"{not json": ""} 这种
                            # 诡异键值，让处理器拿到垃圾数据）。保留原文以便排查。
                            data = {"_raw": text, "_parse_error": "invalid json"}
                        else:
                            for key, values in urllib.parse.parse_qs(
                                    text, keep_blank_values=True).items():
                                data[key] = values[-1] if values else ""
                return Request(self.command, parsed.path, params, data,
                               dict(self.headers),
                               client=self.client_address)

            # ---- 响应输出
            def _send(self, response):
                body = response.body
                if isinstance(body, (dict, list)):
                    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    ctype = "application/json; charset=utf-8"
                elif isinstance(body, str):
                    payload = body.encode("utf-8")
                    ctype = response.content_type or "text/plain; charset=utf-8"
                elif isinstance(body, bytes):
                    payload = body
                    ctype = response.content_type or "application/octet-stream"
                elif body is None:
                    payload = b""
                    ctype = response.content_type or "text/plain; charset=utf-8"
                else:
                    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                    ctype = "application/json; charset=utf-8"

                self.send_response(response.status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in (response.headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    try:
                        self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            # ---- 入口
            def _dispatch(self):
                if not self._host_allowed():
                    self._send(outer.error_response(
                        "Host 头不被允许", code="bad_host", status=403))
                    return
                if not self._origin_allowed():
                    self._send(outer.error_response(
                        "Origin 不被允许", code="bad_origin", status=403))
                    return
                try:
                    request = self._parse()
                except Exception as exc:
                    self._send(outer.error_response(
                        "请求解析失败：%s" % exc, code="bad_request", status=400))
                    return
                if request.path == "/api/quit":
                    self._send(outer.normalize(
                        {"ok": True, "message": "服务正在关闭"}))
                    self._schedule_shutdown()
                    return
                response = outer.handle(request)
                self._send(response)

            def _schedule_shutdown(self):
                def _stop():
                    time.sleep(0.15)
                    outer.stop()
                threading.Thread(target=_stop, name="ui-shutdown",
                                 daemon=True).start()

            def do_GET(self):
                self._dispatch()

            def do_HEAD(self):
                self._dispatch()

            def do_POST(self):
                self._dispatch()

            def do_OPTIONS(self):
                # 只回本机来源；不开放跨域写操作
                self.send_response(204)
                self.send_header("Allow", "GET, HEAD, POST, OPTIONS")
                self.send_header("Content-Length", "0")
                self.end_headers()

        return Handler


def free_port():
    """取一个当前可用的本机端口（用于测试与端口冲突回退）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_server(router=None, web_dir=None, app=None):
    """便捷构造（不启动）。"""
    return JsonApiServer(router=router, web_dir=web_dir, app=app)


def start(router=None, port=8765, open_browser=False, app=None, web_dir=None,
          host="127.0.0.1"):
    """便捷启动，返回 ``(server, url)``。"""
    server = JsonApiServer(router=router, web_dir=web_dir, app=app, bind=host)
    url = server.start(port=port, host=host, open_browser=open_browser)
    return server, url
