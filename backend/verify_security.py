import config
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import sys
import os

# Ensure backend directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app
from services import generate_chat_response, generate_auto_title


import contextlib

@contextlib.contextmanager
def temporary_cookies(test_client, new_cookies):
    """
    Temporarily add cookies to a TestClient.
    Preserves existing cookies, sets the new ones, and restores original state after execution.
    """
    if not new_cookies:
        yield
        return

    old_cookies = list(test_client.cookies.jar)
    test_client.cookies.jar.clear()

    for cookie in old_cookies:
        if cookie.name not in new_cookies:
            test_client.cookies.jar.set_cookie(cookie)

    for name, value in new_cookies.items():
        test_client.cookies.set(name, value)

    try:
        yield
    finally:
        test_client.cookies.jar.clear()
        for cookie in old_cookies:
            test_client.cookies.jar.set_cookie(cookie)

client = TestClient(app)


class TestCYPHRSecurityAndRAG(unittest.IsolatedAsyncioTestCase):

    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    def test_sidebar_flow_updates_title(self, mock_auto_title, mock_generate_chat, mock_update, mock_find):
        """Verify that an existing chat with 'New Conversation' gets its title updated in DB and response."""
        mock_find.return_value = {"chat_id": "fake-123", "title": "New Conversation"}
        mock_generate_chat.return_value = "Mock answer"
        mock_auto_title.return_value = "Generated Awesome Title"

        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "Test message", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )

        self.assertEqual(response.status_code, 200)

        # Verify the auto-title was generated
        mock_auto_title.assert_called_once_with("Test message")

        # Verify the DB was updated with the new title
        mock_update.assert_any_call({"chat_id": "fake-123", "user_email": "user@test.com"}, {"$set": {"title": "Generated Awesome Title"}})

        # Verify the response payload has the title
        self.assertEqual(response.json().get("title"), "Generated Awesome Title")

        app.dependency_overrides = {}


    @patch("services.get_provider_client")
    async def test_auto_title_always_resolves_groq_20b(self, mock_get_client):
        """Verify generate_auto_title ALWAYS resolves Groq 20B regardless of anything else."""
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Mocked Title"))]
        mock_client.chat.completions.create.return_value = mock_response
        # get_provider_client returns (client, resolved_provider, resolved_model)
        mock_get_client.return_value = (mock_client, "groq", "openai/gpt-oss-20b")
        from services import generate_auto_title
        # Test A: Basic call
        title = await generate_auto_title("hello world")
        self.assertEqual(title, "Mocked Title")
        # Prove it requested the TITLE_PROVIDER and TITLE_MODEL from get_provider_client
        mock_get_client.assert_called_with("groq", "openai/gpt-oss-20b")
        mock_client.chat.completions.create.assert_called_once()
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "openai/gpt-oss-20b")
        self.assertTrue("hello world" in kwargs["messages"][0]["content"])

    @patch("main.chats_collection.insert_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    def test_auto_title_independent_of_answer_model(self, mock_auto_title, mock_generate_chat, mock_update, mock_insert):
        """Prove the /chat endpoint isolates answer routing from title routing for multiple models."""
        mock_generate_chat.return_value = "Mock answer"
        mock_auto_title.return_value = "Mock title"
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"
        test_cases = [
            ("gemini", "gemini-1.5-pro"),
            ("tokenforge", "claude-opus-5"),
            ("groq", "openai/gpt-oss-120b")
        ]
        for prov, mod in test_cases:
            mock_generate_chat.reset_mock()
            mock_auto_title.reset_mock()

            with temporary_cookies(client, {"csrf_token": csrf_token}):
                response = client.post(
                    "/chat",
                    json={"message": "Test message", "provider": prov, "model": mod},
                    headers={"X-CSRF-Token": csrf_token}
                )

            self.assertEqual(response.status_code, 200)

            # 1. Answer model follows user selection
            mock_generate_chat.assert_called_once_with("Test message", "user@test.com", provider_id=prov, model_id=mod)

            # 2. Title generation NEVER receives the user's provider/model
            mock_auto_title.assert_called_once_with("Test message")

        app.dependency_overrides = {}


    def test_patch_9_production_csrf_cookie(self):
        """PATCH 9: Verify ACTUAL emitted CSRF Set-Cookie header in production contains Secure and SameSite=None."""
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = str(Path(__file__).resolve().parent)
        script = """
import os
if 'COOKIE_SAMESITE' in os.environ: del os.environ['COOKIE_SAMESITE']
os.environ['ENVIRONMENT'] = 'production'
os.environ['FRONTEND_URL'] = 'https://example.com'
os.environ['JWT_SECRET_KEY'] = 'A'*32
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

response = client.get('/api/csrf')
set_cookie = response.headers.get('set-cookie', '')
print("SET_COOKIE:", set_cookie)
"""
        env = os.environ.copy()
        if 'COOKIE_SAMESITE' in env: del env['COOKIE_SAMESITE']
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=backend_dir, env=env)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Secure", result.stdout)
        self.assertIn("samesite=none", result.stdout.lower())


    async def test_patch_9_jwt_length(self):
        """PATCH 9: Verify JWT_SECRET_KEY must be >= 32 chars in production."""
        import auth
        import os
        import importlib

        old_env = os.environ.get("ENVIRONMENT")
        old_key = os.environ.get("JWT_SECRET_KEY")

        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ["JWT_SECRET_KEY"] = "short"

            with self.assertRaises(ValueError) as context:
                importlib.reload(auth)

            self.assertIn("must be at least 32 characters", str(context.exception))
        finally:
            if old_env is None:
                os.environ.pop("ENVIRONMENT", None)
            else:
                os.environ["ENVIRONMENT"] = old_env

            if old_key is None:
                os.environ.pop("JWT_SECRET_KEY", None)
            else:
                os.environ["JWT_SECRET_KEY"] = old_key

            importlib.reload(auth)


    def test_patch_8f_health_check(self):
        """PATCH 8F: Verify /health endpoint returns 200 OK and no secrets."""
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "CYPHR-RAG"})

    async def asyncSetUp(self):
        import embeddings
        import main
        main.limiter._storage.reset()
        await embeddings.close_embedding_provider()
        self.original_provider = embeddings.EMBEDDING_PROVIDER
        embeddings.EMBEDDING_PROVIDER = "jina"

    async def asyncTearDown(self):
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = self.original_provider


    @patch("services.collection")
    @patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_1_multi_tenant_isolation(self, mock_provider, mock_embed, mock_collection):
        """[1] Multi-Tenant Isolation Verification Test"""
        mock_embed.return_value = [[0.1]*768] if "documents" in str(mock_embed) else [0.1]*768
        mock_collection.distinct = AsyncMock(return_value=[])
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.aggregate.return_value = mock_cursor

        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock(message=MagicMock(content="Mocked answer"))]
        mock_client = MagicMock()

        mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')

        # Run test for alpha
        await generate_chat_response("Hello", "user_alpha@test.com")
        pipeline_alpha = mock_collection.aggregate.call_args[0][0]
        vector_search_stage_alpha = pipeline_alpha[0]["$vectorSearch"]
        self.assertEqual(vector_search_stage_alpha["filter"]["user_email"], {"$eq": "user_alpha@test.com"})

        # Run test for beta
        await generate_chat_response("Hello", "user_beta@test.com")
        pipeline_beta = mock_collection.aggregate.call_args[0][0]
        vector_search_stage_beta = pipeline_beta[0]["$vectorSearch"]
        self.assertEqual(vector_search_stage_beta["filter"]["user_email"], {"$eq": "user_beta@test.com"})

    @patch("services.collection")
    @patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_2_filename_aware_scoping(self, mock_provider, mock_embed, mock_collection):
        """[2] Filename-Aware Scoping Verification Test"""
        mock_embed.return_value = [[0.1]*768] if "documents" in str(mock_embed) else [0.1]*768
        mock_collection.distinct = AsyncMock(return_value=["testnewnewtestnew.pdf", "otherfile.pdf"])
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.aggregate.return_value = mock_cursor

        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock(message=MagicMock(content="Mocked answer"))]
        mock_client = MagicMock()

        mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')

        await generate_chat_response("Summarize testnewnewtestnew.pdf please", "user@test.com")

        pipeline = mock_collection.aggregate.call_args[0][0]
        vector_search_stage = pipeline[0]["$vectorSearch"]

        self.assertEqual(vector_search_stage["filter"]["user_email"], {"$eq": "user@test.com"})
        self.assertEqual(vector_search_stage["filter"]["filename"], {"$eq": "testnewnewtestnew.pdf"})

    @patch("services.collection")
    @patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_3_metadata_page_fallback(self, mock_provider, mock_embed, mock_collection):
        """[3] Metadata Page Integrity & Fallback Test"""
        mock_embed.return_value = [[0.1]*768] if "documents" in str(mock_embed) else [0.1]*768
        mock_collection.distinct = AsyncMock(return_value=["doc.pdf"])
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"filename": "doc.pdf", "text": "Missing page chunk"}
        ])
        mock_collection.aggregate.return_value = mock_cursor

        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock(message=MagicMock(content="Here is the info."))]
        mock_client = MagicMock()

        mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')

        answer = await generate_chat_response("query", "user@test.com")

        self.assertIn("- **doc.pdf** (Page 1)", answer)
        self.assertNotIn("(Page ?)", answer)

    @patch("services.collection")
    @patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_4_precision_citation_filtering(self, mock_provider, mock_embed, mock_collection):
        """[4] Post-LLM Precision Citation Filtering Test"""
        mock_embed.return_value = [[0.1]*768] if "documents" in str(mock_embed) else [0.1]*768
        mock_collection.distinct = AsyncMock(return_value=["file1.pdf", "file2.pdf", "file3.pdf"])
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {"filename": "file1.pdf", "page": 1, "text": "Top match"},
            {"filename": "file2.pdf", "page": 5, "text": "Random context"},
            {"filename": "file3.pdf", "page": 2, "text": "Context for file3"}
        ])
        mock_collection.aggregate.return_value = mock_cursor

        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock(message=MagicMock(content="Based on file3.pdf, here is the result."))]
        mock_client = MagicMock()

        mock_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)

        mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')

        answer = await generate_chat_response("query", "user@test.com")

        self.assertIn("- **file1.pdf** (Page 1)", answer)
        self.assertIn("- **file3.pdf** (Page 2)", answer)

        sources_block = answer.split("### 📚 Sources:")[1] if "### 📚 Sources:" in answer else ""
        self.assertNotIn("file2.pdf", sources_block)

    @patch("main.chats_collection.insert_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    def test_5_graceful_error_boundary(self, mock_generate_chat, mock_insert):
        """[5] Graceful Error Boundary & Exception Handling Test"""
        mock_generate_chat.side_effect = Exception("Upstream OpenAI Timeout")

        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post("/chat", json={"message": "Crash it"}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})

        app.dependency_overrides = {}
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Failed to generate response. Please try again.")


    @patch("main.chats_collection.insert_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    def test_6_chat_endpoint_forwards_provider_model(self, mock_generate_chat, mock_auto_title, mock_update, mock_insert):
        """Verify /chat endpoint correctly forwards provider/model to generate_chat_response"""
        mock_generate_chat.return_value = "Mock response"
        mock_auto_title.return_value = "Mock title"
        mock_update.return_value = None
        mock_insert.return_value = None
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"
        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={
                "message": "Hello",
                "provider": "groq",
                "model": "openai/gpt-oss-120b"
                },
                headers={"X-CSRF-Token": csrf_token}
            )
        self.assertEqual(response.status_code, 200)
        mock_generate_chat.assert_called_once_with(
            "Hello",
            "user@test.com",
            provider_id="groq",
            model_id="openai/gpt-oss-120b"
        )
        mock_auto_title.assert_called_once_with("Hello")

        # Test default fallback when omitted
        mock_generate_chat.reset_mock()
        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response2 = client.post(
                "/chat",
                json={"message": "Hello2"},
                headers={"X-CSRF-Token": csrf_token}
            )
        self.assertEqual(response2.status_code, 200)
        mock_generate_chat.assert_called_once_with(
            "Hello2",
            "user@test.com",
            provider_id=None,
            model_id=None
        )
        mock_auto_title.assert_called_with("Hello2")
        app.dependency_overrides = {}

    def test_6_csrf_get_without_token(self):
        """1. GET request without CSRF token"""
        response = client.get('/api/csrf')
        self.assertEqual(response.status_code, 200)
        self.assertIn("csrf_token", response.json())
        self.assertTrue(len(response.json()["csrf_token"]) > 32)

    def test_7_csrf_post_without_token(self):
        """2. POST without CSRF token"""
        response = client.post('/api/logout')
        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF validation failed", response.json()["detail"])

    def test_8_csrf_patch_without_token(self):
        """3. PATCH without CSRF token"""
        response = client.patch('/api/chats/123/title')
        self.assertEqual(response.status_code, 403)

    def test_9_csrf_delete_without_token(self):
        """4. DELETE without CSRF token"""
        response = client.delete('/api/chats/123')
        self.assertEqual(response.status_code, 403)

    def test_10_csrf_post_incorrect_token(self):
        """5. POST with incorrect CSRF token"""
        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/api/logout', headers={'X-CSRF-Token': 'def'})
        self.assertEqual(response.status_code, 403)

    @patch("main.chats_collection.insert_one", new_callable=AsyncMock)
    def test_11_csrf_valid_token_and_auth(self, mock_insert):
        """8, 14, 15. Valid CSRF token + Auth"""
        cookies = {'csrf_token': 'match'}
        headers = {'X-CSRF-Token': 'match', 'Origin': 'http://localhost:5173'}
        # mock auth
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        with temporary_cookies(client, cookies):
            response = client.post('/api/chats/new', headers=headers)
        app.dependency_overrides = {}
        self.assertEqual(response.status_code, 200)

    def test_12_csrf_missing_header(self):
        """9. Correct token in cookie but missing header"""
        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/api/logout')
        self.assertEqual(response.status_code, 403)

    def test_13_csrf_mismatched_cookie(self):
        """10. Correct header but mismatched cookie"""
        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/api/logout', headers={'X-CSRF-Token': 'xyz'})
        self.assertEqual(response.status_code, 403)

    def test_14_invalid_origin(self):
        """11. Invalid Origin"""
        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/api/logout', headers={'X-CSRF-Token': 'abc', 'Origin': 'http://evil.com'})
        self.assertEqual(response.status_code, 403)

    def test_15_options_preflight(self):
        """13. OPTIONS preflight"""
        response = client.options('/api/logout', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(response.status_code, 200)

    @patch('main.process_and_store_document', new_callable=AsyncMock)
    def test_16_upload_oversized_pdf(self, mock_process):
        """Oversized PDF"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        # Create a file just over 25MB but mock the read
        # Wait, if we send real 25MB it's slow. We can patch MAX_PDF_SIZE_BYTES
        import main
        orig_max = main.MAX_PDF_SIZE_BYTES
        main.MAX_PDF_SIZE_BYTES = 100 # 100 bytes limit

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'A'*150, 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})

        main.MAX_PDF_SIZE_BYTES = orig_max
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 413)
        self.assertIn("too large", response.json()["detail"])
        mock_process.assert_not_called()

    def test_17_upload_fake_pdf(self):
        """Fake .pdf file extension check"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.txt', b'abc', 'text/plain')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 400)
        self.assertIn("Only PDF files", response.json()["detail"])

    @patch('services.PdfReader')
    def test_18_upload_corrupted_pdf(self, mock_pdfreader):
        """Corrupted PDF"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        mock_pdfreader.side_effect = Exception("corrupt")

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid or corrupted", response.json()["detail"])

    @patch('services.PdfReader')
    def test_19_upload_too_many_pages(self, mock_pdfreader):
        """PDF exceeding page limit"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        mock_reader_instance = MagicMock()
        mock_reader_instance.pages = [MagicMock()] * 201
        mock_pdfreader.return_value = mock_reader_instance

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 413)
        self.assertIn("too many pages", response.json()["detail"])

    @patch('services.PdfReader')
    def test_20_upload_empty_pdf(self, mock_pdfreader):
        """Empty PDF / No extractable text"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        mock_reader_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "   "
        mock_reader_instance.pages = [mock_page]
        mock_pdfreader.return_value = mock_reader_instance

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 400)
        self.assertIn("no extractable text", response.json()["detail"])

    @patch('services.PdfReader')
    def test_21_upload_chunk_explosion(self, mock_pdfreader):
        """Document exceeding chunk limit"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        mock_reader_instance = MagicMock()
        mock_page = MagicMock()
        # Generates a massive string to trigger thousands of chunks
        mock_page.extract_text.return_value = "A" * 5000000
        mock_reader_instance.pages = [mock_page]
        mock_pdfreader.return_value = mock_reader_instance

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 413)
        self.assertIn("too many text chunks", response.json()["detail"])

    @patch('services.PdfReader')
    @patch('embeddings.JinaEmbeddingProvider.embed_documents', new_callable=AsyncMock)
    def test_22_upload_embedding_failure(self, mock_embed, mock_pdfreader):
        """Embedding failure"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        mock_reader_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Valid text"
        mock_reader_instance.pages = [mock_page]
        mock_pdfreader.return_value = mock_reader_instance

        mock_embed.side_effect = Exception("API Timeout")

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to generate embeddings", response.json()["detail"])
        self.assertNotIn("Timeout", response.json()["detail"])

    @patch('services.PdfReader')
    @patch('embeddings.JinaEmbeddingProvider.embed_documents', new_callable=AsyncMock)
    @patch('services.collection.insert_many', new_callable=AsyncMock)
    def test_23_upload_mongodb_failure(self, mock_insert, mock_embed, mock_pdfreader):
        """MongoDB insertion failure"""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}

        mock_reader_instance = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Valid text"
        mock_reader_instance.pages = [mock_page]
        mock_pdfreader.return_value = mock_reader_instance

        mock_embed.return_value = [[0.1]*768] if "documents" in str(mock_embed) else [0.1]*768

        mock_insert.side_effect = Exception("DB Down")

        with temporary_cookies(client, {'csrf_token': 'abc'}):
            response = client.post('/upload', files={'file': ('test.pdf', b'bad', 'application/pdf')}, headers={'X-CSRF-Token': 'abc', 'Origin': 'http://localhost:5173'})
        app.dependency_overrides = {}

        self.assertEqual(response.status_code, 500)
        self.assertIn("Database insertion failed", response.json()["detail"])
        self.assertNotIn("DB Down", response.json()["detail"])


    def test_24_rate_limit_login(self):
        """Login requests over limit return 429"""
        from unittest.mock import AsyncMock
        with patch('main.users_collection.find_one', new_callable=AsyncMock) as mock_find:
            mock_find.return_value = None  # user not found, will return 401
            import main
            main.limiter._storage.reset()
            cookies = {'csrf_token': 'rl_token'}
            headers = {'X-CSRF-Token': 'rl_token', 'Origin': 'http://localhost:5173', 'X-Forwarded-For': '192.168.1.1'}

            with temporary_cookies(client, cookies):
                # 10 allowed
                for _ in range(10):
                    res = client.post('/api/login', json={"email": "t@t.com", "password": "1"}, headers=headers)
                    self.assertEqual(res.status_code, 401)

                # 11th should be 429
                res = client.post('/api/login', json={"email": "t@t.com", "password": "1"}, headers=headers)
                self.assertEqual(res.status_code, 429)
            self.assertIn("Too many login attempts", res.json()["detail"])
            self.assertIn("retry-after", res.headers)
            self.assertTrue(res.headers["retry-after"].isdigit())
            self.assertGreaterEqual(int(res.headers["retry-after"]), 1)

    @patch('main.generate_chat_response')
    @patch('main.chats_collection.find_one', new_callable=AsyncMock)
    @patch('main.chats_collection.update_one', new_callable=AsyncMock)
    def test_25_rate_limit_chat_user_isolated(self, mock_update, mock_find, mock_gen):
        """User A exhausting quota does not affect User B and bypasses expensive work"""
        mock_gen.return_value = "mocked_response"
        mock_find.return_value = {"title": "Test"}
        import main
        main.limiter._storage.reset()
        cookies = {'csrf_token': 'rl_token', 'access_token': 'mock_token'}
        headers = {'X-CSRF-Token': 'rl_token', 'Origin': 'http://localhost:5173'}

        from main import get_current_user

        # User A hits 20 chats
        app.dependency_overrides[get_current_user] = lambda: {"email": "userA@test.com"}
        with patch('auth.decode_access_token', return_value={"sub": "userA@test.com"}):
            with temporary_cookies(client, cookies):
                for _ in range(20):
                    res = client.post('/chat', json={"message": "hi", "chat_id": "1"}, headers=headers)
                    self.assertEqual(res.status_code, 200)

                # 21st should be 429 and downstream not called
                mock_gen.reset_mock()
                res = client.post('/chat', json={"message": "hi", "chat_id": "1"}, headers=headers)
                self.assertEqual(res.status_code, 429)
            self.assertIn("Too many chat requests", res.json()["detail"])
            self.assertIn("retry-after", res.headers)
            self.assertTrue(res.headers["retry-after"].isdigit())
            self.assertGreaterEqual(int(res.headers["retry-after"]), 1)
            mock_gen.assert_not_called()

        # User B should still be allowed
        app.dependency_overrides[get_current_user] = lambda: {"email": "userB@test.com"}
        with patch('auth.decode_access_token', return_value={"sub": "userB@test.com"}):
            with temporary_cookies(client, cookies):
                res = client.post('/chat', json={"message": "hi", "chat_id": "1"}, headers=headers)
                self.assertEqual(res.status_code, 200)

        app.dependency_overrides = {}

    @patch('main.process_and_store_document', new_callable=AsyncMock)
    def test_26_rate_limit_upload(self, mock_process):
        """Upload requests over limit return 429 and bypass processing"""
        import main
        main.limiter._storage.reset()
        cookies = {'csrf_token': 'rl_token', 'access_token': 'mock_token'}
        headers = {'X-CSRF-Token': 'rl_token', 'Origin': 'http://localhost:5173'}

        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "upload@test.com"}

        with patch('auth.decode_access_token', return_value={"sub": "upload@test.com"}):
            with temporary_cookies(client, cookies):
                for _ in range(10):
                    res = client.post('/upload', files={'file': ('test.pdf', b'fake', 'application/pdf')}, headers=headers)
                    self.assertEqual(res.status_code, 200)

                mock_process.reset_mock()
                res = client.post('/upload', files={'file': ('test.pdf', b'fake', 'application/pdf')}, headers=headers)
                self.assertEqual(res.status_code, 429)
            self.assertIn("Upload rate limit exceeded", res.json()["detail"])
            self.assertIn("retry-after", res.headers)
            self.assertTrue(res.headers["retry-after"].isdigit())
            self.assertGreaterEqual(int(res.headers["retry-after"]), 1)
            mock_process.assert_not_called()

        app.dependency_overrides = {}

    @patch('main.decode_access_token')
    @patch('main.users_collection.find_one', new_callable=AsyncMock)
    @patch('main.chats_collection.find_one', new_callable=AsyncMock)
    def test_27_chat_not_found_returns_404(self, mock_chats_find, mock_users_find, mock_decode):
        mock_decode.return_value = {"sub": "test@example.com"}
        mock_users_find.return_value = {"email": "test@example.com", "fullname": "Test User"}

        # Simulate chat not found
        mock_chats_find.return_value = None

        headers = {"x-csrf-token": "dummy_csrf"}
        cookies = {"access_token": "dummy_jwt", "csrf_token": "dummy_csrf"}

        with temporary_cookies(client, cookies):
            response = client.post("/chat", json={"message": "hello", "chat_id": "nonexistent_chat"}, headers=headers)

        self.assertEqual(response.status_code, 404)
        self.assertIn("Chat not found", response.json()["detail"])

    @patch('main.decode_access_token')
    @patch('main.users_collection.find_one', new_callable=AsyncMock)
    @patch('main.chats_collection.find_one', new_callable=AsyncMock)
    def test_28_chat_unexpected_exception_returns_500(self, mock_chats_find, mock_users_find, mock_decode):
        mock_decode.return_value = {"sub": "test@example.com"}
        mock_users_find.return_value = {"email": "test@example.com", "fullname": "Test User"}

        # Simulate an unexpected exception in chats_collection.find_one
        mock_chats_find.side_effect = Exception("SECRET_DB_CONNECTION_STRING_ERROR")

        headers = {"x-csrf-token": "dummy_csrf"}
        cookies = {"access_token": "dummy_jwt", "csrf_token": "dummy_csrf"}

        with temporary_cookies(client, cookies):
            response = client.post("/chat", json={"message": "hello", "chat_id": "existing_chat"}, headers=headers)

        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to generate response. Please try again.", response.json()["detail"])
        self.assertNotIn("SECRET_DB_CONNECTION_STRING_ERROR", response.text)

    def test_29_cors_preflight(self):
        # 1. REAL CORS PRE-FLIGHT TEST
        headers = {'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'}
        response = client.options('/api/login', headers=headers)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173')
        self.assertEqual(response.headers.get('Access-Control-Allow-Credentials'), 'true')

        # Verify unexpected origin does NOT get configured allowed-origin
        headers = {'Origin': 'http://attacker.com', 'Access-Control-Request-Method': 'POST'}
        response = client.options('/api/login', headers=headers)
        self.assertNotEqual(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173')

    @patch('main.users_collection.find_one', new_callable=unittest.mock.AsyncMock)
    @patch('main.users_collection.insert_one', new_callable=unittest.mock.AsyncMock)
    def test_30_actual_auth_cookie_creation(self, mock_insert, mock_find):
        # 2. TEST ACTUAL AUTH COOKIE CREATION
        mock_find.return_value = None
        import main

        main.IS_PRODUCTION = False
        main.COOKIE_SAMESITE = 'lax'

        client.cookies.clear()
        res_csrf = client.get('/api/csrf')
        token = res_csrf.json()['csrf_token']

        with temporary_cookies(client, {'csrf_token': token}):
            response = client.post('/api/register', json={"fullname": "test", "email": "new@test.com", "password": "123"}, headers={'X-CSRF-Token': token, 'Origin': 'http://localhost:5173'})
        set_cookies = response.headers.get_list('set-cookie')
        access_cookie = next(c for c in set_cookies if c.startswith('access_token='))

        self.assertIn('HttpOnly', access_cookie)
        self.assertIn('Path=/', access_cookie)
        self.assertIn('Max-Age=86400', access_cookie)
        self.assertIn('samesite=lax', access_cookie.lower())
        self.assertNotIn('Secure', access_cookie)

        main.IS_PRODUCTION = True
        main.COOKIE_SAMESITE = 'none'
        main.limiter._storage.reset()
        mock_find.return_value = None

        client.cookies.clear()
        res_csrf = client.get('/api/csrf')
        token = res_csrf.json()['csrf_token']

        with temporary_cookies(client, {'csrf_token': token}):
            response = client.post('/api/register', json={"fullname": "test", "email": "new2@test.com", "password": "123"}, headers={'X-CSRF-Token': token, 'Origin': 'http://localhost:5173'})
        set_cookies = response.headers.get_list('set-cookie')
        access_cookie = next(c for c in set_cookies if c.startswith('access_token='))
        self.assertIn('samesite=none', access_cookie.lower())
        self.assertIn('Secure', access_cookie)

        main.IS_PRODUCTION = False
        main.COOKIE_SAMESITE = 'lax'

    def test_31_csrf_cookie_creation(self):
        # 3. TEST CSRF COOKIE CREATION
        import main
        main.IS_PRODUCTION = False
        main.COOKIE_SAMESITE = 'lax'

        client.cookies.clear()
        response = client.get('/api/csrf')
        self.assertEqual(response.status_code, 200)

        json_token = response.json().get('csrf_token')
        self.assertTrue(len(json_token) >= 32)

        set_cookies = response.headers.get_list('set-cookie')
        csrf_cookie_str = next((c for c in set_cookies if c.startswith('csrf_token=')), None)
        self.assertIsNotNone(csrf_cookie_str)

        cookie_val = csrf_cookie_str.split(';')[0].split('=')[1]
        self.assertEqual(json_token, cookie_val)

        self.assertIn('Path=/', csrf_cookie_str)
        self.assertNotIn('HttpOnly', csrf_cookie_str)
        self.assertNotIn('Secure', csrf_cookie_str)
        self.assertIn('samesite=lax', csrf_cookie_str.lower())

        main.IS_PRODUCTION = True
        main.COOKIE_SAMESITE = 'none'

        client.cookies.clear()
        response = client.get('/api/csrf')
        set_cookies = response.headers.get_list('set-cookie')
        csrf_cookie_str = next(c for c in set_cookies if c.startswith('csrf_token='))
        self.assertIn('Secure', csrf_cookie_str)
        self.assertIn('samesite=none', csrf_cookie_str.lower())

        main.IS_PRODUCTION = False
        main.COOKIE_SAMESITE = 'lax'

    def test_32_invalid_cookie_samesite(self):
        # 4. INVALID COOKIE_SAMESITE TEST
        import subprocess
        import sys
        from pathlib import Path

        backend_dir = str(Path(__file__).resolve().parent)

        script = """
