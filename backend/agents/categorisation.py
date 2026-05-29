"""Categorisation Agent — assigns categories to transactions.

Two-tier approach:
1. Rule/keyword matching (fast, free, deterministic) — confidence 1.0
2. LLM fallback for unmatched transactions — confidence from model

Transactions with confidence < 0.7 get needs_review = True.
"""

import logging
import re
from decimal import Decimal
from typing import Optional

from backend.llm.provider import CategorisationResult, LLMProvider
from backend.models.transaction import Transaction

logger = logging.getLogger(__name__)

# Confidence threshold below which transactions need human review
REVIEW_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# Rule-based keyword patterns
# Maps pattern (regex) -> (category, subcategory, confidence)
# Order matters: first match wins
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[str, str, Optional[str], float]] = [
    # Salary & Income
    (r"\bSALARY\b", "Salary & Income", "Salary", 1.0),
    (r"\bNETSALARY\b", "Salary & Income", "Salary", 1.0),
    (r"\bBONUS\b", "Salary & Income", "Bonus", 0.9),
    (r"\bCASHBACK\b", "Salary & Income", "Cashback", 0.95),
    (r"\bREFUND\b", "Salary & Income", "Refund", 0.9),
    (r"\bINTEREST\b", "Salary & Income", "Interest Earned", 0.9),
    (r"\bDIVIDEND\b", "Salary & Income", "Dividend", 0.9),

    # Groceries
    (r"\bBIG\s*BASKET\b", "Groceries", "Online Grocery", 1.0),
    (r"\bBIGBASKET\b", "Groceries", "Online Grocery", 1.0),
    (r"\bBLINKIT\b", "Groceries", "Online Grocery", 1.0),
    (r"\bZEPTO\b", "Groceries", "Online Grocery", 1.0),
    (r"\bINSTAMART\b", "Groceries", "Online Grocery", 1.0),
    (r"\bGROCER\b", "Groceries", "Supermarket", 0.9),
    (r"\bSUPER\s*MARKET\b", "Groceries", "Supermarket", 0.9),
    (r"\bDMART\b", "Groceries", "Supermarket", 1.0),
    (r"\bMORE\s*RETAIL\b", "Groceries", "Supermarket", 0.9),
    (r"\bSPENCER\b", "Groceries", "Supermarket", 0.9),
    (r"\bSTAR\s*BAZAAR\b", "Groceries", "Supermarket", 0.9),
    (r"\bRELIANCE\s*FRESH\b", "Groceries", "Supermarket", 0.9),
    (r"\bNATURE.*BASKET\b", "Groceries", "Supermarket", 0.9),

    # Dining
    (r"\bSWIGGY\b", "Dining", "Food Delivery", 1.0),
    (r"\bZOMATO\b", "Dining", "Food Delivery", 1.0),
    (r"\bUBER\s*EATS\b", "Dining", "Food Delivery", 1.0),
    (r"\bDUNZO\b", "Dining", "Food Delivery", 0.85),
    (r"\bDOMINOS\b", "Dining", "Food Delivery", 1.0),
    (r"\bMCDONALD\b", "Dining", "Restaurant", 1.0),
    (r"\bKFC\b", "Dining", "Restaurant", 1.0),
    (r"\bSUBWAY\b", "Dining", "Restaurant", 1.0),
    (r"\bPIZZA\s*HUT\b", "Dining", "Restaurant", 1.0),
    (r"\bSTARBUCK\b", "Dining", "Café", 1.0),
    (r"\bCCD\b", "Dining", "Café", 0.9),
    (r"\bCAFE\b", "Dining", "Café", 0.85),
    (r"\bRESTAURANT\b", "Dining", "Restaurant", 0.9),
    # Hotel in India often means restaurant
    (r"\bHOTEL\b(?!.*BOOKING)", "Dining", "Restaurant", 0.7),

    # Transport
    (r"\bUBER\b(?!\s*EAT)", "Transport", "Cab/Rideshare", 1.0),
    (r"\bOLA\b", "Transport", "Cab/Rideshare", 1.0),
    (r"\bRAPIDO\b", "Transport", "Cab/Rideshare", 1.0),
    (r"\bFUEL\b", "Transport", "Fuel", 0.95),
    (r"\bPETROL\b", "Transport", "Fuel", 1.0),
    (r"\bDIESEL\b", "Transport", "Fuel", 1.0),
    (r"\bHP\s*PAY\b", "Transport", "Fuel", 0.9),
    (r"\bBPCL\b", "Transport", "Fuel", 1.0),
    (r"\bIOCL\b", "Transport", "Fuel", 1.0),
    (r"\bINDIAN\s*OIL\b", "Transport", "Fuel", 1.0),
    (r"\bFASTAG\b", "Transport", "Toll", 1.0),
    (r"\bTOLL\b", "Transport", "Toll", 0.95),
    (r"\bPARKING\b", "Transport", "Parking", 0.95),
    (r"\bMETRO\b", "Transport", "Public Transit", 0.85),

    # Shopping
    (r"\bAMAZON\b", "Shopping", "Online Shopping", 1.0),
    (r"\bFLIPKART\b", "Shopping", "Online Shopping", 1.0),
    (r"\bMYNTRA\b", "Shopping", "Clothing", 1.0),
    (r"\bAJIO\b", "Shopping", "Clothing", 1.0),
    (r"\bNYKAA\b", "Shopping", "Personal Care", 1.0),
    (r"\bCROMA\b", "Shopping", "Electronics", 1.0),
    (r"\bRELIANCE\s*DIGITAL\b", "Shopping", "Electronics", 1.0),
    (r"\bMEESHO\b", "Shopping", "Online Shopping", 1.0),
    (r"\bSNAPDEAL\b", "Shopping", "Online Shopping", 1.0),

    # Utilities
    (r"\bELECTRIC\b", "Utilities", "Electricity", 0.95),
    (r"\bBESCOM\b", "Utilities", "Electricity", 1.0),
    (r"\bTPDDL\b", "Utilities", "Electricity", 1.0),
    (r"\bBSES\b", "Utilities", "Electricity", 1.0),
    (r"\bJIO\b", "Utilities", "Mobile Recharge", 0.9),
    (r"\bAIRTEL\b", "Utilities", "Mobile Recharge", 0.9),
    (r"\bVODAFONE\b", "Utilities", "Mobile Recharge", 0.9),
    (r"\bVI\s+RECHARGE\b", "Utilities", "Mobile Recharge", 0.9),
    (r"\bBROADBAND\b", "Utilities", "Internet", 0.95),
    (r"\bWIFI\b", "Utilities", "Internet", 0.85),
    (r"\bACT\s*FIBERNET\b", "Utilities", "Internet", 1.0),
    (r"\bTATASKY\b", "Utilities", "DTH", 1.0),
    (r"\bDISH\s*TV\b", "Utilities", "DTH", 1.0),
    (r"\bRECHARGE\b", "Utilities", "Mobile Recharge", 0.8),
    (r"\bMOBILE\s*BILL\b", "Utilities", "Mobile Recharge", 0.9),
    (r"\bGAS\s*BILL\b", "Utilities", "Gas", 0.95),
    (r"\bWATER\s*BILL\b", "Utilities", "Water", 0.95),
    (r"\bPIPED\s*GAS\b", "Utilities", "Gas", 0.95),

    # Rent & Housing
    (r"\bRENT\b", "Rent & Housing", "Rent", 0.9),
    (r"\bMAINTENANCE\b", "Rent & Housing", "Maintenance", 0.85),
    (r"\bSOCIETY\b", "Rent & Housing", "Maintenance", 0.8),

    # Healthcare
    (r"\bAPOLLO\b", "Healthcare", "Hospital", 0.9),
    (r"\bPHARMA\b", "Healthcare", "Pharmacy", 0.9),
    (r"\bMEDICAL\b", "Healthcare", "Doctor", 0.85),
    (r"\bNETMEDS\b", "Healthcare", "Pharmacy", 1.0),
    (r"\bPHARMEASY\b", "Healthcare", "Pharmacy", 1.0),
    (r"\b1MG\b", "Healthcare", "Pharmacy", 1.0),
    (r"\bHOSPITAL\b", "Healthcare", "Hospital", 0.9),
    (r"\bCLINIC\b", "Healthcare", "Doctor", 0.85),
    (r"\bDIAGNOSTIC\b", "Healthcare", "Lab Tests", 0.9),
    (r"\bPATHOLOGY\b", "Healthcare", "Lab Tests", 0.9),

    # Entertainment
    (r"\bNETFLIX\b", "Entertainment", "Streaming", 1.0),
    (r"\bHOTSTAR\b", "Entertainment", "Streaming", 1.0),
    (r"\bDISNEY\b", "Entertainment", "Streaming", 0.9),
    (r"\bPRIME\s*VIDEO\b", "Entertainment", "Streaming", 1.0),
    (r"\bSPOTIFY\b", "Entertainment", "Streaming", 1.0),
    (r"\bYOUTUBE\s*PREMIUM\b", "Entertainment", "Streaming", 1.0),
    (r"\bSONY\s*LIV\b", "Entertainment", "Streaming", 1.0),
    (r"\bPVR\b", "Entertainment", "Movies", 1.0),
    (r"\bINOX\b", "Entertainment", "Movies", 1.0),
    (r"\bBOOKMYSHOW\b", "Entertainment", "Movies", 1.0),
    (r"\bBOOK\s*MY\s*SHOW\b", "Entertainment", "Movies", 1.0),
    (r"\bSTEAM\b", "Entertainment", "Gaming", 0.85),

    # Education
    (r"\bUDEMY\b", "Education", "Courses", 1.0),
    (r"\bCOURSERA\b", "Education", "Courses", 1.0),
    (r"\bSKILLSHARE\b", "Education", "Courses", 1.0),
    (r"\bUNACADEMY\b", "Education", "Courses", 1.0),
    (r"\bBYJU\b", "Education", "Courses", 1.0),
    (r"\bSCHOOL\s*FEE\b", "Education", "Fees", 0.9),
    (r"\bCOLLEGE\b", "Education", "Fees", 0.8),
    (r"\bTUITION\b", "Education", "Fees", 0.9),

    # Travel
    (r"\bMAKEMYTRIP\b", "Travel", "Travel Booking", 1.0),
    (r"\bMMT\b", "Travel", "Travel Booking", 0.9),
    (r"\bGOIBIBO\b", "Travel", "Travel Booking", 1.0),
    (r"\bCLEARTRIP\b", "Travel", "Travel Booking", 1.0),
    (r"\bIRCTC\b", "Travel", "Train", 1.0),
    (r"\bINDIGO\b", "Travel", "Flight", 0.9),
    (r"\bSPICEJET\b", "Travel", "Flight", 1.0),
    (r"\bAIR\s*INDIA\b", "Travel", "Flight", 1.0),
    (r"\bVISTARA\b", "Travel", "Flight", 1.0),
    (r"\bOYO\b", "Travel", "Hotel", 0.9),
    (r"\bAIRBNB\b", "Travel", "Hotel", 1.0),
    (r"\bREDBUS\b", "Travel", "Bus", 1.0),

    # EMI & Loans
    (r"\bEMI\b", "EMI & Loans", None, 0.95),
    (r"\bLOAN\b", "EMI & Loans", None, 0.9),
    (r"\bNACH\b", "EMI & Loans", None, 0.85),
    (r"\bBAJAJ\s*FIN\b", "EMI & Loans", "Personal Loan EMI", 0.9),
    (r"\bHDFC\s*LTD\b", "EMI & Loans", "Home Loan EMI", 0.85),

    # Investments
    (r"\bSIP\b", "Investments", "SIP", 0.95),
    (r"\bMUTUAL\s*FUND\b", "Investments", "Mutual Fund", 0.95),
    (r"\bZERODHA\b", "Investments", "Stocks", 1.0),
    (r"\bGROW\b", "Investments", "Mutual Fund", 0.85),
    (r"\bKUVERA\b", "Investments", "Mutual Fund", 1.0),
    (r"\bCOIN\b.*\bZERODHA\b", "Investments", "Mutual Fund", 1.0),
    (r"\bNPS\b", "Investments", "NPS", 0.9),
    (r"\bPPF\b", "Investments", "PPF", 0.95),
    (r"\bFIXED\s*DEPOSIT\b", "Investments", "Fixed Deposit", 0.95),
    (r"\bFD\b", "Investments", "Fixed Deposit", 0.7),
    (r"\bRD\b", "Investments", "Recurring Deposit", 0.7),

    # Insurance
    (r"\bLIC\b", "Insurance", "Life Insurance", 0.9),
    (r"\bICICI\s*PRUD\b", "Insurance", None, 0.9),
    (r"\bINSURANCE\b", "Insurance", None, 0.85),
    (r"\bPOLICY\s*BAZAAR\b", "Insurance", None, 0.9),

    # Cash
    (r"\bATM\b", "Cash", "ATM Withdrawal", 0.95),
    (r"\bCASH\s*WITHDRAWAL\b", "Cash", "ATM Withdrawal", 1.0),
    (r"\bCASH\s*DEPOSIT\b", "Cash", "Cash Deposit", 1.0),

    # Fees & Charges
    (r"\bGST\b", "Fees & Charges", "GST", 0.9),
    (r"\bCHARGES\b", "Fees & Charges", "Service Charge", 0.8),
    (r"\bPENALTY\b", "Fees & Charges", "Penalty", 0.95),
    (r"\bANNUAL\s*FEE\b", "Fees & Charges", "Annual Fee", 0.95),
    (r"\bBANK\s*FEE\b", "Fees & Charges", "Bank Fee", 0.95),
    (r"\bSERVICE\s*TAX\b", "Fees & Charges", "Service Charge", 0.9),
    (r"\bCESS\b", "Fees & Charges", "GST", 0.8),

    # Donations
    (r"\bDONATION\b", "Donations & Gifts", "Charity", 0.9),
    (r"\bCHARITY\b", "Donations & Gifts", "Charity", 0.95),
    (r"\bTEMPLE\b", "Donations & Gifts", "Religious", 0.85),
    (r"\bCHURCH\b", "Donations & Gifts", "Religious", 0.85),
    (r"\bMOSQUE\b", "Donations & Gifts", "Religious", 0.85),

    # Investments — platforms common in India
    (r"\bANGEL\s*ONE\b", "Investments", "Stocks", 1.0),
    (r"\bANGELBROKING\b", "Investments", "Stocks", 1.0),
    (r"\bUPSTOX\b", "Investments", "Stocks", 1.0),
    (r"\bSMALLCASE\b", "Investments", "Mutual Fund", 1.0),
    (r"\bPAYTM\s*MONEY\b", "Investments", "Mutual Fund", 1.0),
    (r"\bMFAUTOPAY\b", "Investments", "SIP", 1.0),
    (r"\bRD\s*INSTALLMENT\b", "Investments", "Recurring Deposit", 1.0),
    # Atal Pension Yojana NACH debit
    (r"\bAPY\b", "Investments", "NPS", 0.9),

    # EMI — NACH / standing instructions
    (r"\bNACH\b", "EMI & Loans", "Personal Loan EMI", 0.85),
    (r"\bSTANDING\s*INSTRUCTION\b", "EMI & Loans", None, 0.85),
    (r"\bECS\b", "EMI & Loans", None, 0.85),

    # Transfer (low priority — must be last; many UPI transfers could be purchases)
    (r"\bSELF\s*TRANSFER\b", "Transfer", "Self Transfer", 1.0),
    (r"\bFUND\s*TRANSFER\b", "Transfer", None, 0.8),
    # HDFC UPI narrations: "SENT USING PAYTM U" / "SENT USING GPAY U"
    (r"SENT\s+USING\s+(PAYTM|GPAY|GOOGLE\s*PAY|PHONEPE|BHIM)",
     "Transfer", "UPI Transfer", 0.85),
    # GPay description prefix for person-to-person
    (r"^(?:Paidto|ReceivedFrom)[A-Z][A-Za-z]+(?:[A-Z][a-z]+)+$",
     "Transfer", "UPI Transfer", 0.80),
]

