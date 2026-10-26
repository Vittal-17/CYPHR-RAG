import config
from fastapi import FastAPI, UploadFile, File, HTTPException, Response, Depends, Cookie, Header
from fastapi.middleware.cors import CORSMiddleware
from database import check_db_connection, users_collection, chats_collection, collection
from llm_providers import get_public_provider_catalog
from services import process_and_store_document, generate_chat_response, generate_auto_title
from auth import get_password_hash, verify_password, create_access_token, decode_access_token
import uvicorn
import uuid
import re
from pydantic import BaseModel, EmailStr
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
import httpx
import secrets
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
import logging
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse
from fastapi import Request

RATE_LIMIT_LOGIN = os.getenv("RATE_LIMIT_LOGIN", "10/minute")
RATE_LIMIT_REGISTER = os.getenv("RATE_LIMIT_REGISTER", "5/hour")
RATE_LIMIT_GOOGLE = os.getenv("RATE_LIMIT_GOOGLE", "20/minute")
RATE_LIMIT_UPLOAD = os.getenv("RATE_LIMIT_UPLOAD", "10/hour")
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "20/minute")
RATE_LIMIT_GENERAL = os.getenv("RATE_LIMIT_GENERAL", "100/minute")

def dynamic_key_func(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
    if token:
        try:
            from auth import decode_access_token
            payload = decode_access_token(token)
            if payload and payload.get("sub"):
                return f"user:{payload['sub']}"
        except Exception:
            pass
    return f"ip:{get_remote_address(request)}"

limiter = Limiter(key_func=dynamic_key_func)

def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    path = request.url.path
    if "/api/login" in path:
        msg = "Too many login attempts. Please try again later."
    elif "/api/register" in path:
        msg = "Too many registrations. Please try again later."
    elif "/api/auth/google" in path:
        msg = "Too many auth attempts. Please try again later."
    elif "/upload" in path:
        msg = "Upload rate limit exceeded. Please try again later."
    elif "/chat" in path:
        msg = "Too many chat requests. Please try again later."
    else:
        msg = "Too many requests. Please try again later."

    response = JSONResponse(
        {"detail": msg}, status_code=429
    )

    current_limit = getattr(request.state, "view_rate_limit", None)
    if current_limit:
        import time
        import math
        try:
            window_stats = request.app.state.limiter.limiter.get_window_stats(current_limit[0], *current_limit[1])
            reset_time = window_stats[0]
            retry_after = max(1, math.ceil(reset_time - time.time()))
            response.headers["Retry-After"] = str(retry_after)
        except Exception:
            pass

    response = request.app.state.limiter._inject_headers(
        response, getattr(request.state, "view_rate_limit", None)
    )
    return response

@asynccontextmanager
async def lifespan(app: FastAPI):
    await check_db_connection()
    yield
    from embeddings import close_embedding_provider
    await close_embedding_provider()

app = FastAPI(title="CYPHR Backend", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."}
    )

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "CYPHR-RAG"}

# Read environment variables
IS_PRODUCTION = os.getenv("ENVIRONMENT") == "production"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")


if IS_PRODUCTION:
    COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "none").lower()
else:
    COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()

if COOKIE_SAMESITE not in ["lax", "strict", "none"]:
    raise ValueError("COOKIE_SAMESITE must be 'lax', 'strict', or 'none'")
if COOKIE_SAMESITE == "none" and not IS_PRODUCTION:
    COOKIE_SAMESITE = "lax"

FRONTEND_URL = os.getenv("FRONTEND_URL")
if not FRONTEND_URL:
    if IS_PRODUCTION:
        raise ValueError("FATAL: FRONTEND_URL environment variable must be set in production")
    FRONTEND_URL = "http://localhost:5173"
FRONTEND_URL = FRONTEND_URL.rstrip('/')
ALLOWED_ORIGIN = FRONTEND_URL

from urllib.parse import urlparse

VERCEL_PROJECT_NAME = os.getenv("VERCEL_PROJECT_NAME", "cyphr-rag").strip()
_escaped_vercel_project = re.escape(VERCEL_PROJECT_NAME)
VERCEL_ORIGIN_REGEX = re.compile(rf"^https://({_escaped_vercel_project}|{_escaped_vercel_project}-[a-zA-Z0-9_\-]+)\.vercel\.app$")