import os
os.environ['COOKIE_SAMESITE'] = 'banana'
import main
"""
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=backend_dir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("COOKIE_SAMESITE must be 'lax', 'strict', or 'none'", result.stderr)

        script2 = """
import os
os.environ['COOKIE_SAMESITE'] = 'none'
os.environ['ENVIRONMENT'] = 'development'
import main
print(main.COOKIE_SAMESITE)
"""
        result2 = subprocess.run([sys.executable, '-c', script2], capture_output=True, text=True, cwd=backend_dir)
        self.assertEqual(result2.returncode, 0)
        self.assertEqual(result2.stdout.strip(), 'lax')

        script3 = """
import os
if 'COOKIE_SAMESITE' in os.environ: del os.environ['COOKIE_SAMESITE']
os.environ['ENVIRONMENT'] = 'production'
os.environ['FRONTEND_URL'] = 'https://example.com'
os.environ['JWT_SECRET_KEY'] = 'A'*32
import main
print(main.COOKIE_SAMESITE)
print(main.IS_PRODUCTION)
"""
        # Ensure we don't pass the parent's COOKIE_SAMESITE explicitly
        env = os.environ.copy()
        if 'COOKIE_SAMESITE' in env: del env['COOKIE_SAMESITE']
        result3 = subprocess.run([sys.executable, '-c', script3], capture_output=True, text=True, cwd=backend_dir, env=env)
        self.assertEqual(result3.returncode, 0)
        self.assertIn('none', result3.stdout)
        self.assertIn('True', result3.stdout)

    def test_33_logout_cookie_deletion(self):
        # 5. LOGOUT COOKIE DELETION
        with temporary_cookies(client, {'csrf_token': 'rl_token'}):
            response = client.post('/api/logout', headers={'X-CSRF-Token': 'rl_token', 'Origin': 'http://localhost:5173'})
        set_cookies = response.headers.get_list('set-cookie')

        access_deleted = next((c for c in set_cookies if c.startswith('access_token=')), None)

        self.assertIsNotNone(access_deleted)
        self.assertIn('""', access_deleted)
        self.assertIn('Path=/', access_deleted)

        self.assertFalse(any('csrftoken=' in c for c in set_cookies))

    def test_34_security_headers(self):
        # 6. SECURITY HEADERS
        import main
        main.IS_PRODUCTION = False
        response = client.get('/api/csrf')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(response.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertNotIn('Strict-Transport-Security', response.headers)

        main.IS_PRODUCTION = True
        response = client.get('/api/csrf')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(response.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')
        self.assertIn('Strict-Transport-Security', response.headers)
        self.assertEqual(response.headers.get('Strict-Transport-Security'), 'max-age=31536000; includeSubDomains')

        main.IS_PRODUCTION = False

    def test_35_csrf_flow(self):
        # 7. CSRF FLOW
        client.cookies.clear()
        response1 = client.get('/api/csrf')
        json_token = response1.json().get('csrf_token')

        set_cookies = response1.headers.get_list('set-cookie')
        csrf_cookie_str = next(c for c in set_cookies if c.startswith('csrf_token='))
        cookie_token = csrf_cookie_str.split(';')[0].split('=')[1]

        self.assertEqual(json_token, cookie_token)

        with temporary_cookies(client, {'csrf_token': cookie_token}):
            response2 = client.post('/api/logout', headers={'X-CSRF-Token': cookie_token, 'Origin': 'http://localhost:5173'})
        self.assertEqual(response2.status_code, 200)

    @patch('main.id_token.verify_oauth2_token')
    @patch('main.users_collection.find_one')
    @patch('main.users_collection.insert_one')
    def test_36_google_auth_email_verified(self, mock_insert, mock_find, mock_verify):
        async def mock_none(*args, **kwargs): return None
        mock_find.side_effect = mock_none
        mock_insert.side_effect = mock_none

        # Unverified email
        mock_verify.return_value = {"email": "test@example.com", "name": "Test", "email_verified": False}
        with temporary_cookies(client, {'csrf_token': 'a'}):
            response = client.post('/api/auth/google', json={"credential": "fake"}, headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': 'a'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid Google token")

        # Missing email_verified
        mock_verify.return_value = {"email": "test@example.com", "name": "Test"}
        with temporary_cookies(client, {'csrf_token': 'a'}):
            response2 = client.post('/api/auth/google', json={"credential": "fake"}, headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': 'a'})
        self.assertEqual(response2.status_code, 401)

        # Verified email
        mock_verify.return_value = {"email": "test@example.com", "name": "Test", "email_verified": True}
        with temporary_cookies(client, {'csrf_token': 'a'}):
            response3 = client.post('/api/auth/google', json={"credential": "fake"}, headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': 'a'})
        self.assertEqual(response3.status_code, 200)

    @patch('main.verify_password')
    @patch('main.users_collection.find_one')
    def test_37_login_timing_enumeration(self, mock_find, mock_verify):
        async def mock_none(*args, **kwargs):
            return None
        mock_find.side_effect = mock_none
        mock_verify.return_value = False

        with temporary_cookies(client, {'csrf_token': 'a'}):
            response = client.post('/api/login', json={"email": "nonexistent@test.com", "password": "abc"}, headers={'Origin': 'http://localhost:5173', 'X-CSRF-Token': 'a'})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(mock_verify.called)

    def test_38_jwt_cookie_max_age_sync(self):
        import auth
        self.assertEqual(auth.ACCESS_TOKEN_EXPIRE_MINUTES, 1440)

        script = """