# Pre-compile patterns for performance
_COMPILED_RULES = [
    (re.compile(pattern, re.IGNORECASE), category, subcategory, confidence)
    for pattern, category, subcategory, confidence in _KEYWORD_RULES
]


def categorise_by_rules(description: str) -> Optional[CategorisationResult]:
    """Try to categorise a transaction using keyword rules.

    Returns CategorisationResult if a match is found, None otherwise.
    """
    if not description:
        return None

    for pattern, category, subcategory, confidence in _COMPILED_RULES:
        if pattern.search(description):
            return CategorisationResult(
                category=category,
                subcategory=subcategory,
                confidence=confidence,
                rationale=f"Matched keyword rule: {pattern.pattern}",
            )

    return None


def categorise_transactions(
    transactions: list[Transaction],
    llm_provider: Optional[LLMProvider] = None,
) -> list[Transaction]:
    """Categorise a list of transactions using rules + LLM fallback.

    1. Try rule-based matching first (fast, deterministic)
    2. Collect unmatched transactions
    3. Send unmatched to LLM in batch
    4. Mark low-confidence results for review

    Args:
        transactions: List of Transaction objects to categorise.
        llm_provider: Optional LLM provider for fallback categorisation.
            If None, unmatched transactions get category "Other".

    Returns:
        Updated list of Transaction objects with categories assigned.
    """
    categorised = []
    needs_llm: list[tuple[int, Transaction]] = []

    # Tier 1: Rule-based matching
    for i, txn in enumerate(transactions):
        result = categorise_by_rules(txn.raw_description)

        if result:
            txn = txn.model_copy(update={
                "category": result.category,
                "subcategory": result.subcategory,
                "confidence": result.confidence,
                "needs_review": result.confidence < REVIEW_THRESHOLD,
            })
            categorised.append(txn)
            logger.debug(
                "Rule match: '%s' -> %s (%.2f)",
                txn.raw_description[:40],
                result.category,
                result.confidence,
            )
        else:
            needs_llm.append((i, txn))
            categorised.append(txn)  # Placeholder, will be updated

    # Tier 2: LLM fallback for unmatched
    if needs_llm and llm_provider:
        logger.info(
            "Sending %d unmatched transactions to LLM for categorisation.",
            len(needs_llm),
        )

        llm_inputs = [
            {
                "description": txn.raw_description,
                "amount": str(txn.amount),
                "direction": txn.direction.value,
            }
            for _, txn in needs_llm
        ]

        llm_results = llm_provider.categorise_batch(llm_inputs)

        for (orig_idx, txn), result in zip(needs_llm, llm_results):
            updated = txn.model_copy(update={
                "category": result.category,
                "subcategory": result.subcategory,
                "confidence": result.confidence,
                "needs_review": result.confidence < REVIEW_THRESHOLD,
            })
            # Find and replace in the categorised list
            for j, cat_txn in enumerate(categorised):
                if cat_txn.txn_id == txn.txn_id:
                    categorised[j] = updated
                    break

            logger.debug(
                "LLM categorised: '%s' -> %s (%.2f) — %s",
                txn.raw_description[:40],
                result.category,
                result.confidence,
                result.rationale,
            )
    elif needs_llm:
        # No LLM provider — mark as "Other"
        logger.warning(
            "%d transactions could not be rule-matched and no LLM provider available.",
            len(needs_llm),
        )
        for orig_idx, txn in needs_llm:
            updated = txn.model_copy(update={
                "category": "Other",
                "subcategory": "Uncategorised",
                "confidence": 0.0,
                "needs_review": True,
            })
            for j, cat_txn in enumerate(categorised):
                if cat_txn.txn_id == txn.txn_id:
                    categorised[j] = updated
                    break

    # Summary
    rule_count = len(transactions) - len(needs_llm)
    llm_count = len(needs_llm)
    review_count = sum(1 for t in categorised if t.needs_review)
    logger.info(
        "Categorisation complete: %d rule-matched, %d LLM-categorised, %d need review.",
        rule_count,
        llm_count,
        review_count,
    )

    return categorised