def _extract_hostname(origin_or_referer: str) -> str:
    if not origin_or_referer:
        return ""
    try:
        parsed = urlparse(origin_or_referer)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""

def get_cookie_samesite(request: Request | None = None) -> str:
    """
    Dynamically determine cookie SameSite policy:
    - If request comes from cyphr.cfd (apex or subdomains): returns 'lax' (same-site, immune to 3rd-party cookie blocking).
    - If request comes from localhost / local dev / not production: returns 'lax' (or explicit override).
    - If request comes from configured *.vercel.app (or external production origin): returns 'none'.
    - If COOKIE_SAMESITE is explicitly configured to 'strict' or modified by tests, preserve it.
    """
    if COOKIE_SAMESITE == "strict":
        return "strict"
    if request:
        origin = request.headers.get("origin") or request.headers.get("referer") or ""
        host = _extract_hostname(origin)
        if host == "cyphr.cfd" or host.endswith(".cyphr.cfd"):
            return "lax"
        if host in ("localhost", "127.0.0.1") or not IS_PRODUCTION:
            return COOKIE_SAMESITE
        return "none"
    return COOKIE_SAMESITE

def get_allowed_origins() -> list[str]:
    origins = {
        ALLOWED_ORIGIN,
        "https://cyphr.cfd",
        "https://www.cyphr.cfd",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
        "http://127.0.0.1",
    }
    if not IS_PRODUCTION:
        origins.update({
            "http://cyphr.cfd",
            "http://www.cyphr.cfd",
        })
    addl = os.getenv("ADDITIONAL_ALLOWED_ORIGINS")
    if addl:
        for o in addl.split(","):
            clean_o = o.strip().rstrip("/")
            if clean_o:
                # In production, block insecure unencrypted HTTP origins for remote hosts
                if IS_PRODUCTION and not clean_o.startswith("https://"):
                    parsed = urlparse(clean_o)
                    if parsed.hostname not in ("localhost", "127.0.0.1"):
                        logger.warning("Ignoring insecure plaintext HTTP origin in production: %s", clean_o)
                        continue
                origins.add(clean_o)
    return [o.rstrip("/") for o in origins if o]

def is_origin_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    clean_origin = origin.rstrip("/")
    if clean_origin == ALLOWED_ORIGIN or clean_origin in get_allowed_origins():
        return True
    if VERCEL_ORIGIN_REGEX.match(clean_origin):
        return True
    return False

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import secrets
import hmac

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            origin = request.headers.get("origin")
            origin = origin.rstrip('/') if origin else origin
            if origin and not is_origin_allowed(origin):
                logger.warning("CSRF validation failed: invalid origin")
                return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})

            csrf_cookie = request.cookies.get("csrf_token")
            csrf_header = request.headers.get("x-csrf-token")

            # Check if this request is using Bearer token without any cookies (fallback mirror mode)
            auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
            has_bearer = bool(auth_header.lower().startswith("bearer "))
            has_cookies = bool(request.cookies.get("access_token") or csrf_cookie)

            # If request relies on cookies (standard mode) or does not have a Bearer token:
            # strictly enforce double-submit CSRF cookie + header check.
            if has_cookies or not has_bearer:
                if not csrf_cookie:
                    logger.warning("CSRF validation failed: missing cookie")
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})
                if not csrf_header:
                    logger.warning("CSRF validation failed: missing header")
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})
                if not hmac.compare_digest(csrf_cookie, csrf_header):
                    logger.warning(
                        "CSRF validation failed: token length mismatch (cookie=%d, header=%d)",
                        len(csrf_cookie),
                        len(csrf_header),
                    )
                    return JSONResponse(status_code=403, content={"detail": "CSRF validation failed."})

        csrf_token = request.cookies.get("csrf_token")
        is_new_token = False
        if not csrf_token:
            csrf_token = secrets.token_hex(32)
            is_new_token = True

        request.state.csrf_token = csrf_token
        response = await call_next(request)

        if is_new_token:
            samesite = get_cookie_samesite(request)
            secure_flag = IS_PRODUCTION or (samesite == "none")
            response.set_cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=False,
                samesite=samesite,
                secure=secure_flag,
            )

        return response

app.add_middleware(CSRFMiddleware)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=VERCEL_ORIGIN_REGEX.pattern,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

class RegisterRequest(BaseModel):
    fullname: str
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class GoogleAuthRequest(BaseModel):
    credential: str