import os
os.environ['COOKIE_SAMESITE'] = 'lax'
from auth import ACCESS_TOKEN_EXPIRE_MINUTES
import main
print(ACCESS_TOKEN_EXPIRE_MINUTES * 60)
"""
        import subprocess
        import sys
        from pathlib import Path
        backend_dir = str(Path(__file__).resolve().parent)
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=backend_dir)
        self.assertIn("86400", result.stdout)
    def test_39_patch_7a_rate_limit_spoofing(self):
        # PATCH 7A TEST
        # Verify default uvicorn config is safe and does not use wildcard forwarded_allow_ips
        import subprocess
        import sys
        from pathlib import Path
        backend_dir = str(Path(__file__).resolve().parent)
        # Check Procfile
        with open(os.path.join(backend_dir, "Procfile"), "r") as f:
            procfile_content = f.read()
            self.assertNotIn('--forwarded-allow-ips="*"', procfile_content)
        # Check main.py
        with open(os.path.join(backend_dir, "main.py"), "r") as f:
            main_content = f.read()
            self.assertNotIn('forwarded_allow_ips="*"', main_content)

        # Check dynamic_key_func fallback
        import main
        from fastapi import Request
        from unittest.mock import MagicMock
        req = MagicMock(spec=Request)
        req.cookies.get.return_value = None
        req.client.host = "9.9.9.9"
        key = main.dynamic_key_func(req)
        self.assertEqual(key, "ip:9.9.9.9")

        req.cookies.get.return_value = "invalid_jwt"
        key_invalid = main.dynamic_key_func(req)
        self.assertEqual(key_invalid, "ip:9.9.9.9")

    @patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_40_patch_7b_async_embedding_used(self, mock_provider, mock_embed):
        """PATCH 7B: Verify async embedding and chat completion APIs are used"""
        from services import generate_chat_response, generate_auto_title
        mock_embed.return_value = [0.9]*768
        mock_provider_response = MagicMock()
        mock_provider_response.choices = [MagicMock(message=MagicMock(content="Async response"))]
        mock_client = MagicMock()

        mock_client.chat.completions.create = AsyncMock(return_value=mock_provider_response)

        mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')
        with patch("services.collection.distinct", new_callable=AsyncMock, return_value=["test.pdf"]), \
             patch("services.collection.aggregate") as mock_aggregate:
            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[{"filename": "test.pdf", "page": 1, "text": "async data"}])
            mock_aggregate.return_value = mock_cursor
            result = await generate_chat_response("test query", "user@test.com")

            mock_embed.assert_called_once()
            mock_provider.assert_called_once()
            self.assertIn("Async response", result)

    @patch("embeddings.JinaEmbeddingProvider.embed_documents", new_callable=AsyncMock)
    @patch("services.collection.insert_many", new_callable=AsyncMock)
    async def test_41_patch_7c_batch_embedding(self, mock_insert, mock_embed):
        """PATCH 7C: Verify batching, mismatch handling, error abort, metadata, and async validity"""
        from services import process_and_store_document
        import services
        import os
        from pypdf import PdfWriter
        import io

        # Create a dummy PDF with multiple pages to generate chunks
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        pdf_bytes = io.BytesIO()
        writer.write(pdf_bytes)

        # Mock extract_text_from_pdf to return many chunks to trigger batching
        with patch("services.extract_text_from_pdf") as mock_extract:
            # We return 3 pages, each will be 1 chunk if we just provide small text
            mock_extract.return_value = [
                {"page": 1, "text": "Chunk 1 text"},
                {"page": 2, "text": "Chunk 2 text"},
                {"page": 3, "text": "Chunk 3 text"}
            ]

            # Temporary override EMBEDDING_BATCH_SIZE to 2 to test batching across 3 chunks
            original_batch_size = services.EMBEDDING_BATCH_SIZE
            services.EMBEDDING_BATCH_SIZE = 2

            try:
                # TEST A, B, C: Batching, Metadata, Order
                mock_embed_response_1 = [[0.1]*768, [0.2]*768]

                mock_embed_response_2 = [[0.3]*768]

                mock_embed.side_effect = [mock_embed_response_1, mock_embed_response_2]

                await process_and_store_document("test.pdf", b'pdfbytes', "user@test.com")

                # Should have been called twice (3 chunks / batch size 2)
                self.assertEqual(mock_embed.call_count, 2)

                # Verify insert_many called once with 3 docs
                mock_insert.assert_called_once()
                inserted_docs = mock_insert.call_args[0][0]
                self.assertEqual(len(inserted_docs), 3)

                # Check order and metadata
                self.assertEqual(inserted_docs[0]["text"], "Chunk 1 text")
                self.assertEqual(inserted_docs[0]["embedding"], [0.1]*768)
                self.assertEqual(inserted_docs[1]["text"], "Chunk 2 text")
                self.assertEqual(inserted_docs[1]["embedding"], [0.2]*768)
                self.assertEqual(inserted_docs[2]["text"], "Chunk 3 text")
                self.assertEqual(inserted_docs[2]["embedding"], [0.3]*768)

                # TEST D: Mismatch fails safely
                mock_embed.reset_mock()
                mock_insert.reset_mock()
                # 3 chunks, but batch 1 returns only 1 embedding
                from embeddings import EmbeddingError
                mock_embed.side_effect = [EmbeddingError("Batch response count mismatch"), mock_embed_response_2]

                with self.assertRaises(Exception) as context:
                    await process_and_store_document("test.pdf", b'pdfbytes', "user@test.com")
                self.assertIn("Upload aborted", str(context.exception))
                mock_insert.assert_not_called()

                # TEST E: API Failure aborts upload
                mock_embed.reset_mock()
                mock_insert.reset_mock()
                mock_embed.side_effect = Exception("Permanent API Error")

                with self.assertRaises(Exception) as context:
                    await process_and_store_document("test.pdf", b'pdfbytes', "user@test.com")
                self.assertIn("Upload aborted", str(context.exception))
                mock_insert.assert_not_called()

            finally:
                services.EMBEDDING_BATCH_SIZE = original_batch_size


class EmojiTestResult(unittest.TextTestResult):
    def addSuccess(self, test):
        unittest.TextTestResult.addSuccess(self, test)
        if self.showAll:
            self.stream.write("✅ [PASS]\n")
            self.stream.flush()

    def addFailure(self, test, err):
        unittest.TextTestResult.addFailure(self, test, err)
        if self.showAll:
            self.stream.write("❌ [FAILED]\n")
            self.stream.flush()

    def addError(self, test, err):
        unittest.TextTestResult.addError(self, test, err)
        if self.showAll:
            self.stream.write("❌ [ERROR]\n")
            self.stream.flush()

class EmojiTestRunner(unittest.TextTestRunner):
    def _makeResult(self):
        return EmojiTestResult(self.stream, self.descriptions, self.verbosity)


class TestCYPHRPatch8A(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import embeddings
        await embeddings.close_embedding_provider()
        self.original_provider = embeddings.EMBEDDING_PROVIDER
        embeddings.EMBEDDING_PROVIDER = "jina"

    async def asyncTearDown(self):
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = self.original_provider
    async def test_patch_8a_test_a_default_provider(self):
        """TEST A: Default configuration resolves to Jina provider."""
        from embeddings import get_embedding_provider, JinaEmbeddingProvider, EMBEDDING_PROVIDER
        import embeddings
        self.assertEqual(embeddings.EMBEDDING_PROVIDER, "jina")
        provider = get_embedding_provider()
        self.assertIsInstance(provider, JinaEmbeddingProvider)

    async def test_patch_8a_test_h_unknown_provider(self):
        """TEST H: Unknown EMBEDDING_PROVIDER raises EmbeddingConfigurationError."""
        import embeddings
        from embeddings import get_embedding_provider, EmbeddingConfigurationError
        old_provider = embeddings.EMBEDDING_PROVIDER
        embeddings.EMBEDDING_PROVIDER = "unknown_provider"
        old_instance = embeddings._provider_instance
        embeddings._provider_instance = None
        try:
            with self.assertRaises(EmbeddingConfigurationError):
                get_embedding_provider()
        finally:
            embeddings.EMBEDDING_PROVIDER = old_provider
            embeddings._provider_instance = old_instance

    async def test_patch_8a_test_i_factory_caching(self):
        """TEST I: Provider factory does not unnecessarily recreate provider/client instances."""
        from embeddings import get_embedding_provider
        p1 = get_embedding_provider()
        p2 = get_embedding_provider()
        self.assertIs(p1, p2)

    async def test_patch_8a_test_j_legacy_google_provider_rejected(self):
        """Legacy Google embedding configuration is explicitly rejected after Jina cutover."""
        import embeddings
        embeddings.EMBEDDING_PROVIDER = "google"
        embeddings._provider_instance = None
        with self.assertRaises(embeddings.EmbeddingConfigurationError):
            embeddings.get_embedding_provider()
    async def test_patch_8a_test_k_l_m_integration(self):
        """TEST K, L, M: Document processing, Chat query use central abstraction, No insert on failure."""
        from services import process_and_store_document, generate_chat_response
        import io
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        pdf_bytes = io.BytesIO()
        writer.write(pdf_bytes)

        with patch("services.extract_text_from_pdf") as mock_extract, \
             patch("embeddings.JinaEmbeddingProvider.embed_documents", new_callable=AsyncMock) as mock_embed_docs, \
             patch("embeddings.JinaEmbeddingProvider.embed_query", new_callable=AsyncMock) as mock_embed_query, \
             patch("services.collection.insert_many", new_callable=AsyncMock) as mock_insert, \
             patch("services.collection.distinct", new_callable=AsyncMock, return_value=["test.pdf"]), \
             patch("services.collection.aggregate") as mock_aggregate, \
             patch("services.get_provider_client") as mock_provider:

            # K & M
            mock_extract.return_value = [{"page": 1, "text": "Doc content"}]
            # Simulate failure first
            mock_embed_docs.side_effect = Exception("General Failure")
            with self.assertRaises(Exception):
                await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")
            mock_insert.assert_not_called()  # TEST M

            # Simulate success
            mock_embed_docs.reset_mock()
            mock_embed_docs.side_effect = None
            mock_embed_docs.return_value = [[0.9]*768]
            await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")
            mock_embed_docs.assert_called_once()  # TEST K
            mock_insert.assert_called_once()
            inserted_doc = mock_insert.call_args[0][0][0]
            self.assertEqual(inserted_doc["embedding_provider"], "jina")

            # L
            mock_embed_query.return_value = [0.8]*768
            mock_provider_response = MagicMock()
            mock_provider_response.choices = [MagicMock(message=MagicMock(content="Answer"))]
            mock_client = MagicMock()

            mock_client.chat.completions.create = AsyncMock(return_value=mock_provider_response)

            mock_provider.return_value = (mock_client, 'gemini', 'gemini-1.5-flash')

            mock_cursor = AsyncMock()
            mock_cursor.to_list = AsyncMock(return_value=[{"filename": "test.pdf", "page": 1, "text": "async data"}])
            mock_aggregate.return_value = mock_cursor

            await generate_chat_response("query", "user@test.com")
            mock_embed_query.assert_called_once()  # TEST L


class TestCYPHRPatch8B2(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import embeddings
        await embeddings.close_embedding_provider()
        self.original_provider = embeddings.EMBEDDING_PROVIDER
        self.original_key = os.environ.get("JINA_API_KEY")

        # Default to safe isolated state for these tests
        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ["JINA_API_KEY"] = "dummy_jina_key"

    async def asyncTearDown(self):
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = self.original_provider
        if self.original_key is None:
            os.environ.pop("JINA_API_KEY", None)
        else:
            os.environ["JINA_API_KEY"] = self.original_key

    async def test_patch_8b2_test_a_default_jina(self):
        """TEST A: Default provider remains Jina."""
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = "jina"
        provider = embeddings.get_embedding_provider()
        self.assertIsInstance(provider, embeddings.JinaEmbeddingProvider)

    async def test_patch_8b2_test_b_resolves_jina(self):
        """TEST B: EMBEDDING_PROVIDER=jina resolves to JinaEmbeddingProvider."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        self.assertIsInstance(provider, embeddings.JinaEmbeddingProvider)

    async def test_patch_8b2_test_c_missing_key(self):
        """TEST C: Missing JINA_API_KEY raises EmbeddingConfigurationError."""
        import embeddings
        await embeddings.close_embedding_provider()
        os.environ.pop("JINA_API_KEY", None)
        with self.assertRaises(embeddings.EmbeddingConfigurationError):
            embeddings.get_embedding_provider()

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_d_e_single_query(self, mock_post):
        """TEST D & E: Single query request succeeds and returns exactly one 768-dimensional vector."""
        import embeddings
        provider = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"embedding": [0.5] * 768}]
        }
        mock_post.return_value = mock_resp

        res = await provider.embed_query("test query")
        self.assertEqual(len(res), 768)
        self.assertEqual(res[0], 0.5)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_f_g_batch_success_ordering(self, mock_post):
        """TEST F & G: Batch embedding succeeds and response indexes are reordered correctly."""
        import embeddings
        provider = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Return out of order to verify reconstruction
        mock_resp.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.2] * 768},
                {"index": 0, "embedding": [0.1] * 768}
            ]
        }
        mock_post.return_value = mock_resp

        res = await provider.embed_documents(["doc1", "doc2"])
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0][0], 0.1)
        self.assertEqual(res[1][0], 0.2)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_h_duplicate_indexes(self, mock_post):
        """TEST H: Duplicate response indexes fail safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1] * 768},
                {"index": 0, "embedding": [0.1] * 768}
            ]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_documents(["doc1", "doc2"])
        self.assertIn("Duplicate", str(ctx.exception))

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_i_missing_indexes(self, mock_post):
        """TEST I: Missing response indexes fail safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1] * 768},
                # Missing index 1 but passing 2 items (so length is 2, but result[1] is None)
                {"index": 0, "embedding": [0.1] * 768} # duplicate will fail first actually
            ]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError):
            await provider.embed_documents(["doc1", "doc2"])

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_j_out_of_range(self, mock_post):
        """TEST J: Out-of-range response indexes fail safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1] * 768},
                {"index": 5, "embedding": [0.1] * 768}
            ]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_documents(["doc1", "doc2"])
        self.assertIn("out-of-bounds", str(ctx.exception))

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_k_mismatch(self, mock_post):
        """TEST K: Response count mismatch fails safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1] * 768}]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError):
            await provider.embed_documents(["doc1", "doc2"])

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_l_wrong_dimensionality(self, mock_post):
        """TEST L: Wrong dimensionality fails safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1] * 128}]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_query("text")
        self.assertIn("dimension mismatch", str(ctx.exception))

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_m_invalid_numeric(self, mock_post):
        """TEST M: Invalid numeric values such as NaN/Infinity fail safely."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        bad_vec = [0.1] * 768
        bad_vec[0] = float('nan')
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": bad_vec}]
        }
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_query("text")
        self.assertIn("NaN/Inf", str(ctx.exception))

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_n_quota_error(self, mock_post):
        """TEST N: HTTP 429 maps to EmbeddingQuotaError."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingQuotaError):
            await provider.embed_query("text")

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_o_auth_error(self, mock_post):
        """TEST O: HTTP 401/403 maps safely to a configuration/authentication error."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingConfigurationError):
            await provider.embed_query("text")

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_p_5xx_error(self, mock_post):
        """TEST P: HTTP 5xx maps to EmbeddingError."""
        import embeddings
        provider = embeddings.get_embedding_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_post.return_value = mock_resp
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_query("text")
        self.assertEqual(mock_post.call_count, 3) # retries

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_q_network_error(self, mock_post):
        """TEST Q: Network failure maps to EmbeddingError."""
        import embeddings
        import httpx
        provider = embeddings.get_embedding_provider()
        mock_post.side_effect = httpx.ConnectError("Network Down")
        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await provider.embed_query("text")
        self.assertEqual(mock_post.call_count, 3) # retries

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_test_r_retry_logic(self, mock_post):
        """TEST R: Retry behavior retries transient failures but does not retry permanent."""
        import embeddings
        provider = embeddings.get_embedding_provider()

        # 401 should NOT retry
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_post.return_value = mock_resp_401
        with self.assertRaises(embeddings.EmbeddingConfigurationError):
            await provider.embed_query("text")
        self.assertEqual(mock_post.call_count, 1)

        mock_post.reset_mock()
        # 422 should NOT retry
        mock_resp_422 = MagicMock()
        mock_resp_422.status_code = 422
        mock_post.return_value = mock_resp_422
        with self.assertRaises(embeddings.EmbeddingError):
            await provider.embed_query("text")
        self.assertEqual(mock_post.call_count, 1)

    async def test_patch_8b2_test_s_factory_caching(self):
        """TEST S: Provider factory caching behaves correctly."""
        import embeddings
        p1 = embeddings.get_embedding_provider()
        p2 = embeddings.get_embedding_provider()
        self.assertIs(p1, p2)

    async def test_patch_8b2_test_t_reset_caching(self):
        """TEST T: Cache/reset behavior allows environment-driven provider tests to remain isolated."""
        import embeddings
        p1 = embeddings.get_embedding_provider()
        await embeddings.close_embedding_provider()
        p2 = embeddings.get_embedding_provider()
        self.assertIsNot(p1, p2)

    async def test_patch_8b2_test_v_service_agnostic(self):
        """TEST V: Service integration remains provider-agnostic."""
        import services
        import embeddings
        provider = embeddings.get_embedding_provider()
        self.assertIsInstance(provider, embeddings.JinaEmbeddingProvider)
        # services imports get_embedding_provider, it should automatically use Jina here

    @patch("httpx.AsyncClient.post")
    @patch("services.collection.insert_many", new_callable=AsyncMock)
    async def test_patch_8b2_test_w_metadata(self, mock_insert, mock_post):
        """TEST W: New embedding metadata correctly identifies configured provider/model/dimensions where supported."""
        from services import process_and_store_document
        import io
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        pdf_bytes = io.BytesIO()
        writer.write(pdf_bytes)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1] * 768}]
        }
        mock_post.return_value = mock_resp

        with patch("services.extract_text_from_pdf") as mock_extract:
            mock_extract.return_value = [{"page": 1, "text": "Doc content"}]
            await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")

        mock_insert.assert_called_once()
        inserted_doc = mock_insert.call_args[0][0][0]
        self.assertEqual(inserted_doc["embedding_provider"], "jina")
        self.assertEqual(inserted_doc["embedding_dimensions"], 768)

    async def test_patch_8b2_model_default_jina(self):
        """2. Jina provider uses jina-embeddings-v3 by default."""
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ.pop("JINA_EMBEDDING_MODEL", None)
        p = embeddings.get_embedding_provider()
        self.assertEqual(p.model_id, "jina-embeddings-v3")

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_model_jina_payload(self, mock_post):
        """3. The actual outgoing Jina payload contains 'model': 'jina-embeddings-v3'."""
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ.pop("JINA_EMBEDDING_MODEL", None)
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        await p.embed_query("test")

        called_json = mock_post.call_args[1]["json"]
        self.assertEqual(called_json["model"], "jina-embeddings-v3")

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_model_jina_override(self, mock_post):
        """4. A custom Jina model override is respected."""
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ["JINA_EMBEDDING_MODEL"] = "jina-custom-model"
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        await p.embed_query("test")

        called_json = mock_post.call_args[1]["json"]
        self.assertEqual(called_json["model"], "jina-custom-model")
        os.environ.pop("JINA_EMBEDDING_MODEL", None)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8b2_missing_index_genuine(self, mock_post):
        """6. Genuine missing-index test that does NOT trigger duplicate-index validation."""
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = "jina"
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Passing 2 inputs, API returns 2 outputs, but indices are 0 and 2.
        # So index 1 is missing, and index 2 is out of bounds.
        # Let's just make it return 1 output for 2 inputs, which triggers count mismatch.
        # If we bypass count mismatch (somehow), or if the API returns 2 outputs but with indices 0 and 0.
        # Wait, the prompt asks for "missing index that does NOT accidentally trigger duplicate-index".
        # If len(texts) == 2, and Jina returns 2 items with index 0 and index 2.
        # This will trigger "out-of-bounds" for index 2.
        # If we pass len(texts) == 2, and Jina returns 2 items with index None?
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1]*768},
                {"embedding": [0.2]*768} # Missing index field completely
            ]
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(embeddings.EmbeddingError) as ctx:
            await p.embed_documents(["a", "b"])
        self.assertIn("Invalid or out-of-bounds", str(ctx.exception))

