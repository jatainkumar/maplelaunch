"""Synthetic demo personas. All names, numbers and businesses are fictional. IFSC codes are real branch codes so the
live IFSC lookup works; account numbers are made up."""

from app.domain.validators import make_gstin

KUMAR_PAN = "BQXPK4821M"
MEHTA_PAN = "AAKFM7781Q"
SHARMA_PAN = "CVRPS3307L"
NEXA_PAN = "AADCN5521K"
LUCKY_PAN = "AAGCL9043H"
NAIR_PAN = "DHMPN6612R"


def _bank(account, ifsc, holder, bank):
    return {"account_number": account, "ifsc": ifsc, "account_holder_name": holder, "bank_name": bank}


PERSONAS: dict[str, dict] = {
    "happy_path": {
        "title": "Happy path",
        "story": "Proprietor, clean documents. All four checks pass (the PAN provider sends its callback three "
                 "times; duplicates are ignored). The agent auto-approves and a merchant ID is issued.",
        "business_type": "proprietorship", "category": "food_beverage",
        "form": {"legal_name": "Ravi Kumar", "trade_name": "Kumar Chai Corner", "contact_name": "Ravi Kumar",
                 "phone": "9845012345", "email": "ravi.kumar@example.com", "address": "14, 5th Cross, Koramangala",
                 "city": "Bengaluru", "state": "Karnataka", "pincode": "560034", "monthly_volume": 300000,
                 "pan": KUMAR_PAN, "gstin": make_gstin("29", KUMAR_PAN),
                 **_bank("50100234567812", "SBIN0000813", "Ravi Kumar", "State Bank of India")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "RAVI KUMAR", "dob": "1986-04-12"},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "RAVI KUMAR", "trade_name": "KUMAR CHAI CORNER",
                                "constitution": "Proprietorship", "date": "2021-07-01",
                                "address": "14, 5th Cross, Koramangala, Bengaluru, Karnataka 560034"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "scenarios": {"PAN": "duplicate"},
    },
    "gst_cancelled": {
        "title": "GST cancelled → merchant fixes it",
        "story": "Partnership firm. PAN and bank pass but the GST provider reports the GSTIN as cancelled. The agent "
                 "asks for an active GSTIN; the merchant uploads the corrected certificate; only GST is re-verified.",
        "business_type": "partnership", "category": "electronics",
        "form": {"legal_name": "Mehta and Sons Electronics", "trade_name": "Mehta Electronics",
                 "contact_name": "Kiran Mehta", "phone": "9820098765", "email": "accounts@mehta-electronics.example.com",
                 "address": "Shop 7, Lamington Road", "city": "Mumbai", "state": "Maharashtra", "pincode": "400007",
                 "monthly_volume": 1200000, "pan": MEHTA_PAN, "gstin": make_gstin("27", MEHTA_PAN, "9"),
                 **_bank("912020045678123", "HDFC0000240", "Mehta and Sons Electronics", "HDFC Bank")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "MEHTA AND SONS ELECTRONICS", "dob": "2015-02-20"},
            "PARTNERSHIP_DEED": {"kind": "deed", "pdf": True},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "MEHTA AND SONS ELECTRONICS",
                                "trade_name": "MEHTA ELECTRONICS", "constitution": "Partnership", "date": "2017-07-01",
                                "address": "Shop 7, Lamington Road, Mumbai, Maharashtra 400007"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "fix": {"form": {"gstin": make_gstin("27", MEHTA_PAN, "2")},
                "documents": {"GST_CERTIFICATE": {"kind": "gst", "legal_name": "MEHTA AND SONS ELECTRONICS",
                                                  "trade_name": "MEHTA ELECTRONICS", "constitution": "Partnership",
                                                  "date": "2024-03-01", "gstin": make_gstin("27", MEHTA_PAN, "2"),
                                                  "address": "Shop 7, Lamington Road, Mumbai, Maharashtra 400007"}}},
        "scenarios": {},
    },
    "blurred_document": {
        "title": "Blurred PAN → re-upload",
        "story": "The PAN card photo is too blurred to read. Validation stops before any provider is called and the "
                 "merchant is asked for a clearer photo; after re-upload the application continues.",
        "business_type": "proprietorship", "category": "apparel",
        "form": {"legal_name": "Anita Sharma", "trade_name": "Sharma Textiles", "contact_name": "Anita Sharma",
                 "phone": "9900112233", "email": "anita@sharmatextiles.example.com", "address": "22 Chickpet Main Road",
                 "city": "Bengaluru", "state": "Karnataka", "pincode": "560053", "monthly_volume": 450000,
                 "pan": SHARMA_PAN, "gstin": make_gstin("29", SHARMA_PAN),
                 **_bank("002301556677", "ICIC0000002", "Anita Sharma", "ICICI Bank")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "ANITA SHARMA", "dob": "1990-11-03", "blur": True},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "ANITA SHARMA", "trade_name": "SHARMA TEXTILES",
                                "constitution": "Proprietorship", "date": "2019-04-15",
                                "address": "22 Chickpet Main Road, Bengaluru, Karnataka 560053"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "fix": {"form": {}, "documents": {"PAN_CARD": {"kind": "pan", "name": "ANITA SHARMA", "dob": "1990-11-03"}}},
        "scenarios": {},
    },
    "name_mismatch": {
        "title": "Bank name mismatch → human review",
        "story": "Private limited company. The penny-drop returns a different beneficiary name than the company. "
                 "The agent can't resolve this itself, so a reviewer gets an AI summary and decides.",
        "business_type": "private_limited", "category": "software",
        "form": {"legal_name": "Nexa Softworks Private Limited", "trade_name": "Nexa Softworks",
                 "contact_name": "Rahul Iyer", "phone": "9886001122", "email": "finance@nexasoft.example.com",
                 "address": "3rd Floor, 80 Feet Road, Indiranagar", "city": "Bengaluru", "state": "Karnataka",
                 "pincode": "560038", "monthly_volume": 2500000, "pan": NEXA_PAN,
                 "gstin": make_gstin("29", NEXA_PAN), "cin": "U72200KA2019PTC123456",
                 **_bank("917020011111", "UTIB0000009", "Nexa Softworks Private Limited", "Axis Bank")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "NEXA SOFTWORKS PRIVATE LIMITED", "dob": "2019-06-18"},
            "INCORPORATION_CERTIFICATE": {"kind": "coi", "company_name": "NEXA SOFTWORKS PRIVATE LIMITED",
                                          "cin": "U72200KA2019PTC123456", "date": "2019-06-18", "pdf": True},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "NEXA SOFTWORKS PRIVATE LIMITED",
                                "trade_name": "NEXA SOFTWORKS", "constitution": "Private Limited Company",
                                "date": "2019-09-01", "address": "80 Feet Road, Indiranagar, Bengaluru 560038"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "scenarios": {},
    },
    "duplicate": {
        "title": "Duplicate merchant → review",
        "story": "Same PAN and GSTIN as the happy-path merchant, a new trade name and a different bank account. "
                 "Entity matching flags it; a reviewer decides. (Run the happy path first.)",
        "business_type": "proprietorship", "category": "food_beverage",
        "form": {"legal_name": "Ravi Kumar", "trade_name": "Kumar Chai Corner Express", "contact_name": "Ravi Kumar",
                 "phone": "9845012399", "email": "ravi.express@example.com", "address": "88, 1st Main, Koramangala",
                 "city": "Bengaluru", "state": "Karnataka", "pincode": "560034", "monthly_volume": 500000,
                 "pan": KUMAR_PAN, "gstin": make_gstin("29", KUMAR_PAN),
                 **_bank("50100998877665", "SBIN0000813", "Ravi Kumar", "State Bank of India")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "RAVI KUMAR", "dob": "1986-04-12"},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "RAVI KUMAR", "trade_name": "KUMAR CHAI CORNER EXPRESS",
                                "constitution": "Proprietorship", "date": "2021-07-01",
                                "address": "88, 1st Main, Koramangala, Bengaluru, Karnataka 560034"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "scenarios": {},
    },
    "high_risk_mid_failure": {
        "title": "High risk → approve → MID failure → retry",
        "story": "Online-gaming company: high-risk category, so the agent escalates. After a reviewer approves, the "
                 "merchant-ID service fails three times (auto-retries), ops clicks Retry and it goes live.",
        "business_type": "private_limited", "category": "gaming",
        "form": {"legal_name": "Lucky Star Gaming Private Limited", "trade_name": "Lucky Star",
                 "contact_name": "Vikram Rao", "phone": "9811223344", "email": "ops@luckystar.example.com",
                 "address": "Unit 401, Bandra Kurla Complex", "city": "Mumbai", "state": "Maharashtra",
                 "pincode": "400051", "monthly_volume": 9000000, "pan": LUCKY_PAN,
                 "gstin": make_gstin("27", LUCKY_PAN), "cin": "U92490MH2025PTC456789",
                 **_bank("1234509876", "KKBK0000958", "Lucky Star Gaming Private Limited", "Kotak Mahindra Bank")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "LUCKY STAR GAMING PRIVATE LIMITED", "dob": "2025-01-10"},
            "INCORPORATION_CERTIFICATE": {"kind": "coi", "company_name": "LUCKY STAR GAMING PRIVATE LIMITED",
                                          "cin": "U92490MH2025PTC456789", "date": "2025-01-10"},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "LUCKY STAR GAMING PRIVATE LIMITED",
                                "trade_name": "LUCKY STAR", "constitution": "Private Limited Company",
                                "date": "2025-08-01", "address": "Unit 401, Bandra Kurla Complex, Mumbai 400051"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "scenarios": {"MID": "fail_3"},
    },
    "late_callback": {
        "title": "Late callback → timeout → retry",
        "story": "The GST provider is slow: no callback before the 45 s deadline, so the check times out and the "
                 "agent retries it. Attempt 2 passes; attempt 1's late result arrives afterwards and is recorded as "
                 "stale without changing anything.",
        "business_type": "proprietorship", "category": "healthcare",
        "form": {"legal_name": "Priya Nair", "trade_name": "Nair Ayurveda Store", "contact_name": "Priya Nair",
                 "phone": "9447011223", "email": "priya@nairayurveda.example.com", "address": "MG Road, Ernakulam",
                 "city": "Kochi", "state": "Kerala", "pincode": "682011", "monthly_volume": 200000,
                 "pan": NAIR_PAN, "gstin": make_gstin("32", NAIR_PAN),
                 **_bank("50100776655443", "HDFC0000001", "Priya Nair", "HDFC Bank")},
        "documents": {
            "PAN_CARD": {"kind": "pan", "name": "PRIYA NAIR", "dob": "1992-01-25"},
            "GST_CERTIFICATE": {"kind": "gst", "legal_name": "PRIYA NAIR", "trade_name": "NAIR AYURVEDA STORE",
                                "constitution": "Proprietorship", "date": "2020-10-05",
                                "address": "MG Road, Ernakulam, Kochi, Kerala 682011"},
            "BANK_PROOF": {"kind": "cheque"},
        },
        "scenarios": {"GST": "late_once"},
    },
}


def sample_filename(slot: str, spec: dict, fixed: bool = False) -> str:
    ext = "pdf" if spec.get("pdf") else "png"
    return f"{slot.lower()}{'_fixed' if fixed else ''}.{ext}"
