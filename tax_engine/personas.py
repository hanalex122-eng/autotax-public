"""Validation-suite personas (mirrors knowledge/coverage_report_v2.json).

Each persona = (id, profile flags, expected base form keys). Instance markers
(#n) from the coverage report are dropped here; instance counts are checked
separately via detection._instance_count. Used by tax_engine.tests.
"""
from __future__ import annotations

PERSONAS: list[dict] = [
    {"id": "p01_single_employee", "profile": {"employment": True, "commute": True, "homeoffice": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_vorsorge"}},
    {"id": "p02_married_one_earner", "profile": {"employment": True, "married": True, "spouse_income": False},
     "expected": {"hauptvordruck", "anlage_n", "anlage_vorsorge"}},
    {"id": "p03_family_two_children", "profile": {"employment": True, "married": True, "children": 2, "childcare": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_vorsorge", "anlage_kind"}},
    {"id": "p04_pensioner", "profile": {"pension": True},
     "expected": {"hauptvordruck", "anlage_r", "anlage_vorsorge"}},
    {"id": "p05_student_second_degree", "profile": {"employment": True, "student": True, "second_degree": True},
     "expected": {"hauptvordruck", "anlage_n"}},
    {"id": "p06_freelancer", "profile": {"freelance": True, "kleinunternehmer": False},
     "expected": {"hauptvordruck", "anlage_s", "anlage_euer", "ust_1a", "anlage_vorsorge"}},
    {"id": "p07_gewerbe_owner", "profile": {"gewerbe": True, "kleinunternehmer": False, "profit": 60000},
     "expected": {"hauptvordruck", "anlage_g", "anlage_euer", "ust_1a", "gewst_1a", "anlage_vorsorge"}},
    {"id": "p08_doener_shop", "profile": {"gewerbe": True, "kleinunternehmer": False, "profit": 45000, "business": "doener_shop"},
     "expected": {"hauptvordruck", "anlage_g", "anlage_euer", "ust_1a", "gewst_1a"}},
    {"id": "p09_barber_shop", "profile": {"gewerbe": True, "kleinunternehmer": False, "profit": 30000, "business": "barber_shop"},
     "expected": {"hauptvordruck", "anlage_g", "anlage_euer", "ust_1a", "gewst_1a"}},
    {"id": "p10_landlord", "profile": {"rental": True, "properties": 1},
     "expected": {"hauptvordruck", "anlage_v", "anlage_vorsorge"}},
    {"id": "p11_remote_worker", "profile": {"employment": True, "homeoffice": True, "commute": False},
     "expected": {"hauptvordruck", "anlage_n", "anlage_vorsorge"}},
    {"id": "p12_investor", "profile": {"employment": True, "capital_income": True, "capital_inv": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_kap", "anlage_kap_inv"}},
    {"id": "p13_foreign_income", "profile": {"employment": True, "foreign_income": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_aus"}},
    {"id": "p14_church_tax", "profile": {"employment": True, "church_member": True, "donations": True},
     "expected": {"hauptvordruck", "anlage_n"}},
    {"id": "p15_mixed_employment_selfemployed", "profile": {"employment": True, "freelance": True, "kleinunternehmer": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_s", "anlage_euer", "anlage_vorsorge"}},
    {"id": "p16_disabled_taxpayer", "profile": {"employment": True, "disability": True, "gdb": 60},
     "expected": {"hauptvordruck", "anlage_n", "aussergewoehnliche", "anlage_vorsorge"}},
    {"id": "p17_parent_disabled_child", "profile": {"employment": True, "children": 1, "disabled_child": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_kind"}},
    {"id": "p18_energetic_renovation", "profile": {"employment": True, "owns_home": True, "energetic": True},
     "expected": {"hauptvordruck", "anlage_n", "energetisch"}},
    {"id": "p19_handwerker_household", "profile": {"employment": True, "handwerker": True},
     "expected": {"hauptvordruck", "anlage_n", "haushaltsnah"}},
    {"id": "p20_married_both_earners_kids", "profile": {"employment": True, "married": True, "spouse_income": True, "children": 2, "rental": True, "donations": True, "church_member": True},
     "expected": {"hauptvordruck", "anlage_n", "anlage_v", "anlage_kind", "anlage_vorsorge"}},
    {"id": "p21_widow_pension_capital", "profile": {"pension": True, "capital_income": True, "widow": True},
     "expected": {"hauptvordruck", "anlage_r", "anlage_kap", "anlage_vorsorge"}},
    {"id": "p22_riester_saver", "profile": {"employment": True, "riester": True, "children": 1},
     "expected": {"hauptvordruck", "anlage_n", "anlage_av", "anlage_kind", "anlage_vorsorge"}},
]

# Personas whose multi-instance counts we assert explicitly.
INSTANCE_EXPECTATIONS = {
    "p03_family_two_children": {"anlage_kind": 2},
    "p20_married_both_earners_kids": {"anlage_n": 2, "anlage_kind": 2},
    "p22_riester_saver": {"anlage_kind": 1},
}