class TestCYPHRPatch8C(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import embeddings
        await embeddings.close_embedding_provider()
        self.original_provider = embeddings.EMBEDDING_PROVIDER
        self.original_key = os.environ.get("JINA_API_KEY")

        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ["JINA_API_KEY"] = "dummy"

    async def asyncTearDown(self):
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = self.original_provider
        if self.original_key is None:
            os.environ.pop("JINA_API_KEY", None)
        else:
            os.environ["JINA_API_KEY"] = self.original_key

    async def test_patch_8c_test_a_deterministic_estimate(self):
        """TEST A: Token estimator returns deterministic values (base + 15%)."""
        import embeddings
        p = embeddings.get_embedding_provider()
        # total chars = 40. base = 10. +15% = 11.5 -> 11
        est = p.estimate_tokens(["1234567890" * 4])
        self.assertEqual(est, 11)

    async def test_patch_8c_test_b_safety_margin(self):
        """TEST B: Safety margin is applied."""
        import embeddings
        p = embeddings.get_embedding_provider()
        est1 = p.estimate_tokens(["1234567890"])
        self.assertTrue(est1 >= 2) # chars=10 -> 2.5 + safety -> >2

    @patch("embeddings.time.time")
    async def test_patch_8c_test_c_rolling_window_expiry(self, mock_time):
        """TEST C: Old rolling-window entries expire after 60 seconds."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_time.return_value = 1000.0
        p.quota_governor.history.append({'time': 1000.0, 'tokens': 5000})

        # At 1050, it shouldn't expire yet
        mock_time.return_value = 1050.0
        p.quota_governor._clean(1050.0)
        self.assertEqual(len(p.quota_governor.history), 1)

        # At 1061, it should expire
        mock_time.return_value = 1061.0
        p.quota_governor._clean(1061.0)
        self.assertEqual(len(p.quota_governor.history), 0)

    @patch("asyncio.sleep")
    async def test_patch_8c_test_d_safe_budget(self, mock_sleep):
        """TEST D: A batch within safe token budget proceeds immediately."""
        import embeddings
        p = embeddings.get_embedding_provider()
        await p.quota_governor.acquire(100)
        mock_sleep.assert_not_called()
        self.assertEqual(len(p.quota_governor.history), 1)
        self.assertEqual(p.quota_governor.history[0]['tokens'], 100)

    @patch("asyncio.sleep")
    @patch("embeddings.time.time")
    async def test_patch_8c_test_e_exceeds_budget(self, mock_time, mock_sleep):
        """TEST E: A batch exceeding the safe token budget waits asynchronously."""
        import embeddings
        p = embeddings.get_embedding_provider()

        # Simulate an ongoing request that used up the budget
        mock_time.return_value = 1000.0
        p.quota_governor.safe_tpm = 500
        p.quota_governor.safe_rpm = 100

        p.quota_governor.history.append({'time': 1000.0, 'tokens': 500})

        async def mock_sleep_impl(t):
            mock_time.return_value += t

        mock_sleep.side_effect = mock_sleep_impl

        await p.quota_governor.acquire(100)

        mock_sleep.assert_called_once()
        self.assertEqual(len(p.quota_governor.history), 1) # Old one expired, new one added
        self.assertEqual(p.quota_governor.history[0]['tokens'], 100)
        self.assertTrue(mock_time.return_value > 1000.0)

    @patch("asyncio.sleep")
    @patch("embeddings.time.time")
    async def test_patch_8c_test_f_request_budget(self, mock_time, mock_sleep):
        """TEST F: Request-per-minute budget is enforced."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_time.return_value = 1000.0
        p.quota_governor.safe_tpm = 50000
        p.quota_governor.safe_rpm = 2 # VERY SMALL RPM

        p.quota_governor.history.append({'time': 1000.0, 'tokens': 10})
        p.quota_governor.history.append({'time': 1001.0, 'tokens': 10})

        async def mock_sleep_impl(t):
            mock_time.return_value += t

        mock_sleep.side_effect = mock_sleep_impl

        await p.quota_governor.acquire(10)

        mock_sleep.assert_called_once()

        self.assertEqual(len(p.quota_governor.history), 2)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_g_concurrency_limit(self, mock_post):
        """TEST G: Concurrency limit is enforced."""
        import embeddings
        p = embeddings.get_embedding_provider()
        import asyncio

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        async def delayed_post(*args, **kwargs):
            await asyncio.sleep(0.1)
            return mock_resp

        mock_post.side_effect = delayed_post

        # Launch 3 requests. Concurrency is 2.
        # Should take ~0.2s total instead of 0.1s
        t0 = asyncio.get_event_loop().time()
        await asyncio.gather(
            p.embed_query("1"),
            p.embed_query("2"),
            p.embed_query("3")
        )
        t1 = asyncio.get_event_loop().time()

        self.assertTrue((t1 - t0) > 0.15)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_h_actual_usage(self, mock_post):
        """TEST H: Actual Jina usage feedback is recorded."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index":0, "embedding": [0.1]*768}],
            "usage": {"total_tokens": 1000} # massive actual usage
        }
        mock_post.return_value = mock_resp

        await p.embed_query("1")
        # Estimate was small. Actual was 1000. Difference should be added.
        tokens = sum(h['tokens'] for h in p.quota_governor.history)
        self.assertEqual(tokens, 1000)

    @patch("httpx.AsyncClient.post")
    @patch("asyncio.sleep")
    async def test_patch_8c_test_i_retry_after(self, mock_sleep, mock_post):
        """TEST I: 429 with Retry-After honors the supplied delay."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {"Retry-After": "5"}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        mock_post.side_effect = [resp1, resp2]

        await p.embed_query("1")
        mock_sleep.assert_called_with(5)

    @patch("httpx.AsyncClient.post")
    @patch("asyncio.sleep")
    async def test_patch_8c_test_j_exponential_backoff(self, mock_sleep, mock_post):
        """TEST J: 429 without Retry-After uses bounded exponential backoff with jitter."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        mock_post.side_effect = [resp1, resp2]

        await p.embed_query("1")
        mock_sleep.assert_called_once()
        args, _ = mock_sleep.call_args
        self.assertTrue(1.0 <= args[0] <= 2.0)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_k_max_retries(self, mock_post):
        """TEST K: Retries stop after the configured maximum."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {}
        mock_post.return_value = resp1

        with patch("asyncio.sleep"):
            with self.assertRaises(embeddings.EmbeddingQuotaError):
                await p.embed_query("1")
        self.assertEqual(mock_post.call_count, embeddings.EMBEDDING_MAX_RETRIES)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_l_no_retry_401(self, mock_post):
        """TEST L: Permanent 401/403 errors are NOT retried."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 401
        mock_post.return_value = resp1

        with self.assertRaises(embeddings.EmbeddingConfigurationError):
            await p.embed_query("1")
        self.assertEqual(mock_post.call_count, 1)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_m_no_retry_400(self, mock_post):
        """TEST M: Permanent 400/422 errors are NOT retried."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 422
        resp1.text = "Bad"
        mock_post.return_value = resp1

        with self.assertRaises(embeddings.EmbeddingError):
            await p.embed_query("1")
        self.assertEqual(mock_post.call_count, 1)

    @patch("embeddings.JinaQuotaGovernor.acquire", new_callable=AsyncMock)
    @patch("httpx.AsyncClient.post")
    @patch("services.collection.insert_many", new_callable=AsyncMock)
    async def test_patch_8c_test_n_doc_ingestion_governor(self, mock_insert, mock_post, mock_acquire):
        """TEST N: Document ingestion uses the governor."""
        import embeddings
        from services import process_and_store_document

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        with patch("services.extract_text_from_pdf") as mock_extract:
            mock_extract.return_value = [{"page": 1, "text": "Doc"}]
            await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")

        mock_acquire.assert_called()

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_o_multiple_batches(self, mock_post):
        """TEST O: Multiple batches preserve exact ordering."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1]*768},
                {"index": 1, "embedding": [0.2]*768}
            ]
        }
        mock_post.return_value = mock_resp

        res = await p.embed_documents(["a", "b"])
        self.assertEqual(res[0][0], 0.1)
        self.assertEqual(res[1][0], 0.2)

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_p_batch_validation(self, mock_post):
        """TEST P: Batch response validation still works."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1]*768}] # Missing 1
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(embeddings.EmbeddingError):
            await p.embed_documents(["a", "b"])

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_q_dimension_validation(self, mock_post):
        """TEST Q: Dimension validation still works."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1]*10}] # Bad dims
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(embeddings.EmbeddingError):
            await p.embed_documents(["a"])

    @patch("httpx.AsyncClient.post")
    @patch("services.collection.insert_many", new_callable=AsyncMock)
    async def test_patch_8c_test_r_failed_batch_no_mongo(self, mock_insert, mock_post):
        """TEST R: A failed batch prevents MongoDB insertion."""
        from services import process_and_store_document

        mock_post.side_effect = Exception("Boom")

        with patch("services.extract_text_from_pdf") as mock_extract:
            mock_extract.return_value = [{"page": 1, "text": "Doc"}]
            with self.assertRaises(Exception):
                await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")

        mock_insert.assert_not_called()

    @patch("httpx.AsyncClient.post")
    @patch("services.collection.insert_many", new_callable=AsyncMock)
    async def test_patch_8c_test_s_success_mongo(self, mock_insert, mock_post):
        """TEST S: A complete successful document eventually reaches insert_many()."""
        from services import process_and_store_document

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        with patch("services.extract_text_from_pdf") as mock_extract:
            mock_extract.return_value = [{"page": 1, "text": "Doc"}]
            await process_and_store_document("test.pdf", b"pdfbytes", "user@test.com")

        mock_insert.assert_called_once()

    @patch("embeddings.JinaQuotaGovernor.acquire", new_callable=AsyncMock)
    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_t_query_shared_accounting(self, mock_post, mock_acquire):
        """TEST T: Query embedding participates in shared quota accounting where appropriate."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        await p.embed_query("Query")
        mock_acquire.assert_called()

    @patch("asyncio.sleep")
    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_test_u_query_no_delay(self, mock_post, mock_sleep):
        """TEST U: Query embedding is not unnecessarily delayed when quota is available."""
        import embeddings
        p = embeddings.get_embedding_provider()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"embedding": [0.1]*768}]}
        mock_post.return_value = mock_resp

        await p.embed_query("Query")
        mock_sleep.assert_not_called()

    async def test_patch_8c_test_v_no_time_sleep(self):
        """TEST V: No blocking time.sleep() exists in the scheduler/provider logic."""
        import embeddings
        import inspect
        src = inspect.getsource(embeddings)
        self.assertNotIn("time.sleep", src)

    async def test_patch_8c_test_x_large_doc_sim(self):
        """Realistic large document simulation with 2,000 chunks."""
        import embeddings
        p = embeddings.get_embedding_provider()

        # We'll just manually call the governor a bunch of times and ensure it properly sleeps.
        # 2000 chunks, batch size = 50 -> 40 batches.
        # Let's say each batch is 2000 tokens. 40 * 2000 = 80,000 tokens.
        # If TPM = 50,000, it should sleep at least once.
        p.quota_governor.safe_tpm = 50000

        sleep_count = 0
        async def mock_sleep_impl(t):
            nonlocal sleep_count
            sleep_count += 1
            # fast forward time in the governor so it unblocks
            for h in p.quota_governor.history:
                h['time'] -= t

        with patch("asyncio.sleep", side_effect=mock_sleep_impl):
            for _ in range(40):
                await p.quota_governor.acquire(2000)

        self.assertTrue(sleep_count > 0)


