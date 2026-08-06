"""
NON-SHIPPED — optional web enrichment stub.

Cross-referencing LinkedIn/G2 to verify market-positioning claims from a CIM
was considered and explicitly left out of scope for this version.

Do not import this module from the pipeline. Kept only as a placeholder so the
roadmap is visible without implying a live enrichment path.

See README.md "Honest limits" and docs/INTERVIEW.md.
"""


def verify_market_claims(claims: list[str]) -> dict[str, bool]:
    """
    Stub only — not wired into pipeline or API.

    Would verify claims against LinkedIn/G2 (or similar). Returns claim → verified.
    """
    raise NotImplementedError(
        "web_enrichment is non-shipped; market claims are not verified via the web"
    )
