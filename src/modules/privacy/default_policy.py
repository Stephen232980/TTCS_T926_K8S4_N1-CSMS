"""Engineering policy selected under the project owner's delegated authority.

Financial periods are minimums; this implementation never auto-deletes money.
"""

VERSION = "CSMS-PRIVACY-2026-01"
DOCUMENT = {
    "version": VERSION,
    "approval_basis": "project_owner_delegated_policy_selection",
    "mode": "unlink_original_account_preserve_financials",
    "identity": "redact_after_approved_request_and_financial_gates",
    "financial_minimum_years": 10,
    "financial_expiry": "manual_review_no_automatic_delete",
    "operational_history": "preserve_measurements_remove_original_identity_links",
    "pending_ocpp": "never_delete_by_age",
    "legal_hold": "blocks_privacy_execution",
    "sources": [
        "https://vanban.chinhphu.vn/default.aspx?docid=183198&pageid=27160",
        "https://vanban.bocongan.gov.vn/co-so-du-lieu-van-ban/luat-bao-ve-du-lieu-ca-nhan-1753688803",
    ],
}