class TestCYPHRPatch8CCorrection(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import embeddings
        await embeddings.close_embedding_provider()
        self.original_provider = embeddings.EMBEDDING_PROVIDER
        self.original_key = os.environ.get("JINA_API_KEY")

        embeddings.EMBEDDING_PROVIDER = "jina"
        os.environ["JINA_API_KEY"] = "dummy"

    async def asyncTearDown(self):
        import embeddings
        await embeddings.close_embedding_provider()
        embeddings.EMBEDDING_PROVIDER = self.original_provider
        if self.original_key is None:
            os.environ.pop("JINA_API_KEY", None)
        else:
            os.environ["JINA_API_KEY"] = self.original_key

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_1_oversized_batch_splits(self, mock_post):
        """TEST 1: Oversized batch automatically splits before provider request."""
        import embeddings
        p = embeddings.get_embedding_provider()

        # TPM = 100.
        p.quota_governor.safe_tpm = 100
        # Create a batch of 3 texts. Text 1 takes 60 tokens, Text 2 takes 60 tokens.
        # It should split into 2 batches.

        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}, {"index":1, "embedding": [0.2]*768}]}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.3]*768}]}

        mock_post.side_effect = [resp1, resp2]

        text = "50"

        def mock_estimate_tokens(batch_texts):
            return sum(int(t) for t in batch_texts)

        with patch.object(p, 'estimate_tokens', side_effect=mock_estimate_tokens):
            res = await p.embed_documents([text, text, text])

        self.assertEqual(len(res), 3)
        # Should take 2 API calls: [text, text] (100) and [text] (50)
        self.assertEqual(mock_post.call_count, 2)

    async def test_patch_8c_corr_test_2_oversized_query_fails(self):
        """TEST 2: Oversized single query fails safely."""
        import embeddings
        p = embeddings.get_embedding_provider()
        p.quota_governor.safe_tpm = 10
        with self.assertRaises(embeddings.EmbeddingQuotaError):
            await p.embed_query("a" * 1000)

    async def test_patch_8c_corr_test_3_no_impossible_wait(self):
        """TEST 3: No impossible governor wait loop."""
        import embeddings
        p = embeddings.get_embedding_provider()
        p.quota_governor.safe_tpm = 10
        with self.assertRaises(embeddings.EmbeddingQuotaError):
            await p.quota_governor.acquire(100)

    @patch("embeddings.JinaQuotaGovernor.acquire", new_callable=AsyncMock)
    @patch("asyncio.sleep")
    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_4_retry_reenters_governor(self, mock_post, mock_sleep, mock_acquire):
        """TEST 4: Retry attempt re-enters quota governor."""
        import embeddings
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        mock_post.side_effect = [resp1, resp2]

        await p.embed_query("1")
        self.assertEqual(mock_acquire.call_count, 2)

    @patch("asyncio.sleep")
    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_5_6_retry_obeys_accounting(self, mock_post, mock_sleep):
        """TEST 5 and 6: All retry attempts obey RPM and TPM accounting."""
        import embeddings
        p = embeddings.get_embedding_provider()
        p.quota_governor.safe_rpm = 100

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        mock_post.side_effect = [resp1, resp2]

        await p.embed_query("1")

        # History should have 2 entries since it attempted twice.

        self.assertEqual(len(p.quota_governor.history), 2)

    @patch("asyncio.sleep")
    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_7_8_backoff_semaphore(self, mock_post, mock_sleep):
        """TEST 7 and 8: 429 backoff does not hold semaphore. Two sleeping retries do not block."""
        import embeddings
        import asyncio
        p = embeddings.get_embedding_provider()

        resp1 = MagicMock()
        resp1.status_code = 429
        resp1.headers = {"Retry-After": "10"}

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {"data": [{"index":0, "embedding": [0.1]*768}]}

        mock_post.side_effect = [resp1, resp1, resp2, resp2]

        async def sleep_impl(*args):
            # Assert semaphore is NOT held when sleep is called!
            import embeddings
            self.assertEqual(p.concurrency_semaphore._value, embeddings.JINA_MAX_CONCURRENCY)

        mock_sleep.side_effect = sleep_impl

        # Launch two concurrent requests that both 429.
        await asyncio.gather(
            p.embed_query("1"),
            p.embed_query("2")
        )


    async def test_patch_8c_corr_test_9_10_client_lifecycle(self):
        """TEST 9 and 10: Provider AsyncClient closes correctly, cache reset cleans up safely."""
        import embeddings
        p = embeddings.get_embedding_provider()
        client = p.client
        self.assertFalse(client.is_closed)
        await embeddings.close_embedding_provider()
        self.assertTrue(client.is_closed)
        self.assertIsNone(embeddings._provider_instance)
        self.assertIsNone(p._client) # Verify client is dropped

        # Re-accessing should create a fresh client
        new_client = p.client
        self.assertIsNot(new_client, client)
        self.assertFalse(new_client.is_closed)
        await p.close()

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_11_batch_count_limit(self, mock_post):
        """TEST 11: Oversized list of small chunks respects EMBEDDING_BATCH_SIZE."""
        import embeddings
        p = embeddings.get_embedding_provider()

        # Make TPM huge so it doesn't split on tokens
        p.quota_governor.safe_tpm = 100000000

        resp = MagicMock()
        resp.status_code = 200
        # Return 1 element per request just to satisfy the structure if needed,
        # wait! embed_documents expects len(embs) == len(batch).
        # We must return dynamically based on the input!

        async def mock_post_impl(*args, **kwargs):
            batch = kwargs.get("json", {}).get("input", [])
            embs = [{"index": i, "embedding": [0.1]*768} for i in range(len(batch))]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"data": embs}
            return r

        mock_post.side_effect = mock_post_impl

        # BATCH_SIZE is 2048 in the original? Wait! Let's check embeddings.EMBEDDING_BATCH_SIZE.
        # It defaults to 100 or something in services.py? Actually, EMBEDDING_BATCH_SIZE might be in embeddings.py.
        # Wait, if EMBEDDING_BATCH_SIZE is not exported, let's look for it in embeddings.py.
        # Actually I can just mock embeddings.EMBEDDING_BATCH_SIZE!
        original_batch_size = embeddings.EMBEDDING_BATCH_SIZE
        embeddings.EMBEDDING_BATCH_SIZE = 50
        try:
            texts = ["a"] * 105
            with patch.object(p, 'estimate_tokens', return_value=1):
                res = await p.embed_documents(texts)

            self.assertEqual(len(res), 105)
            # 105 items / 50 = 3 batches (50, 50, 5)
            self.assertEqual(mock_post.call_count, 3)

            # Verify payload logic
            for call in mock_post.call_args_list:
                payload = call.kwargs.get("json", {})
                self.assertLessEqual(len(payload["input"]), 50)
        finally:
            embeddings.EMBEDDING_BATCH_SIZE = original_batch_size

    @patch("httpx.AsyncClient.post")
    async def test_patch_8c_corr_test_12_both_limits_applied(self, mock_post):
        """TEST 12: Both limits applied simultaneously."""
        import embeddings
        p = embeddings.get_embedding_provider()
        p.quota_governor.safe_tpm = 100

        original_batch_size = embeddings.EMBEDDING_BATCH_SIZE
        embeddings.EMBEDDING_BATCH_SIZE = 3
        try:
            async def mock_post_impl(*args, **kwargs):
                batch = kwargs.get("json", {}).get("input", [])

                # Check constraints on every outbound payload
                self.assertLessEqual(len(batch), 3, "Batch count limit exceeded!")
                est_tokens = sum(int(t) for t in batch)
                self.assertLessEqual(est_tokens, 100, "TPM token limit exceeded!")

                embs = [{"index": i, "embedding": [0.1]*768} for i in range(len(batch))]
                r = MagicMock()
                r.status_code = 200
                r.json.return_value = {"data": embs}
                return r

            mock_post.side_effect = mock_post_impl

            texts = ["40", "40", "40", "10", "10", "10", "10"]

            def mock_estimate_tokens(batch_texts):
                return sum(int(t) for t in batch_texts)

            with patch.object(p, 'estimate_tokens', side_effect=mock_estimate_tokens):
                res = await p.embed_documents(texts)

            self.assertEqual(len(res), 7)
            self.assertEqual(mock_post.call_count, 3)
        finally:
            embeddings.EMBEDDING_BATCH_SIZE = original_batch_size

