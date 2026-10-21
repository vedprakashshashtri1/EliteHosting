import sys
import tempfile
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parent.parent
if "elite_cloud" not in sys.modules:
    package = types.ModuleType("elite_cloud")
    package.__path__ = [str(REPO_ROOT)]
    sys.modules["elite_cloud"] = package

orchestrator_package = types.ModuleType("elite_cloud.orchestrator")
orchestrator_package.__path__ = [str(REPO_ROOT / "orchestrator")]
sys.modules["elite_cloud.orchestrator"] = orchestrator_package

config_spec = importlib.util.spec_from_file_location("elite_cloud.config", REPO_ROOT / "config.py")
config_module = importlib.util.module_from_spec(config_spec)
sys.modules["elite_cloud.config"] = config_module
config_spec.loader.exec_module(config_module)

pages_spec = importlib.util.spec_from_file_location(
    "elite_cloud.orchestrator.cloudflare_pages",
    REPO_ROOT / "orchestrator" / "cloudflare_pages.py",
)
pages_module = importlib.util.module_from_spec(pages_spec)
sys.modules["elite_cloud.orchestrator.cloudflare_pages"] = pages_module
pages_spec.loader.exec_module(pages_module)
CloudflarePagesDeployer = pages_module.CloudflarePagesDeployer


def api_response(result, status_code=200):
    response = Mock()
    response.ok = 200 <= status_code < 300
    response.status_code = status_code
    response.reason = "OK" if response.ok else "Error"
    response.json.return_value = {"success": response.ok, "result": result, "errors": []}
    return response


class CloudflarePagesDeployerTests(unittest.TestCase):
    def test_sanitizes_pages_project_name(self):
        self.assertEqual(
            CloudflarePagesDeployer.project_name(" My Beautiful_SITE.zip "),
            "my-beautiful-site-zip",
        )

    @patch("elite_cloud.orchestrator.cloudflare_pages.requests.request")
    @patch("elite_cloud.orchestrator.cloudflare_pages.requests.get")
    def test_direct_upload_creates_manifest_and_returns_public_url(self, mock_get, mock_request):
        mock_get.return_value = api_response({"name": "demo-site"})

        def request_result(method, url, **kwargs):
            if url.endswith("/upload-token"):
                return api_response({"jwt": "short-lived-upload-token"})
            if url.endswith("/check-missing"):
                return api_response(kwargs["json"]["hashes"])
            if url.endswith("/deployments"):
                return api_response({"id": "deployment-123"})
            return api_response({})

        mock_request.side_effect = request_result
        deployer = CloudflarePagesDeployer()
        deployer.account_id = "account-id"
        deployer.api_token = "api-token"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
            result = deployer.deploy(root, "Demo Site")

        self.assertEqual(result["url"], "https://demo-site.pages.dev")
        self.assertEqual(result["deployment_id"], "deployment-123")

        deployment_call = next(
            call for call in mock_request.call_args_list
            if call.args[1].endswith("/deployments")
        )
        manifest = deployment_call.kwargs["files"]["manifest"][1]
        self.assertIn('"/index.html"', manifest)
        self.assertIn('"/assets/app.js"', manifest)


if __name__ == "__main__":
    unittest.main()