class ChatRequest(BaseModel):
    message: str
    chat_id: str | None = None
    provider: str | None = None
    model: str | None = None


@app.get("/api/csrf")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_csrf(request: Request):
    return {"message": "CSRF cookie set", "csrf_token": request.state.csrf_token}

async def get_current_user(
    access_token: str | None = Cookie(None),
    authorization: str | None = Header(None)
):
    token = access_token
    token_from_header = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token_from_header = parts[1]

    if not token:
        token = token_from_header

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(token)
    # If cookie was present but expired/invalid, try the Bearer header fallback if available
    if not payload and access_token and token_from_header:
        token = token_from_header
        payload = decode_access_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = await users_collection.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return {"email": user["email"], "fullname": user["fullname"]}

@app.post("/api/register")
@limiter.limit(RATE_LIMIT_REGISTER)
async def register(request: Request, body_req: RegisterRequest, response: Response):
    # Fix request obj access
    request_obj = request
    request = body_req
    existing_user = await users_collection.find_one({"email": request.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(request.password)
    user_doc = {
        "fullname": request.fullname,
        "email": request.email,
        "hashed_password": hashed_password,
        "created_at": datetime.now(timezone.utc)
    }

    await users_collection.insert_one(user_doc)

    access_token = create_access_token(data={"sub": request.email})
    from auth import ACCESS_TOKEN_EXPIRE_MINUTES
    samesite = get_cookie_samesite(request_obj)
    secure_flag = IS_PRODUCTION or (samesite == "none")
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return {
        "message": "User registered successfully",
        "user": {"email": request.email, "fullname": request.fullname},
        "access": access_token,
        "access_token": access_token
    }

@app.post("/api/login")
@limiter.limit(RATE_LIMIT_LOGIN)
async def login(request: Request, body_req: LoginRequest, response: Response):
    request_obj = request
    request = body_req
    user = await users_collection.find_one({"email": request.email})
    if user and user.get("hashed_password"):
        is_valid = verify_password(request.password, user["hashed_password"])
    else:
        dummy_hash = "$2b$12$Ad.JhLIiX8Dtu/AtpaiCWuGzdVRHNgX/Rs8tH5m7nTXfA8VZ74LJC"
        verify_password(request.password, dummy_hash)
        is_valid = False
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(data={"sub": request.email})
    from auth import ACCESS_TOKEN_EXPIRE_MINUTES
    samesite = get_cookie_samesite(request_obj)
    secure_flag = IS_PRODUCTION or (samesite == "none")
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return {
        "message": "Login successful",
        "user": {"email": user["email"], "fullname": user["fullname"]},
        "access": access_token,
        "access_token": access_token
    }

@app.get("/api/auth/google/login")
async def google_login(request: Request, redirect_uri: str = None):
    state = secrets.token_urlsafe(16)

    if not redirect_uri:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/api/auth/google/callback"
    else:
        # Validate redirect URI to prevent Open Redirect
        parsed = urlparse(redirect_uri)
        if not parsed.path.endswith("/api/auth/google/callback"):
            raise HTTPException(status_code=400, detail="Invalid redirect URI path.")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account"
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    response = RedirectResponse(url=url)

    # We will set a short-lived cookie for the state
    samesite = get_cookie_samesite(request)
    secure_flag = IS_PRODUCTION or (samesite == "none")
    response.set_cookie(
        key="google_oauth_state",
        value=state,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=300
    )
    response.set_cookie(
        key="google_oauth_redirect_uri",
        value=redirect_uri,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=300
    )

    return response

@app.get("/api/auth/google/callback")
async def google_callback(request: Request, response: Response, state: str, code: str = None, error: str = None):
    # Handle user cancellation
    if error:
        logger.warning(f"GOOGLE OAUTH ERROR: {error}")
        err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Authentication+cancelled")
        err_res.delete_cookie("google_oauth_state")
        err_res.delete_cookie("google_oauth_redirect_uri")
        return err_res

    if not code:
        logger.warning("GOOGLE OAUTH ERROR: Missing authorization code")
        err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Missing+code")
        err_res.delete_cookie("google_oauth_state")
        err_res.delete_cookie("google_oauth_redirect_uri")
        return err_res

    # Validate State (CSRF)
    cookie_state = request.cookies.get("google_oauth_state")
    if not cookie_state or cookie_state != state:
        logger.warning("GOOGLE OAUTH ERROR: Invalid state parameter")
        err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Invalid+state")
        err_res.delete_cookie("google_oauth_state")
        err_res.delete_cookie("google_oauth_redirect_uri")
        return err_res

    redirect_uri = request.cookies.get("google_oauth_redirect_uri")
    if not redirect_uri:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/api/auth/google/callback"

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            },
            timeout=10.0
        )
        token_data = token_response.json()
        id_token_str = token_data.get("id_token")

        if not id_token_str:
            logger.warning("GOOGLE OAUTH ERROR: Failed to get id token")
            err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Authentication+failed")
            err_res.delete_cookie("google_oauth_state")
            return err_res

        try:
            idinfo = id_token.verify_oauth2_token(
                id_token_str, google_requests.Request(), GOOGLE_CLIENT_ID, clock_skew_in_seconds=60
            )
        except ValueError:
            logger.warning("GOOGLE OAUTH ERROR: Invalid Google token")
            err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Invalid+Google+token")
            err_res.delete_cookie("google_oauth_state")
            return err_res

        if idinfo.get("email_verified") != True:
            logger.warning("GOOGLE OAUTH ERROR: Unverified email")
            err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=No+verified+email")
            err_res.delete_cookie("google_oauth_state")
            err_res.delete_cookie("google_oauth_redirect_uri")
            return err_res

        email = idinfo['email']
        name = idinfo.get('name', 'Google User')

        # Find or create CYPHR user
        user = await users_collection.find_one({"email": email})
        if not user:
            user_doc = {
                "email": email,
                "fullname": name,
                "hashed_password": None,
                "auth_provider": "google"
            }
            await users_collection.insert_one(user_doc)

        # Create JWT and set cookie
        from auth import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
        jwt_token = create_access_token(data={"sub": email})

        redirect_url = f"{FRONTEND_URL}/#token={jwt_token}"
        redirect_response = RedirectResponse(url=redirect_url)
        samesite = get_cookie_samesite(request)
        secure_flag = IS_PRODUCTION or (samesite == "none")
        redirect_response.set_cookie(
            key="access_token",
            value=jwt_token,
            httponly=True,
            samesite=samesite,
            secure=secure_flag,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        redirect_response.delete_cookie("google_oauth_state")
        redirect_response.delete_cookie("google_oauth_redirect_uri")
        return redirect_response



@app.get("/api/auth/github/login")
async def github_login(request: Request, redirect_uri: str = None):
    state = secrets.token_urlsafe(16)

    if not redirect_uri:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/api/auth/github/callback"
    else:
        # Validate redirect URI to prevent Open Redirect
        parsed = urlparse(redirect_uri)
        if not parsed.path.endswith("/api/auth/github/callback"):
            raise HTTPException(status_code=400, detail="Invalid redirect URI path.")

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "user:email"
    }
    url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"

    response = RedirectResponse(url=url)

    # We will set a short-lived cookie for the state
    samesite = get_cookie_samesite(request)
    secure_flag = IS_PRODUCTION or (samesite == "none")
    response.set_cookie(
        key="github_oauth_state",
        value=state,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=300
    )
    response.set_cookie(
        key="github_oauth_redirect_uri",
        value=redirect_uri,
        httponly=True,
        samesite=samesite,
        secure=secure_flag,
        max_age=300
    )

    return response