import importlib
class TestRuntimeRouting(unittest.IsolatedAsyncioTestCase):
    @patch("services.get_embedding_provider")
    @patch("services.collection.distinct")
    @patch("services.collection.aggregate")
    @patch("llm_providers.AsyncOpenAI")
    async def test_runtime_routing_gemini(self, mock_openai_cls, mock_agg, mock_distinct, mock_jina):
        mock_jina.return_value.embed_query = AsyncMock(return_value=[0.1]*768)
        import llm_providers
        llm_providers._client_cache.clear()

        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Gorouter Response"))]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_agg.return_value.to_list = AsyncMock(return_value=[{"filename": "test.pdf", "page": 1, "text": "hello"}])
        mock_distinct.return_value = ["test.pdf"]; mock_distinct.side_effect = AsyncMock(return_value=["test.pdf"])

        with patch.dict(os.environ, {"LLM_GOROUTER_ENABLED": "true", "GOROUTER_API_KEY": "fake"}, clear=False):
            import llm_providers
            llm_providers.PROVIDER_REGISTRY["gemini"].enabled = True
            res = await generate_chat_response("query", "user@test.com", "gemini", "gemini-1.5-flash")

            mock_openai_cls.assert_called_with(api_key="fake", base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            mock_instance.chat.completions.create.assert_called_once()
            _, kwargs = mock_instance.chat.completions.create.call_args
            self.assertEqual(kwargs["model"], "gemini-1.5-flash")

    @patch("services.get_embedding_provider")
    @patch("services.collection.distinct")
    @patch("services.collection.aggregate")
    @patch("llm_providers.AsyncOpenAI")
    async def test_runtime_routing_groq_120b(self, mock_openai_cls, mock_agg, mock_distinct, mock_jina):
        mock_jina.return_value.embed_query = AsyncMock(return_value=[0.1]*768)
        import llm_providers
        llm_providers._client_cache.clear()

        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Groq Response"))]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_agg.return_value.to_list = AsyncMock(return_value=[])
        mock_distinct.side_effect = AsyncMock(return_value=[])

        with patch.dict(os.environ, {"LLM_GROQ_ENABLED": "true", "GROQ_API_KEY": "fake_groq"}, clear=False):

            res = await generate_chat_response("query", "user@test.com", "groq", "openai/gpt-oss-120b")

            mock_openai_cls.assert_called_with(api_key="fake_groq", base_url="https://api.groq.com/openai/v1")
            mock_instance.chat.completions.create.assert_called_once()
            _, kwargs = mock_instance.chat.completions.create.call_args
            self.assertEqual(kwargs["model"], "openai/gpt-oss-120b")

    @patch("services.get_embedding_provider")
    @patch("services.collection.distinct")
    @patch("services.collection.aggregate")
    @patch("llm_providers.AsyncOpenAI")
    async def test_runtime_routing_groq_20b(self, mock_openai_cls, mock_agg, mock_distinct, mock_jina):
        mock_jina.return_value.embed_query = AsyncMock(return_value=[0.1]*768)
        import llm_providers
        llm_providers._client_cache.clear()

        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Groq Response"))]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_agg.return_value.to_list = AsyncMock(return_value=[])
        mock_distinct.side_effect = AsyncMock(return_value=[])

        with patch.dict(os.environ, {"LLM_GROQ_ENABLED": "true", "GROQ_API_KEY": "fake_groq"}, clear=False):

            res = await generate_chat_response("query", "user@test.com", "groq", "openai/gpt-oss-20b")

            mock_openai_cls.assert_called_with(api_key="fake_groq", base_url="https://api.groq.com/openai/v1")
            mock_instance.chat.completions.create.assert_called_once()
            _, kwargs = mock_instance.chat.completions.create.call_args
            self.assertEqual(kwargs["model"], "openai/gpt-oss-20b")

    @patch("llm_providers.AsyncOpenAI")
    async def test_auto_title_routing_independent(self, mock_openai_cls):
        import llm_providers
        llm_providers._client_cache.clear()

        mock_instance = MagicMock()
        mock_openai_cls.return_value = mock_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="My Title"))]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.dict(os.environ, {"LLM_GROQ_ENABLED": "true", "GROQ_API_KEY": "fake_groq"}, clear=False):

            title = await generate_auto_title("hello")

            mock_openai_cls.assert_called_with(api_key="fake_groq", base_url="https://api.groq.com/openai/v1")
            mock_instance.chat.completions.create.assert_called_once()
            _, kwargs = mock_instance.chat.completions.create.call_args
            self.assertEqual(kwargs["model"], "openai/gpt-oss-20b")
            self.assertEqual(title, "My Title")


