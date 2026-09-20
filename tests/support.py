"""Shared test support: fixture-backed HTTP, no network ever touches a test."""
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "tests" / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from sources import common  # noqa: E402


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_http_get(url: str, headers=None, timeout=30) -> bytes:
    """Serve recorded responses instead of calling the network."""
    u = url.lower()
    if "export.arxiv.org" in u:
        return _fixture_bytes("arxiv_atom_kvcache.xml")
    if "api.github.com/search/repositories" in u:
        return _fixture_bytes("github_search_kvcache.json")
    if "api.github.com/repos/" in u and u.rstrip("/").endswith("readme"):
        return b"# fixture repo readme\n"
    if "huggingface.co/api/models" in u:
        return _fixture_bytes("huggingface_models_kvcache.json")
    if "huggingface.co/api/datasets" in u:
        return b"[]"
    if "api.openalex.org/works/w" in u or "api.openalex.org/works?filter=cites" in u:
        return _fixture_bytes("openalex_search_kvcache.json")
    if "api.openalex.org/works" in u:
        return _fixture_bytes("openalex_search_kvcache.json")
    raise AssertionError("test tried to reach the network: " + url)


def install_fixtures():
    common.set_http_get(fixture_http_get)


def uninstall_fixtures():
    common.set_http_get(None)


def sample_items():
    """The eight real top hits for 'long context attention' (2026-09-20)."""
    return [
        dict(id="openalex:W2293040502", source="openalex", type="paper",
             title="The ASA Statement on p-Values: Context, Process, and Purpose",
             venue="The American Statistician", citations=6313, year=2016,
             pdf_url="https://example.org/a.pdf",
             abstract="Widely used statistical rituals are criticized."),
        dict(id="arxiv:1406.2661", source="arxiv", type="paper",
             title="Generative Adversarial Networks", venue="arXiv",
             citations=4625, year=2014, pdf_url="https://arxiv.org/pdf/1406.2661",
             abstract="We propose a new framework for estimating generative models."),
        dict(id="openalex:W3122136669", source="openalex", type="paper",
             title="In Search of Attention", venue="The Journal of Finance",
             citations=3196, year=2011, pdf_url="https://example.org/b.pdf",
             abstract="We propose a new measure of investor attention."),
        dict(id="arxiv:2004.05150", source="arxiv", type="paper",
             title="Longformer: The Long-Document Transformer", venue="arXiv",
             citations=2205, year=2020, pdf_url="https://arxiv.org/pdf/2004.05150",
             abstract="Transformer-based models are unable to process long "
                      "sequences due to their self-attention operation."),
        dict(id="arxiv:2205.14135", source="arxiv", type="paper",
             title="FlashAttention: Fast and Memory-Efficient Exact Attention "
                   "with IO-Awareness", venue="arXiv", citations=463, year=2022,
             pdf_url="https://arxiv.org/pdf/2205.14135",
             abstract="Transformers are slow and memory-hungry on long "
                      "sequences, making context length a bottleneck."),
        dict(id="openalex:W2129375421", source="openalex", type="paper",
             title="Long Noncoding RNAs: Past, Present, and Future",
             venue="Genetics", citations=1942, year=2013,
             pdf_url="https://example.org/c.pdf",
             abstract="Long noncoding RNAs have gained widespread attention."),
        dict(id="openalex:W2162482203", source="openalex", type="paper",
             title="Tacit knowledge and the economic geography of context",
             venue="Journal of Economic Geography", citations=1972, year=2002,
             abstract="This paper discusses the role of context in economic "
                      "geography and the explicitness of knowledge."),
        dict(id="openalex:W2914686075", source="openalex", type="paper",
             title="Attention-deficit hyperactivity disorder", venue="The Lancet",
             citations=1468, year=2005,
             abstract="ADHD is a common childhood behavioural disorder."),
    ]