@app.get("/api/auth/github/callback")
async def github_callback(request: Request, response: Response, code: str, state: str):
    # Validate State (CSRF)
    cookie_state = request.cookies.get("github_oauth_state")
    if not cookie_state or cookie_state != state:
        logger.warning("GITHUB OAUTH ERROR: Invalid state parameter")
        err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Invalid+state")
        err_res.delete_cookie("github_oauth_state")
        err_res.delete_cookie("github_oauth_redirect_uri")
        return err_res

    redirect_uri = request.cookies.get("github_oauth_redirect_uri")
    if not redirect_uri:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.url.netloc)
        redirect_uri = f"{scheme}://{host}/api/auth/github/callback"

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
                "state": state
            },
            timeout=10.0
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            logger.warning("GITHUB OAUTH ERROR: Failed to get access token")
            err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=Authentication+failed")
            err_res.delete_cookie("github_oauth_state")
            return err_res

        # Get user profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0
        )
        user_data = user_response.json()

        name = user_data.get("name") or user_data.get("login") or "GitHub User"
        email = user_data.get("email")

        # If email is private, we must fetch from /user/emails
        if not email:
            emails_response = await client.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0
            )
            emails_data = emails_response.json()
            for e in emails_data:
                if e.get("primary") and e.get("verified"):
                    email = e.get("email")
                    break
            if not email:
                # Fallback to any verified email
                for e in emails_data:
                    if e.get("verified"):
                        email = e.get("email")
                        break

        if not email:
            logger.warning("GITHUB OAUTH ERROR: No verified email found")
            err_res = RedirectResponse(url=f"{FRONTEND_URL}/login?error=No+verified+email")
            err_res.delete_cookie("github_oauth_state")
            err_res.delete_cookie("github_oauth_redirect_uri")
            return err_res

        # Find or create CYPHR user
        user = await users_collection.find_one({"email": email})
        if not user:
            user_doc = {
                "email": email,
                "fullname": name,
                "hashed_password": None,
                "auth_provider": "github"
            }
            await users_collection.insert_one(user_doc)

        # Create JWT and set cookie
        from auth import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
        jwt_token = create_access_token(data={"sub": email})

        redirect_url = f"{FRONTEND_URL}/#token={jwt_token}"
        redirect_response = RedirectResponse(url=redirect_url)
        samesite = get_cookie_samesite(request)
        secure_flag = IS_PRODUCTION or (samesite == "none")
        redirect_response.set_cookie(
            key="access_token",
            value=jwt_token,
            httponly=True,
            samesite=samesite,
            secure=secure_flag,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
        redirect_response.delete_cookie("github_oauth_state")
        redirect_response.delete_cookie("github_oauth_redirect_uri")
        return redirect_response

@app.post("/api/logout")
@limiter.limit(RATE_LIMIT_GENERAL)
async def logout(request: Request, response: Response):
    samesite = get_cookie_samesite(request)
    secure_flag = IS_PRODUCTION or (samesite == "none")
    response.delete_cookie(
        "access_token", httponly=True, samesite=samesite, secure=secure_flag
    )
    return {"message": "Logged out successfully"}

@app.get("/api/me")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_me(request: Request, current_user: dict = Depends(get_current_user)):
    return {"user": current_user}

@app.get("/api/llm/providers")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_llm_providers(request: Request, current_user: dict = Depends(get_current_user)):
    return get_public_provider_catalog()



@app.get("/api/documents")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_documents(request: Request, current_user: dict = Depends(get_current_user)):
    # Aggregate unique filenames for this user
    pipeline = [
        {"$match": {"user_email": current_user["email"]}},
        {"$group": {"_id": "$filename"}}
    ]
    cursor = collection.aggregate(pipeline)
    docs = await cursor.to_list(length=None)
    return [{"filename": doc["_id"]} for doc in docs]

@app.delete("/api/documents/{filename}")
@limiter.limit(RATE_LIMIT_GENERAL)
async def delete_document(request: Request, filename: str, current_user: dict = Depends(get_current_user)):
    result = await collection.delete_many({"user_email": current_user["email"], "filename": filename})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"message": "Document deleted successfully"}

