"""Canonical category taxonomy used by rules + LLM categorisation."""

CATEGORIES: dict[str, list[str]] = {
    "Salary & Income": ["Salary", "Bonus", "Cashback", "Refund", "Interest Earned", "Dividend"],
    "Groceries": ["Online Grocery", "Supermarket"],
    "Dining": ["Food Delivery", "Restaurant", "Café"],
    "Transport": ["Cab/Rideshare", "Fuel", "Toll", "Parking", "Public Transit"],
    "Shopping": ["Online Shopping", "Clothing", "Personal Care", "Electronics"],
    "Utilities": [
        "Electricity", "Mobile Recharge", "Internet", "DTH", "Gas", "Water",
    ],
    "Rent & Housing": ["Rent", "Maintenance"],
    "Healthcare": ["Hospital", "Pharmacy", "Doctor", "Lab Tests"],
    "Entertainment": ["Streaming", "Movies", "Gaming"],
    "Education": ["Courses", "Fees"],
    "Travel": ["Travel Booking", "Train", "Flight", "Hotel", "Bus"],
    "EMI & Loans": ["Personal Loan EMI", "Home Loan EMI", "Car Loan EMI"],
    "Investments": [
        "SIP", "Mutual Fund", "Stocks", "NPS", "PPF", "Fixed Deposit",
        "Recurring Deposit",
    ],
    "Insurance": ["Life Insurance", "Health Insurance", "Vehicle Insurance"],
    "Cash": ["ATM Withdrawal", "Cash Deposit"],
    "Fees & Charges": ["GST", "Service Charge", "Penalty", "Annual Fee", "Bank Fee"],
    "Donations & Gifts": ["Charity", "Religious", "Gifts"],
    "Transfer": ["Self Transfer", "UPI Transfer"],
    "Other": ["Uncategorised"],
}