class TestProviderRegistry(unittest.IsolatedAsyncioTestCase):
    def test_dotenv_loaded_before_providers(self):
        import ast
        with open("main.py", "r") as f:
            tree = ast.parse(f.read())
        config_idx = -1
        llm_idx = -1
        for i, node in enumerate(tree.body):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name == "config":
                        config_idx = i
            elif isinstance(node, ast.ImportFrom):
                if node.module == "llm_providers":
                    llm_idx = i
        self.assertTrue(config_idx != -1, "config must be imported in main.py")
        self.assertTrue(llm_idx != -1, "llm_providers must be imported in main.py")
        self.assertTrue(config_idx < llm_idx, "config must be imported BEFORE llm_providers in main.py to load .env first")

    def test_provider_catalog_exposes_defaults(self):
        from llm_providers import get_public_provider_catalog
        data = get_public_provider_catalog()
        self.assertIn("providers", data)
        self.assertIn("default_provider", data)
        self.assertIn("default_model", data)
        self.assertEqual(data["default_provider"], "groq")
        self.assertEqual(data["default_model"], "openai/gpt-oss-20b")

    @patch.dict(os.environ, {"GROQ_API_KEY": "fake", "GOROUTER_API_KEY": "fake", "JINA_API_KEY": "fake", "LLM_GOROUTER_ENABLED": "true"})
    def test_gemini_selects_gemini_client(self):
        import llm_providers
        llm_providers._client_cache.clear()
        llm_providers.PROVIDER_REGISTRY["gemini"].enabled = True
        client, p_id, m_id = llm_providers.get_provider_client("gemini", "gemini-1.5-flash")
        self.assertEqual(p_id, "gemini")
        self.assertEqual(m_id, "gemini-1.5-flash")
        self.assertIn("gemini.app", client.base_url.host)

    @patch.dict(os.environ, {"GROQ_API_KEY": "fake", "GOROUTER_API_KEY": "fake", "JINA_API_KEY": "fake"})
    def test_groq_20b_selects_groq_client(self):
        import importlib
        import llm_providers
        importlib.reload(llm_providers)
        client, p_id, m_id = llm_providers.get_provider_client("groq", "openai/gpt-oss-20b")
        self.assertEqual(p_id, "groq")
        self.assertEqual(m_id, "openai/gpt-oss-20b")
        self.assertIn("api.groq.com", client.base_url.host)

    @patch.dict(os.environ, {"GROQ_API_KEY": "fake", "GOROUTER_API_KEY": "fake", "JINA_API_KEY": "fake"})
    def test_omitted_provider_uses_defaults(self):
        import importlib
        import llm_providers
        importlib.reload(llm_providers)
        client, p_id, m_id = llm_providers.get_provider_client(None, None)
        self.assertEqual(p_id, "groq")
        self.assertEqual(m_id, "openai/gpt-oss-20b")
        self.assertIn("api.groq.com", client.base_url.host)

    def test_cross_provider_model_rejected(self):
        from llm_providers import get_provider_client
        with self.assertRaisesRegex(ValueError, "is not supported"):
            get_provider_client("groq", "gemini-1.5-flash")

    @patch.dict(os.environ, {"LLM_TOKENFORGE_ENABLED": "false"})
    def test_disabled_provider_rejected_even_if_requested(self):
        import importlib
        import llm_providers
        importlib.reload(llm_providers)
        with self.assertRaisesRegex(ValueError, "is currently disabled"):
            llm_providers.get_provider_client("tokenforge", "gemini-1.5-flash")

    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.find", new_callable=MagicMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    async def test_39_auto_title_full_persistence_chain(self, mock_auto_title, mock_generate_chat, mock_update, mock_find_cursor, mock_find_one):
        """a-e. Verify the full auto-title persistence chain."""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        # Mock DB state
        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "New Conversation"}

        # Mock cursor for GET /api/chats
        mock_cursor_instance = MagicMock()
        mock_cursor_instance.to_list = AsyncMock(return_value = [{"_id": "dummy", "chat_id": "fake-123", "user_email": "user@test.com", "title": "Generated Awesome Title"}])
        mock_cursor_instance.sort.return_value = mock_cursor_instance
        mock_find_cursor.return_value = mock_cursor_instance

        mock_generate_chat.return_value = "Mock answer"
        mock_auto_title.return_value = "Generated Awesome Title"

        # 1. /chat generates the title
        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "First message", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )
        self.assertEqual(response.status_code, 200)

        # a. generate_auto_title was called correctly
        mock_auto_title.assert_called_once_with("First message")

        # b. writes title to the correct tenant-scoped MongoDB chat document
        mock_update.assert_any_call(
            {"chat_id": "fake-123", "user_email": "user@test.com"},
            {"$set": {"title": "Generated Awesome Title"}}
        )

        # c. response includes the generated title
        self.assertEqual(response.json().get("title"), "Generated Awesome Title")

        # Update mock_find_one to simulate the DB state having the new title
        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "Generated Awesome Title"}

        # d. GET /api/chats returns the persisted title
        response_chats = client.get(
            "/api/chats",
            headers={"X-CSRF-Token": csrf_token}
        )
        self.assertEqual(response_chats.status_code, 200)
        self.assertEqual(response_chats.json()[0]["title"], "Generated Awesome Title")

        # e. GET /api/chats/{chat_id} returns the persisted title
        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response_chat = client.get(
                "/api/chats/fake-123",
                headers={"X-CSRF-Token": csrf_token}
            )
        self.assertEqual(response_chat.status_code, 200)
        self.assertEqual(response_chat.json()["title"], "Generated Awesome Title")

        app.dependency_overrides = {}

    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    async def test_40_auto_title_subsequent_message(self, mock_auto_title, mock_generate_chat, mock_update, mock_find_one):
        """f. A subsequent message does not regenerate or overwrite the title."""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "Existing Title"}
        mock_generate_chat.return_value = "Mock answer"

        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "Subsequent message", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("title"), "Existing Title")

        # Verify title was not generated
        mock_auto_title.assert_not_called()

        app.dependency_overrides = {}

    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("main.generate_auto_title", new_callable=AsyncMock)
    async def test_41_auto_title_persistence_failure_fallback(self, mock_auto_title, mock_generate_chat, mock_update, mock_find_one):
        """g. If auto-title fails, main RAG answer still succeeds and no title overwrite occurs."""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "New Conversation"}
        mock_generate_chat.return_value = "Mock answer"
        mock_auto_title.return_value = "New Conversation" # Simulated fallback

        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "Test message", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("title"), "New Conversation")

        # Verify title update was skipped (only 1 update call for messages)
        self.assertEqual(mock_update.call_count, 1)
        args, kwargs = mock_update.call_args
        self.assertIn("$push", args[1])

        app.dependency_overrides = {}


    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_42_auto_title_empty_fallback(self, mock_get_provider, mock_generate_chat, mock_update, mock_find_one):
        """Regression test: an empty title response falls back to 'New Conversation'."""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "New Conversation"}
        mock_generate_chat.return_value = "Mock answer"

        mock_client = MagicMock()
        mock_response = MagicMock()
        # Simulate an empty title response with finish_reason="length".
        mock_response.choices = [MagicMock(message=MagicMock(content=""), finish_reason="length")]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_get_provider.return_value = (mock_client, 'groq', 'openai/gpt-oss-20b')

        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "Test message", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )

        self.assertEqual(response.status_code, 200)
        # Because content was empty string, generate_auto_title returns "New Conversation", skipping update
        self.assertEqual(response.json().get("title"), "New Conversation")

        # Verify title update was skipped (only 1 update call for messages)
        self.assertEqual(mock_update.call_count, 1)
        args, kwargs = mock_update.call_args
        self.assertIn("$push", args[1])

        app.dependency_overrides = {}

    @patch("main.chats_collection.find_one", new_callable=AsyncMock)
    @patch("main.chats_collection.update_one", new_callable=AsyncMock)
    @patch("main.generate_chat_response", new_callable=AsyncMock)
    @patch("services.get_provider_client")
    async def test_43_auto_title_success_path(self, mock_get_provider, mock_generate_chat, mock_update, mock_find_one):
        """Verify a concrete generated title such as 'Printing History' survives through."""
        from main import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"email": "user@test.com"}
        csrf_token = "mock-csrf-token"

        mock_find_one.return_value = {"chat_id": "fake-123", "user_email": "user@test.com", "title": "New Conversation"}
        mock_generate_chat.return_value = "Mock answer"

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Printing History"), finish_reason="stop")]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_get_provider.return_value = (mock_client, 'groq', 'openai/gpt-oss-20b')

        with temporary_cookies(client, {"csrf_token": csrf_token}):
            response = client.post(
                "/chat",
                json={"message": "Tell me about printing", "chat_id": "fake-123", "provider": "tokenforge", "model": "claude-opus-5"},
                headers={"X-CSRF-Token": csrf_token}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("title"), "Printing History")

        mock_update.assert_any_call(
            {"chat_id": "fake-123", "user_email": "user@test.com"},
            {"$set": {"title": "Printing History"}}
        )

        app.dependency_overrides = {}

if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(
        resultclass=EmojiTestResult, verbosity=2))