@app.get("/api/chats")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_chats(request: Request, current_user: dict = Depends(get_current_user)):
    cursor = chats_collection.find({"user_email": current_user["email"]}, {"messages": 0}).sort("created_at", -1)
    chats = await cursor.to_list(length=None)
    for chat in chats:
        chat["_id"] = str(chat["_id"])
    return chats

@app.post("/api/chats/new")
@limiter.limit(RATE_LIMIT_GENERAL)
async def create_new_chat(request: Request, current_user: dict = Depends(get_current_user)):
    chat_id = str(uuid.uuid4())
    chat_doc = {
        "chat_id": chat_id,
        "user_email": current_user["email"],
        "title": "New Conversation",
        "created_at": datetime.now(timezone.utc),
        "messages": []
    }
    await chats_collection.insert_one(chat_doc)
    return {"chat_id": chat_id, "title": chat_doc["title"]}

@app.get("/api/chats/{chat_id}")
@limiter.limit(RATE_LIMIT_GENERAL)
async def get_chat(request: Request, chat_id: str, current_user: dict = Depends(get_current_user)):
    chat = await chats_collection.find_one({"chat_id": chat_id, "user_email": current_user["email"]}, {"_id": 0})
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

MAX_PDF_SIZE_MB = int(os.getenv("MAX_PDF_SIZE_MB", 25))
MAX_PDF_SIZE_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024

@app.post("/upload")
@limiter.limit(RATE_LIMIT_UPLOAD)
async def upload_document(request: Request, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    contents = bytearray()
    while chunk := await file.read(1024 * 1024):
        contents.extend(chunk)
        if len(contents) > MAX_PDF_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"PDF is too large. Maximum size is {MAX_PDF_SIZE_MB} MB.")

    try:
        await process_and_store_document(file.filename, bytes(contents), current_user["email"])
        return {"message": f"Successfully processed and stored {file.filename}"}
    except ValueError as ve:
        error_msg = str(ve)
        if "too many" in error_msg.lower():
            raise HTTPException(status_code=413, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.exception("CRITICAL ERROR in upload_document")
        # Only pass through our own controlled Exception messages, otherwise generic 500
        safe_messages = ["Failed to generate embeddings. Upload aborted.", "Database insertion failed. Upload aborted."]
        detail = str(e) if str(e) in safe_messages else "An internal server error occurred while processing the document."
        raise HTTPException(status_code=500, detail=detail)

class TitleRequest(BaseModel):
    title: str

@app.patch("/api/chats/{chat_id}/title")
@limiter.limit(RATE_LIMIT_GENERAL)
async def update_chat_title(request: Request, chat_id: str, req: TitleRequest, current_user: dict = Depends(get_current_user)):
    result = await chats_collection.update_one(
        {"chat_id": chat_id, "user_email": current_user["email"]},
        {"$set": {"title": req.title}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"message": "Title updated successfully"}

@app.delete("/api/chats/{chat_id}")
@limiter.limit(RATE_LIMIT_GENERAL)
async def delete_chat(request: Request, chat_id: str, current_user: dict = Depends(get_current_user)):
    result = await chats_collection.delete_one(
        {"chat_id": chat_id, "user_email": current_user["email"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"message": "Chat successfully deleted"}

@app.post("/chat")
@limiter.limit(RATE_LIMIT_CHAT)
async def chat(request: Request, body_req: ChatRequest, current_user: dict = Depends(get_current_user)):
    request_obj = request
    request = body_req
    try:
        chat_id = request.chat_id
        is_new_chat = False

        if not chat_id:
            chat_id = str(uuid.uuid4())
            is_new_chat = True
            chat_doc = {
                "chat_id": chat_id,
                "user_email": current_user["email"],
                "title": "New Conversation",
                "created_at": datetime.now(timezone.utc),
                "messages": []
            }
            await chats_collection.insert_one(chat_doc)
        else:
            chat_exists = await chats_collection.find_one({"chat_id": chat_id, "user_email": current_user["email"]})
            if not chat_exists:
                raise HTTPException(status_code=404, detail="Chat not found")

        # Auto-title logic
        chat_title = "New Conversation"
        if not is_new_chat:
            chat_title = chat_exists.get("title", "New Conversation")

        generated_title = None
        if chat_title == "New Conversation":
            new_title = await generate_auto_title(request.message)
            if new_title and new_title != "New Conversation":
                await chats_collection.update_one(
                    {"chat_id": chat_id, "user_email": current_user["email"]},
                    {"$set": {"title": new_title}}
                )
                generated_title = new_title

        # Generate response
        answer = await generate_chat_response(request.message, current_user["email"], provider_id=request.provider, model_id=request.model)

        # Update chat thread
        user_msg = {"role": "user", "content": request.message, "timestamp": datetime.now(timezone.utc)}
        assistant_msg = {"role": "assistant", "content": answer, "timestamp": datetime.now(timezone.utc)}

        await chats_collection.update_one(
            {"chat_id": chat_id, "user_email": current_user["email"]},
            {"$push": {"messages": {"$each": [user_msg, assistant_msg]}}}
        )

        response_payload = {"response": answer, "chat_id": chat_id}
        if generated_title:
            response_payload["title"] = generated_title
        elif not is_new_chat:
            response_payload["title"] = chat_title
        else:
            # If it's a new chat, but title generation failed, provide the default.
            response_payload["title"] = "New Conversation"

        return response_payload
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CRITICAL CHAT ERROR")
        raise HTTPException(status_code=500, detail="Failed to generate response. Please try again.")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=not IS_PRODUCTION, proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))
